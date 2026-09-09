# -*- coding: utf-8 -*-
"""
Real cluster validation for orthogonal efficiency:

  kubectl apply (effect VS/DR) → curl ingress → assert → kubectl delete

Exhaustive: apply/clear per case.
Orthogonal bundle: one multi-route apply, traffic each member, one clear.
All timings are wall-clock (time.time()).
"""

from __future__ import print_function

import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# reuse deploy helpers from real_traffic_experiment
_RTE = Path(__file__).resolve().parents[2] / "real_traffic_experiment"
if str(_RTE) not in sys.path:
    sys.path.insert(0, str(_RTE))

from deploy_services import (  # noqa: E402
    deploy,
    wait_ready,
    wait_namespace_gone,
    svc_name as rte_svc_name,
)
from run_traffic import discover_ingress_url, curl_once  # noqa: E402


def kubectl(args, stdin=None, timeout=120):
    # type: (List[str], Optional[str], int) -> str
    proc = subprocess.run(
        ["kubectl"] + args,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "kubectl {0} failed: {1}".format(" ".join(args), proc.stderr or proc.stdout)
        )
    return proc.stdout or ""


def kubectl_delete_ignore(args, timeout=60):
    # type: (List[str], int) -> None
    subprocess.run(
        ["kubectl"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
    )


def _safe_name(s):
    # type: (str) -> str
    out = []
    for ch in s.lower():
        if ch.isalnum() or ch == "-":
            out.append(ch)
        else:
            out.append("-")
    name = "".join(out).strip("-")
    return name[:60] or "x"


def effect_expect_status(effect_id):
    # type: (str) -> int
    if effect_id in ("action_fault_abort",):
        return 503
    if effect_id in ("action_authz_deny", "pred_authz_header"):
        return 403
    return 200


def effect_requests(strategy):
    # type: (str) -> int
    # Real traffic volume for complete-ish validation (kept modest for wall-clock).
    m = {
        "routing": 2,
        "traffic_split": 8,
        "retry": 3,
        "timeout": 2,
        "fault_injection": 3,
        "rate_limit": 6,
        "circuit_breaker": 4,
        "connection_pool": 4,
        "connection_pool_outlier": 4,
        "mirroring": 3,
        "authorization": 2,
    }
    return int(m.get(strategy, 2))


def _http_route_for_unit(unit, ns):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    idx = int(unit["service_index"])
    svc = rte_svc_name(idx)
    effect = unit["effect_id"]
    path = unit.get("path") or "/s{0}/{1}/".format(idx, effect)
    expect = effect_expect_status(effect)

    match = {"uri": {"prefix": path}}
    route = {
        "name": _safe_name(unit["unit_id"]),
        "match": [match],
        "rewrite": {"uri": "/"},
        "route": [
            {
                "destination": {
                    "host": svc,
                    "subset": "v1",
                    "port": {"number": 80},
                }
            }
        ],
    }

    if effect in ("pred_header_user",):
        match["headers"] = {"x-meshscope-user": {"exact": "vip"}}
        route["route"][0]["destination"]["subset"] = "v2"
    elif effect in ("pred_header_role",):
        match["headers"] = {"x-meshscope-role": {"exact": "admin"}}
        route["route"][0]["destination"]["subset"] = "v2"
    elif effect == "action_traffic_split":
        route["route"] = [
            {
                "destination": {"host": svc, "subset": "v1", "port": {"number": 80}},
                "weight": 70,
            },
            {
                "destination": {"host": svc, "subset": "v2", "port": {"number": 80}},
                "weight": 30,
            },
        ]
    elif effect == "action_retry":
        route["retries"] = {
            "attempts": 3,
            "perTryTimeout": "2s",
            "retryOn": "connect-failure,refused-stream,unavailable,cancelled,5xx",
        }
    elif effect == "action_timeout":
        route["timeout"] = "3s"
    elif effect == "action_fault_abort":
        route["fault"] = {
            "abort": {"httpStatus": 503, "percentage": {"value": 100}}
        }
    elif effect == "action_fault_delay":
        route["fault"] = {
            "delay": {"fixedDelay": "0.05s", "percentage": {"value": 100}}
        }
    elif effect in ("action_authz_deny", "pred_authz_header"):
        route["fault"] = {
            "abort": {"httpStatus": 403, "percentage": {"value": 100}}
        }
    elif effect == "action_mirroring":
        route["mirror"] = {"host": svc, "subset": "v2"}
        route["mirrorPercentage"] = {"value": 50.0}

    route["_expect_status"] = expect
    route["_path"] = path
    route["_headers"] = {}
    if "headers" in match:
        # curl with same headers so match hits
        route["_headers"] = {
            k: v.get("exact", "") for k, v in match["headers"].items()
        }
    return route


def _baseline_destination_rule(ns, idx):
    # type: (str, int) -> Dict[str, Any]
    """Restore to the DR created by deploy_services (no outlier / mild pool)."""
    svc = rte_svc_name(idx)
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "DestinationRule",
        "metadata": {"name": svc, "namespace": ns},
        "spec": {
            "host": svc,
            "subsets": [
                {"name": "v1", "labels": {"version": "v1"}},
                {"name": "v2", "labels": {"version": "v2"}},
            ],
            "trafficPolicy": {
                "connectionPool": {
                    "http": {
                        "http1MaxPendingRequests": 100,
                        "maxRequestsPerConnection": 10,
                    }
                }
            },
        },
    }


