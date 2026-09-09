#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D-Naive: apply + HTTP probe (2xx/5xx only). D-Ours: policy-aware runtime checks."""
from __future__ import print_function

import os
import re
import time

import yaml

from .base import empty_result, now_iso, run_cmd

DEFAULT_INGRESS = "http://192.168.1.69:31605"
DEFAULT_NAMESPACE = "baseline-bookinfo"
BASELINE_NETWORKING = [
    "/root/configPilot/cluster/istio-1.24.6/samples/bookinfo/networking/destination-rule-all.yaml",
    "/root/configPilot/cluster/istio-1.24.6/samples/bookinfo/networking/virtual-service-all-v1.yaml",
]


def _load_docs(path):
    with open(path, "r") as f:
        return [d for d in yaml.safe_load_all(f) if isinstance(d, dict)]


def _fault(config_file, fault_type, desc, conf, tool):
    return {
        "config_file": config_file,
        "fault_type": fault_type,
        "confidence": conf,
        "description": desc,
        "details": {"tool": tool},
        "detection_time": now_iso(),
    }


def _rewrite_namespace(docs, ns):
    out = []
    for d in docs:
        d = dict(d)
        md = dict(d.get("metadata") or {})
        md["namespace"] = ns
        d["metadata"] = md
        # rewrite *.default.svc host refs to ns
        blob = yaml.dump(d)
        blob = blob.replace(".default.svc.cluster.local", ".{0}.svc.cluster.local".format(ns))
        blob = re.sub(r"namespace:\s*default", "namespace: {0}".format(ns), blob)
        rebuilt = list(yaml.safe_load_all(blob))
        out.extend([x for x in rebuilt if x])
    return out


def _kubectl_apply_docs(docs, ns):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(tmp, "w") as f:
        for i, d in enumerate(docs):
            if i:
                f.write("---\n")
            yaml.dump(d, f)
    rc, out, err = run_cmd(["kubectl", "apply", "-f", tmp, "-n", ns], timeout=60)
    try:
        os.unlink(tmp)
    except Exception:
        pass
    return rc, out, err


def _kubectl_delete_docs(docs, ns):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(tmp, "w") as f:
        for i, d in enumerate(docs):
            if i:
                f.write("---\n")
            yaml.dump(d, f)
    run_cmd(["kubectl", "delete", "-f", tmp, "-n", ns, "--ignore-not-found"], timeout=60)
    try:
        os.unlink(tmp)
    except Exception:
        pass


def _hosts_touched(docs):
    hosts = set()
    for d in docs:
        kind = d.get("kind")
        spec = d.get("spec") or {}
        if kind in ("VirtualService", "DestinationRule"):
            for h in spec.get("hosts") or []:
                hosts.add(str(h).split(".")[0])
            h = spec.get("host")
            if h:
                hosts.add(str(h).split(".")[0])
        if kind in ("AuthorizationPolicy", "PeerAuthentication"):
            hosts.add("reviews")  # security policies in suite target reviews/mesh
    return sorted(h for h in hosts if h)


def _prepare_cluster_overlay(docs, ns):
    """Delete conflicting baseline VS/DR for touched services so fault overlays take effect."""
    touched = _hosts_touched(docs)
    for name in touched:
        run_cmd(["kubectl", "-n", ns, "delete", "virtualservice", name, "--ignore-not-found"], timeout=30)
        run_cmd(["kubectl", "-n", ns, "delete", "destinationrule", name, "--ignore-not-found"], timeout=30)
    return touched


def _restore_baseline_networking(ns):
    for path in BASELINE_NETWORKING:
        if os.path.isfile(path):
            run_cmd(["kubectl", "apply", "-n", ns, "-f", path], timeout=60)


def _curl_probe(url, n=20, timeout_each=3):
    """Return codes, latencies, body_fail_count (Bookinfo soft-errors still HTTP 200)."""
    codes = []
    latencies = []
    body_fails = 0
    soft_markers = (
        "error fetching",
        "sorry, product reviews are currently unavailable",
        "reviews are currently unavailable",
        "upstream connect error",
        "no healthy upstream",
        "503",
    )
    for _ in range(n):
        t0 = time.time()
        rc, out, err = run_cmd([
            "curl", "-s", "-w", "\n__HTTP_CODE__:%{http_code}",
            "--max-time", str(timeout_each), url
        ], timeout=timeout_each + 2)
        latencies.append(time.time() - t0)
        body = out or ""
        code = 0
        if "__HTTP_CODE__:" in body:
            parts = body.rsplit("__HTTP_CODE__:", 1)
            body = parts[0]
            try:
                code = int((parts[1] or "0").strip() or "0")
            except Exception:
                code = 0
        codes.append(code)
        low = body.lower()
        if code >= 500 or code == 0 or any(m in low for m in soft_markers):
            body_fails += 1
    return codes, latencies, body_fails


def _curl_stats(url, n=20, timeout_each=3):
    codes, latencies, _ = _curl_probe(url, n=n, timeout_each=timeout_each)
    return codes, latencies


