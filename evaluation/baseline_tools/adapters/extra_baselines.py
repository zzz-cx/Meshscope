#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Additional external / stand-in baselines for F-suite comparison.

- S-KubectlDryRun: kubectl apply --dry-run=client|server (admission/schema gate)
- S-PolicyLite: Gatekeeper/Kyverno-style admission rules (hand-written, limited)
- S-LintBP: kube-linter-style best-practice checks (labels/security; weak on Istio)
- S-SchemaCRD: lightweight CRD field presence checks (schema-ish)

Real binaries (kube-linter / kubeconform / checkov / kyverno) are preferred when
present on PATH or under evaluation/baseline_tools/bin/.
"""
from __future__ import print_function

import os
import re

import yaml

from .base import empty_result, merge_yamls, now_iso, run_cmd, which
from . import kube_tools

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _bin(name):
    local = os.path.join(BIN_DIR, name)
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return which(name)


def _fault(config_file, fault_type, desc, conf, tool):
    return {
        "config_file": config_file,
        "fault_type": fault_type,
        "confidence": conf,
        "description": desc,
        "details": {"tool": tool},
        "detection_time": now_iso(),
    }


def _load_docs(path):
    with open(path, "r") as f:
        return [d for d in yaml.safe_load_all(f) if isinstance(d, dict)]


# ---------------------------------------------------------------------------
# Real tools if installed
# ---------------------------------------------------------------------------

def detect_kube_linter(config_file, mapping=None):
    # Prefer local bin
    path = _bin("kube-linter")
    if path and not which("kube-linter"):
        os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
    return kube_tools.detect_kube_linter(config_file, mapping or {})


def detect_kubeconform(config_file, mapping=None):
    """kubeconform; only count real validation errors (ignore skipped/status OK)."""
    result = empty_result("S-Schema", config_file)
    path = _bin("kubeconform")
    if not path:
        result["available"] = False
        result["error"] = "kubeconform not installed"
        return result
    tmp = merge_yamls([config_file])
    try:
        # -ignore-missing-schemas: Istio CRDs often not in default catalog
        cmd = [path, "-summary", "-output", "json", "-ignore-missing-schemas", tmp]
        rc, out, err = run_cmd(cmd, timeout=60)
        result["raw"] = {"returncode": rc, "stdout": (out or "")[:4000], "stderr": (err or "")[:1000], "tool": "kubeconform"}
        faults = []
        try:
            import json
            data = json.loads(out) if out.strip() else {}
            resources = []
            if isinstance(data, dict):
                resources = data.get("resources") or []
            elif isinstance(data, list):
                resources = data
            for item in resources:
                status = str((item or {}).get("status") or "").lower()
                msg = (item or {}).get("msg") or (item or {}).get("message") or ""
                if status in ("statuserror", "error") or (msg and "error" in str(msg).lower()):
                    faults.append(_fault(
                        config_file, "schema_validation_error",
                        str(msg or status)[:300], 0.85, "kubeconform"))
        except Exception:
            if rc != 0 and "error" in ((out or "") + (err or "")).lower():
                faults.append(_fault(
                    config_file, "schema_validation_error",
                    ((out or err)[:300]), 0.8, "kubeconform"))
        result["detected_faults"] = faults
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return result


def detect_checkov(config_file, mapping=None):
    result = empty_result("S-Checkov", config_file)
    path = _bin("checkov")
    if not path:
        # python -m checkov
        rc, out, err = run_cmd(["python3", "-m", "checkov", "-h"], timeout=20)
        if rc != 0:
            result["available"] = False
            result["error"] = "checkov not installed"
            return result
        path = "python3"
        cmd = ["python3", "-m", "checkov", "-f", config_file, "-o", "json", "--quiet"]
    else:
        cmd = [path, "-f", config_file, "-o", "json", "--quiet"]
    rc, out, err = run_cmd(cmd, timeout=120)
    result["raw"] = {"returncode": rc, "stdout": (out or "")[:6000], "stderr": (err or "")[:1500]}
    faults = []
    try:
        import json
        data = json.loads(out) if out.strip().startswith("{") or out.strip().startswith("[") else {}
        # checkov json: results.failed_checks
        failed = []
        if isinstance(data, dict):
            res = data.get("results") or {}
            failed = res.get("failed_checks") or []
            if not failed and isinstance(data.get("failed"), list):
                failed = data["failed"]
        for item in failed:
            msg = ""
            if isinstance(item, dict):
                msg = item.get("check_name") or item.get("check_id") or str(item)
            faults.append(_fault(
                config_file, "generic_config_error", str(msg)[:300], 0.75, "checkov"))
    except Exception as e:
        if rc != 0 and (out or err):
            faults.append(_fault(
                config_file, "generic_config_error",
                (out or err)[:300], 0.7, "checkov"))
        result["raw"]["parse_error"] = str(e)
    # dedupe
    seen = set()
    uniq = []
    for f in faults:
        if f["fault_type"] + f["description"] not in seen:
            seen.add(f["fault_type"] + f["description"])
            uniq.append(f)
    result["detected_faults"] = uniq
    return result


def detect_kyverno(config_file, mapping=None, policy_dir=None):
    """kyverno apply -f config --policy policy_dir (if CLI + policies exist)."""
    result = empty_result("S-Kyverno", config_file)
    path = _bin("kyverno")
    if not path:
        result["available"] = False
        result["error"] = "kyverno CLI not installed"
        return result
    policy_dir = policy_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs", "kyverno_policies")
    if not os.path.isdir(policy_dir) or not os.listdir(policy_dir):
        result["available"] = False
        result["error"] = "no kyverno policies in {0}".format(policy_dir)
        return result
    rc, out, err = run_cmd(
        [path, "apply", policy_dir, "--resource", config_file], timeout=90)
    result["raw"] = {"returncode": rc, "stdout": (out or "")[:4000], "stderr": (err or "")[:1500]}
    text = (out or "") + "\n" + (err or "")
    faults = []
    # Parse summary: "pass: X, fail: Y"
    m = re.search(r"fail:\s*(\d+)", text)
    fail_n = int(m.group(1)) if m else 0
    # Also capture explicit policy failure messages
    for line in text.splitlines():
        low = line.lower().strip()
        if not low:
            continue
        if low.startswith("pass:") or low.startswith("applying "):
            continue
        if "failed" in low or "violat" in low or (low.startswith("error") and "error: 0" not in low):
            ft = "generic_config_error"
            if "subset" in low:
                ft = "missing_subset"
            elif "authoriz" in low:
                ft = "authorization_conflict"
            elif "mtls" in low or "disable" in low or "peerauthentication" in low:
                ft = "mtls_inconsistency"
            elif "weight" in low:
                ft = "weight_error"
            faults.append(_fault(config_file, ft, line.strip()[:300], 0.8, "kyverno"))
    if fail_n > 0 and not faults:
        # Failed but no detailed line — map by resource content heuristics
        blob = open(config_file).read().lower()
        ft = "generic_config_error"
        if "mode: disable" in blob and "strict" in blob:
            ft = "mtls_inconsistency"
        elif "weight:" in blob:
            ft = "weight_error"
        faults.append(_fault(
            config_file, ft,
            "kyverno policy fail count={0}".format(fail_n), 0.8, "kyverno"))
    seen = set()
    uniq = []
    for f in faults:
        key = f["fault_type"]
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    result["detected_faults"] = uniq
    return result


# ---------------------------------------------------------------------------
# kubectl dry-run (always available with kubectl)
# ---------------------------------------------------------------------------

def detect_kubectl_dryrun(config_file, mapping=None, mode="client"):
    """
    mode: client | server
    Maps any rejection to schema/admission style fault (usually misses semantic Istio faults).
    """
    method = "S-KubectlDryRun-" + mode
    result = empty_result(method, config_file)
    if not which("kubectl"):
        result["available"] = False
        result["error"] = "kubectl not found"
        return result
    tmp = merge_yamls([config_file])
    try:
        cmd = ["kubectl", "apply", "--dry-run={0}".format(mode), "-f", tmp]
        if mode == "server":
            cmd.append("--validate=true")
        rc, out, err = run_cmd(cmd, timeout=60)
        result["raw"] = {"returncode": rc, "stdout": (out or "")[:2000], "stderr": (err or "")[:2000], "mode": mode}
        text = (out or "") + "\n" + (err or "")
        if rc != 0:
            ft = "schema_validation_error"
            low = text.lower()
            if "authoriz" in low:
                ft = "authorization_conflict"
            elif "subset" in low:
                ft = "missing_subset"
            result["detected_faults"] = [_fault(
                config_file, ft, text.strip()[:400], 0.85, method)]
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Policy-lite (Gatekeeper/Kyverno stand-in with fixed Istio-ish policies)
# Intentionally narrow: only a few admission-style rules.
# ---------------------------------------------------------------------------

def detect_policy_lite(config_file, mapping=None):
    """
    Admission-style rules similar to what operators often encode in Gatekeeper:
      P1: VS route weights must sum to 100 when present
      P2: DestinationRule tls mode must not be DISABLE if PeerAuthentication STRICT exists
      P3: forbid AuthorizationPolicy ALLOW+DENY on same selector
    Does NOT cover timeout/retry/CB/runtime gaps.
    """
    result = empty_result("S-PolicyLite", config_file)
    docs = _load_docs(config_file)
    faults = []
    vs_list = [d for d in docs if d.get("kind") == "VirtualService"]
    dr_list = [d for d in docs if d.get("kind") == "DestinationRule"]
    ap_list = [d for d in docs if d.get("kind") == "AuthorizationPolicy"]
    pa_list = [d for d in docs if d.get("kind") == "PeerAuthentication"]

    for vs in vs_list:
        for http in (vs.get("spec") or {}).get("http") or []:
            routes = http.get("route") or []
            if len(routes) >= 2:
                w = sum((r.get("weight") or 0) for r in routes)
                if w not in (0, 100):
                    faults.append(_fault(
                        config_file, "weight_error",
                        "policy: route weights sum to {0}".format(w), 0.9, "S-PolicyLite"))

    strict = any(((p.get("spec") or {}).get("mtls") or {}).get("mode") == "STRICT" for p in pa_list)
    if strict:
        for dr in dr_list:
            mode = (((dr.get("spec") or {}).get("trafficPolicy") or {}).get("tls") or {}).get("mode")
            if mode == "DISABLE":
                faults.append(_fault(
                    config_file, "mtls_inconsistency",
                    "policy: STRICT PeerAuthentication vs DR tls DISABLE", 0.9, "S-PolicyLite"))

    selectors = []
    actions = []
    for ap in ap_list:
        sel = ((ap.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
        act = (ap.get("spec") or {}).get("action") or "ALLOW"
        selectors.append(tuple(sorted(sel.items())))
        actions.append(act)
    if len(ap_list) >= 2 and len(set(selectors)) == 1 and ("ALLOW" in actions and "DENY" in actions):
        faults.append(_fault(
            config_file, "authorization_conflict",
            "policy: ALLOW+DENY AuthorizationPolicy on same selector", 0.9, "S-PolicyLite"))

    seen = set()
    uniq = []
    for f in faults:
        if f["fault_type"] not in seen:
            seen.add(f["fault_type"])
            uniq.append(f)
    result["detected_faults"] = uniq
    result["raw"] = {"mode": "admission_policy_lite", "n_rules": 3}
    return result


def detect_lint_bp(config_file, mapping=None):
    """
    Best-practice / security lint stand-in (kube-linter-like):
      - require app label on workloads (N/A for pure Istio YAML → usually nothing)
      - warn on empty metadata.name
    Intentionally does NOT understand Istio traffic semantics.
    """
    result = empty_result("S-LintBP", config_file)
    docs = _load_docs(config_file)
    faults = []
    for d in docs:
        md = d.get("metadata") or {}
        if not md.get("name"):
            faults.append(_fault(
                config_file, "generic_config_error",
                "missing metadata.name on {0}".format(d.get("kind")), 0.8, "S-LintBP"))
        # Istio resources rarely have securityContext — do not false-flag
    result["detected_faults"] = faults
    result["raw"] = {"mode": "best_practice_lint"}
    return result


def detect_schema_crd(config_file, mapping=None):
    """
    Lightweight schema-ish checks: required apiVersion/kind/metadata, VS hosts present.
    Does not load full OpenAPI CRDs (use kubeconform when available).
    """
    result = empty_result("S-SchemaCRD", config_file)
    docs = _load_docs(config_file)
    faults = []
    for d in docs:
        kind = d.get("kind")
        if not d.get("apiVersion") or not kind or not (d.get("metadata") or {}).get("name"):
            faults.append(_fault(
                config_file, "schema_validation_error",
                "missing apiVersion/kind/metadata.name", 0.9, "S-SchemaCRD"))
            continue
        if kind == "VirtualService":
            hosts = (d.get("spec") or {}).get("hosts")
            if not hosts:
                faults.append(_fault(
                    config_file, "schema_validation_error",
                    "VirtualService missing spec.hosts", 0.85, "S-SchemaCRD"))
        if kind == "DestinationRule":
            if not (d.get("spec") or {}).get("host"):
                faults.append(_fault(
                    config_file, "schema_validation_error",
                    "DestinationRule missing spec.host", 0.85, "S-SchemaCRD"))
    seen = set()
    uniq = []
    for f in faults:
        if f["description"] not in seen:
            seen.add(f["description"])
            uniq.append(f)
    result["detected_faults"] = uniq
    result["raw"] = {"mode": "lightweight_crd_fields"}
    return result