def _dr_for_unit(unit, ns):
    # type: (Dict[str, Any], str) -> Optional[Dict[str, Any]]
    """
    DestinationRule overlay for CB / pool / outlier.
    IMPORTANT: reuse the service's primary DR name (same host, one DR only).
    Creating a second DR for the same host caused N=30 coverage drops.
    """
    effect = unit["effect_id"]
    if effect not in (
        "scope_dr_global",
        "trigger_load_pool",
        "trigger_outlier_window",
        "trigger_cb_eject",
    ):
        return None
    idx = int(unit["service_index"])
    svc = rte_svc_name(idx)
    tp = {
        "connectionPool": {
            "tcp": {"maxConnections": 50},
            "http": {"http1MaxPendingRequests": 20, "maxRequestsPerConnection": 2},
        }
    }
    if effect in ("trigger_outlier_window", "trigger_cb_eject", "scope_dr_global"):
        tp["outlierDetection"] = {
            "consecutive5xxErrors": 5,
            "interval": "10s",
            "baseEjectionTime": "30s",
            "maxEjectionPercent": 50,
        }
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "DestinationRule",
        "metadata": {"name": svc, "namespace": ns},  # in-place update
        "spec": {
            "host": svc,
            "subsets": [
                {"name": "v1", "labels": {"version": "v1"}},
                {"name": "v2", "labels": {"version": "v2"}},
            ],
            "trafficPolicy": tp,
        },
    }


def build_case_manifests(case, ns):
    # type: (Dict[str, Any], str) -> Tuple[str, List[str], List[Dict[str, Any]], List[Dict[str, Any]]]
    """
    Returns (yaml_text, delete_refs, traffic_targets, restore_docs).
    restore_docs: baseline DRs to re-apply after delete (for in-place DR updates).
    """
    members = case.get("members") or []
    http_routes = []
    docs = []
    delete_refs = []  # type: List[str]
    targets = []
    restore_docs = []  # type: List[Dict[str, Any]]
    touched_svc = set()  # type: set

    vs_name = "ortho-vs-{0}".format(_safe_name(case.get("case_id", "case")))
    for u in members:
        rt = _http_route_for_unit(u, ns)
        expect = rt.pop("_expect_status")
        path = rt.pop("_path")
        headers = rt.pop("_headers")
        http_routes.append(rt)
        targets.append(
            {
                "unit_id": u["unit_id"],
                "path": path,
                "headers": headers,
                "expect_status": expect,
                "repeat": effect_requests(u.get("strategy") or "routing"),
            }
        )
        dr = _dr_for_unit(u, ns)
        if dr is not None:
            docs.append(dr)
            idx = int(u["service_index"])
            svc = rte_svc_name(idx)
            if svc not in touched_svc:
                touched_svc.add(svc)
                restore_docs.append(_baseline_destination_rule(ns, idx))
            # do NOT delete primary DR — restore baseline instead

    vs = {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "VirtualService",
        "metadata": {"name": vs_name, "namespace": ns},
        "spec": {
            "hosts": ["*"],
            "gateways": ["meshscope-gw"],
            "http": http_routes,
        },
    }
    docs.insert(0, vs)
    delete_refs.insert(0, "virtualservice/{0}".format(vs_name))

    yaml_text = "---\n".join(
        yaml.safe_dump(d, default_flow_style=False, allow_unicode=True) for d in docs
    )
    return yaml_text, delete_refs, targets, restore_docs


def _wait_config(settle_s=0.6):
    # type: (float) -> None
    time.sleep(settle_s)