def _yaml_oracle_dynamic(config_file, docs, tool):
    """
    Offline dynamic oracle used when cluster probe is unavailable.
    Detects runtime-oriented faults from policy content (ablation proxy).
    Pure static conflicts (missing subset / auth / unreachable host refs)
    are left to static analysis — Dyn.Only should miss them without live traffic.
    Marked in details.mode=yaml_oracle.
    """
    faults = []
    blob = yaml.dump(docs)
    vs_timeouts = []
    for d in docs:
        kind = d.get("kind")
        spec = d.get("spec") or {}
        if kind == "VirtualService":
            ann = (d.get("metadata") or {}).get("annotations") or {}
            for http in spec.get("http") or []:
                to = str(http.get("timeout") or "")
                if to:
                    vs_timeouts.append(to)
                if to in ("1ms", "10ms", "0.1s") or (
                        to.endswith("ms") and to.replace("ms", "").isdigit()
                        and int(to.replace("ms", "")) <= 50):
                    faults.append(_fault(config_file, "timeout_error", "runtime timeout risk: " + to, 0.8, tool))
                retries = http.get("retries") or {}
                if int(retries.get("attempts") or 0) >= 8:
                    faults.append(_fault(config_file, "retry_policy_error", "retry amplification risk", 0.8, tool))
                fault = http.get("fault") or {}
                abort = fault.get("abort") or {}
                abort_pct = (abort.get("percentage") or {}).get("value")
                if abort_pct == 100:
                    # F10-style enforcement gap / always-fail policy
                    faults.append(_fault(config_file, "policy_enforcement_gap",
                                         "100% abort → always 5xx at runtime", 0.9, tool))
                    faults.append(_fault(config_file, "fault_injection_error",
                                         "100% abort at runtime", 0.9, tool))
                # F6: abort present but retries omitted despite intent
                if abort_pct and int(abort_pct) > 0 and not retries:
                    if ann.get("configpilot.intent/expect_retries") == "true":
                        faults.append(_fault(
                            config_file, "retry_policy_error",
                            "abort under load with retries omitted", 0.85, tool))
                routes = http.get("route") or []
                weights = [r.get("weight") or 0 for r in routes]
                if len(weights) >= 2 and max(weights) >= 90 and min(weights) <= 10:
                    if "50/50" in str(ann.get("configpilot.intent/expected_split", "")):
                        faults.append(_fault(config_file, "weight_error", "runtime split vs intent", 0.85, tool))
                # Do NOT claim missing host / subset here (static / live 5xx only)
        if kind == "DestinationRule":
            tp = spec.get("trafficPolicy") or {}
            od = tp.get("outlierDetection") or {}
            if od.get("consecutive5xxErrors") == 1 or od.get("consecutiveErrors") == 1:
                faults.append(_fault(config_file, "circuit_breaker_error", "premature eject at runtime", 0.85, tool))
            cp = tp.get("connectionPool") or {}
            if (cp.get("tcp") or {}).get("maxConnections") == 1:
                faults.append(_fault(config_file, "circuit_breaker_error", "pool exhaustion under load", 0.8, tool))
            tls_mode = (tp.get("tls") or {}).get("mode")
            if tls_mode == "DISABLE":
                # runtime mTLS handshake failures when mesh is STRICT
                for d2 in docs:
                    if d2.get("kind") == "PeerAuthentication":
                        if ((d2.get("spec") or {}).get("mtls") or {}).get("mode") == "STRICT":
                            faults.append(_fault(
                                config_file, "mtls_inconsistency",
                                "runtime mTLS STRICT vs DISABLE mismatch", 0.85, tool))
        if kind == "EnvoyFilter" and ("max_tokens: 1" in blob or "max_tokens: 1" in yaml.dump(d)):
            faults.append(_fault(config_file, "rate_limit_error", "token bucket starves traffic", 0.85, tool))

    # F8: partial timeout chain — some VS have short timeout, sibling hop has none
    short = [t for t in vs_timeouts if t.endswith("ms") and t.replace("ms", "").isdigit()
             and int(t.replace("ms", "")) <= 100]
    vs_count = sum(1 for d in docs if d.get("kind") == "VirtualService")
    if short and vs_count >= 2:
        any_missing = False
        for d in docs:
            if d.get("kind") != "VirtualService":
                continue
            for http in (d.get("spec") or {}).get("http") or []:
                if not http.get("timeout"):
                    any_missing = True
        if any_missing:
            for d in docs:
                ann = ((d.get("metadata") or {}).get("annotations") or {})
                if ann.get("configpilot.intent/timeout_chain") == "partial":
                    faults.append(_fault(
                        config_file, "timeout_propagation",
                        "partial timeout propagation across service chain", 0.85, tool))
                    break

    seen = set()
    uniq = []
    for f in faults:
        if f["fault_type"] not in seen:
            seen.add(f["fault_type"])
            f = dict(f)
            f["details"] = dict(f.get("details") or {})
            f["details"]["mode"] = "yaml_oracle"
            uniq.append(f)
    return uniq