def validate_case_cluster(case, ns, base_url, settle_s=0.6):
    # type: (Dict[str, Any], str, str, float) -> Dict[str, Any]
    """One complete real validation: apply → traffic → assert → delete/restore."""
    t0 = time.time()
    yaml_text, delete_refs, targets, restore_docs = build_case_manifests(case, ns)
    apply_t0 = time.time()
    kubectl(["apply", "-f", "-"], stdin=yaml_text, timeout=180)
    apply_s = time.time() - apply_t0
    _wait_config(settle_s)

    statuses = []
    unit_ok = {}  # type: Dict[str, bool]
    traffic_t0 = time.time()
    for tgt in targets:
        uid = tgt["unit_id"]
        expect = int(tgt["expect_status"])
        passed = True
        # Adaptive retries for large-scale config propagate races
        attempts = 3
        for _ in range(int(tgt["repeat"])):
            ok_this = False
            for attempt in range(attempts):
                code, lat, _ = curl_once(
                    base_url, tgt["path"], tgt.get("headers") or {}
                )
                statuses.append(code)
                if code == expect:
                    ok_this = True
                    break
                time.sleep(0.35 * (attempt + 1))
            if not ok_this:
                passed = False
        unit_ok[uid] = passed
    traffic_s = time.time() - traffic_t0

    clear_t0 = time.time()
    for ref in delete_refs:
        kubectl_delete_ignore(["-n", ns, "delete", ref, "--ignore-not-found=true"])
    if restore_docs:
        restore_yaml = "---\n".join(
            yaml.safe_dump(d, default_flow_style=False, allow_unicode=True)
            for d in restore_docs
        )
        try:
            kubectl(["apply", "-f", "-"], stdin=restore_yaml, timeout=120)
        except Exception:
            pass
    clear_s = time.time() - clear_t0

    total = time.time() - t0
    passed_units = [uid for uid, ok in unit_ok.items() if ok]
    # Case-level ok: all members passed (kept for suite success_rate)
    traffic_ok = bool(unit_ok) and all(unit_ok.values())
    return {
        "case_id": case.get("case_id"),
        "ok": bool(traffic_ok),
        "wall_s": round(total, 4),
        "apply_s": round(apply_s, 4),
        "traffic_s": round(traffic_s, 4),
        "clear_s": round(clear_s, 4),
        "statuses": statuses[:40],
        "unit_ok": unit_ok,
        "detected_units": passed_units,
        # Coverage observes = units that actually passed HTTP checks (not all-or-nothing)
        "observes": passed_units,
        "planned_observes": list(case.get("observes") or []),
    }


def validate_suite_cluster(cases, ns, base_url, settle_s=0.6, progress_every=10):
    # type: (List[Dict[str, Any]], str, str, float, int) -> Dict[str, Any]
    """Sequential complete validation of a suite; wall-clock timed."""
    t0 = time.time()
    results = []
    detected = set()
    for i, c in enumerate(cases):
        r = validate_case_cluster(c, ns, base_url, settle_s=settle_s)
        results.append(r)
        detected.update(r.get("detected_units") or r.get("observes") or [])
        if progress_every and (i + 1) % progress_every == 0:
            print(
                "    [{0}/{1}] elapsed={2:.1f}s last_ok={3} passed_units={4}/{5}".format(
                    i + 1,
                    len(cases),
                    time.time() - t0,
                    r.get("ok"),
                    len(r.get("detected_units") or []),
                    len(r.get("planned_observes") or r.get("observes") or []),
                )
            )
            sys.stdout.flush()
    wall = time.time() - t0
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "total_validation_s": round(wall, 3),
        "num_cases": len(cases),
        "num_ok": ok_n,
        "success_rate_pct": round(100.0 * ok_n / float(max(len(cases), 1)), 2),
        "detected_units": sorted(detected),
        "unit_coverage_pct": None,  # filled by caller with fault set size
        "results": results,
    }


def ensure_cluster_namespace(ns, n_services, skip_deploy=False):
    # type: (str, int, bool) -> None
    if skip_deploy:
        return
    # if terminating, wait
    proc = subprocess.run(
        ["kubectl", "get", "ns", ns, "-o", "jsonpath={.status.phase}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if proc.returncode == 0 and (proc.stdout or "").strip() == "Terminating":
        wait_namespace_gone(ns, timeout_sec=600)
    deploy(ns, n_services)
    wait_ready(ns, n_services, timeout_sec=900)


def cleanup_namespace(ns, wait=False):
    # type: (str, bool) -> None
    kubectl_delete_ignore(["delete", "ns", ns, "--wait=false"])
    if wait:
        try:
            wait_namespace_gone(ns, timeout_sec=600)
        except Exception:
            pass