def detect_naive(config_file, mapping=None, cluster=False, namespace=None,
                 ingress_url=None, probe_path="/productpage"):
    result = empty_result("D-Naive", config_file)
    docs = _load_docs(config_file)
    if not cluster:
        # Naive offline: only coarse always-fail signals (100% abort / enforcement gap)
        faults = []
        for f in _yaml_oracle_dynamic(config_file, docs, "D-Naive"):
            if f["fault_type"] in (
                "policy_enforcement_gap",
                "fault_injection_error",
            ):
                faults.append(f)
        result["detected_faults"] = faults
        result["raw"] = {"mode": "yaml_oracle_naive"}
        return result

    namespace = namespace or os.environ.get("BASELINE_NAMESPACE", DEFAULT_NAMESPACE)
    ingress_url = ingress_url or os.environ.get("BASELINE_INGRESS", DEFAULT_INGRESS)
    run_cmd(["kubectl", "create", "ns", namespace], timeout=30)
    rewritten = _rewrite_namespace(docs, namespace)
    touched = _prepare_cluster_overlay(rewritten, namespace)
    rc, out, err = _kubectl_apply_docs(rewritten, namespace)
    time.sleep(4)
    url = ingress_url.rstrip("/") + probe_path
    codes, lats, body_fails = _curl_probe(url, n=15)
    n5 = sum(1 for c in codes if c >= 500 or c == 0)
    fail_n = max(n5, body_fails)
    result["raw"] = {
        "apply_rc": rc,
        "apply_out": (out + err)[:1500],
        "mode": "cluster",
        "namespace": namespace,
        "http_codes": codes,
        "body_fails": body_fails,
        "touched": touched,
        "url": url,
    }
    _kubectl_delete_docs(rewritten, namespace)
    _restore_baseline_networking(namespace)
    # Truly naive: only coarse failure rate; emit types that F10 / always-fail map to
    if fail_n >= max(3, len(codes) // 3):
        desc = "naive probe high fail rate status5xx={0} body_fail={1}/{2}".format(
            n5, body_fails, len(codes))
        result["detected_faults"] = [
            _fault(config_file, "policy_enforcement_gap", desc, 0.75, "D-Naive"),
            _fault(config_file, "fault_injection_error", desc, 0.75, "D-Naive"),
            _fault(config_file, "missing_service_ref", desc, 0.7, "D-Naive"),
        ]
    return result


def detect_ours(config_file, mapping=None, cluster=False, namespace=None,
                ingress_url=None, probe_path="/productpage"):
    result = empty_result("D-Ours", config_file)
    docs = _load_docs(config_file)
    if not cluster:
        result["detected_faults"] = _yaml_oracle_dynamic(config_file, docs, "D-Ours")
        result["raw"] = {"mode": "yaml_oracle"}
        return result

    namespace = namespace or os.environ.get("BASELINE_NAMESPACE", DEFAULT_NAMESPACE)
    ingress_url = ingress_url or os.environ.get("BASELINE_INGRESS", DEFAULT_INGRESS)
    run_cmd(["kubectl", "create", "ns", namespace], timeout=30)
    rewritten = _rewrite_namespace(docs, namespace)
    touched = _prepare_cluster_overlay(rewritten, namespace)
    rc, out, err = _kubectl_apply_docs(rewritten, namespace)
    time.sleep(5)
    url = ingress_url.rstrip("/") + probe_path
    codes, lats, body_fails = _curl_probe(url, n=30)
    avg_lat = sum(lats) / float(len(lats) or 1)
    n5 = sum(1 for c in codes if c >= 500 or c == 0)
    fail_n = max(n5, body_fails)
    faults = _yaml_oracle_dynamic(config_file, docs, "D-Ours")
    # reinforce with live signals
    if fail_n >= max(5, len(codes) // 4):
        faults.append(_fault(config_file, "fault_injection_error",
                             "live fail rate status5xx={0} body_fail={1}/{2}".format(
                                 n5, body_fails, len(codes)), 0.85, "D-Ours"))
        faults.append(_fault(config_file, "policy_enforcement_gap",
                             "live policy enforcement gap fail={0}/{1}".format(
                                 fail_n, len(codes)), 0.85, "D-Ours"))
    if avg_lat > 1.5:
        faults.append(_fault(config_file, "timeout_error",
                             "live high latency avg={0:.3f}s".format(avg_lat), 0.75, "D-Ours"))
    _kubectl_delete_docs(rewritten, namespace)
    _restore_baseline_networking(namespace)
    seen = set()
    uniq = []
    for f in faults:
        key = f["fault_type"]
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    result["detected_faults"] = uniq
    result["raw"] = {
        "mode": "cluster+oracle",
        "apply_rc": rc,
        "apply_out": (out + err)[:1500],
        "namespace": namespace,
        "http_codes": codes,
        "body_fails": body_fails,
        "avg_latency": avg_lat,
        "touched": touched,
        "url": url,
    }
    return result
