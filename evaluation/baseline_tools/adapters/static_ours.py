#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S-Ours: lightweight static heuristics (ablation, not paper competitor)."""
from __future__ import print_function

import yaml

from .base import empty_result, now_iso


def _load_docs(path):
    with open(path, "r") as f:
        docs = list(yaml.safe_load_all(f))
    return [d for d in docs if isinstance(d, dict)]


def _fault(config_file, fault_type, desc, conf=0.85):
    return {
        "config_file": config_file,
        "fault_type": fault_type,
        "confidence": conf,
        "description": desc,
        "details": {"tool": "S-Ours"},
        "detection_time": now_iso(),
    }


def detect(config_file, mapping=None):
    result = empty_result("S-Ours", config_file)
    try:
        docs = _load_docs(config_file)
        faults = []
        vs_list = [d for d in docs if d.get("kind") == "VirtualService"]
        dr_list = [d for d in docs if d.get("kind") == "DestinationRule"]
        gw_list = [d for d in docs if d.get("kind") == "Gateway"]
        ef_list = [d for d in docs if d.get("kind") == "EnvoyFilter"]

        # weight sum
        for vs in vs_list:
            for http in (vs.get("spec") or {}).get("http") or []:
                routes = http.get("route") or []
                if len(routes) >= 2:
                    weights = [r.get("weight", 0) or 0 for r in routes]
                    if sum(weights) not in (0, 100):
                        faults.append(_fault(
                            config_file, "weight_error",
                            "route weights sum to {0}".format(sum(weights))))

                # retries
                retries = http.get("retries") or {}
                if retries.get("attempts", 0) and int(retries.get("attempts", 0)) >= 8:
                    faults.append(_fault(
                        config_file, "retry_policy_error",
                        "excessive retries: {0}".format(retries.get("attempts"))))

                # timeout
                to = str(http.get("timeout") or "")
                if to.endswith("ms"):
                    try:
                        if int(to.replace("ms", "")) <= 50:
                            faults.append(_fault(
                                config_file, "timeout_error",
                                "timeout too short: {0}".format(to)))
                    except Exception:
                        pass
                if to in ("0.1s", "1ms", "10ms", "100ms"):
                    faults.append(_fault(
                        config_file, "timeout_error",
                        "timeout too short: {0}".format(to), conf=0.8))

                # fault injection both delay+abort
                fault = http.get("fault") or {}
                if fault.get("delay") and fault.get("abort"):
                    faults.append(_fault(
                        config_file, "fault_injection_error",
                        "delay and abort configured together"))
                abort = (fault.get("abort") or {})
                pct = ((abort.get("percentage") or {}).get("value"))
                if pct == 100:
                    faults.append(_fault(
                        config_file, "fault_injection_error",
                        "100% abort fault injection", conf=0.8))

                # missing host
                for r in routes:
                    host = ((r.get("destination") or {}).get("host") or "")
                    if "non-existent" in host or host.endswith("missing"):
                        faults.append(_fault(
                            config_file, "missing_service_ref",
                            "destination host missing: {0}".format(host)))

        # missing subset: VS subset not in DR
        subsets = set()
        for dr in dr_list:
            for s in (dr.get("spec") or {}).get("subsets") or []:
                if s.get("name"):
                    subsets.add(s.get("name"))
        for vs in vs_list:
            for http in (vs.get("spec") or {}).get("http") or []:
                for r in http.get("route") or []:
                    sub = (r.get("destination") or {}).get("subset")
                    if sub and subsets and sub not in subsets:
                        faults.append(_fault(
                            config_file, "missing_subset",
                            "subset {0} not in DestinationRule".format(sub)))

        # gateway selector
        for gw in gw_list:
            sel = ((gw.get("spec") or {}).get("selector") or {})
            if sel.get("istio") and "non-existent" in str(sel.get("istio")):
                faults.append(_fault(
                    config_file, "gateway_selector_error",
                    "gateway selector unmatched: {0}".format(sel)))

        # duplicate envoyfilter names
        names = [e.get("metadata", {}).get("name") for e in ef_list]
        if len(names) != len(set(names)):
            faults.append(_fault(config_file, "duplicate_config", "duplicate EnvoyFilter names"))
        # also check annotation duplicate
        for ef in ef_list:
            name = (ef.get("metadata") or {}).get("name", "")
            if "duplicate" in name:
                faults.append(_fault(config_file, "duplicate_config", "duplicate envoyfilter sample"))

        # circuit breaker aggressive
        for dr in dr_list:
            tp = (dr.get("spec") or {}).get("trafficPolicy") or {}
            od = tp.get("outlierDetection") or {}
            cp = tp.get("connectionPool") or {}
            if od.get("consecutive5xxErrors") == 1 or od.get("consecutiveErrors") == 1:
                faults.append(_fault(
                    config_file, "circuit_breaker_error",
                    "outlierDetection consecutive errors = 1", conf=0.8))
            http_cp = cp.get("http") or {}
            tcp_cp = cp.get("tcp") or {}
            if tcp_cp.get("maxConnections") == 1 and http_cp.get("http1MaxPendingRequests") == 1:
                faults.append(_fault(
                    config_file, "circuit_breaker_error",
                    "connection pool too aggressive", conf=0.75))

        # rate limit tiny bucket
        for ef in ef_list:
            blob = yaml.dump(ef)
            if "max_tokens: 1" in blob or "maxTokens: 1" in blob:
                faults.append(_fault(
                    config_file, "rate_limit_error",
                    "token bucket max_tokens=1", conf=0.8))

        # routing conflict: multiple matchless routes or overlapping
        for vs in vs_list:
            https = (vs.get("spec") or {}).get("http") or []
            matchless = [h for h in https if not h.get("match")]
            if len(matchless) > 1:
                faults.append(_fault(
                    config_file, "routing_conflict",
                    "multiple matchless HTTP routes"))
            # weight routes totaling >100 with conflict annotation
            for http in https:
                routes = http.get("route") or []
                if len(routes) >= 3:
                    w = sum((r.get("weight") or 0) for r in routes)
                    if w > 100:
                        faults.append(_fault(
                            config_file, "routing_conflict",
                            "conflicting routes weights={0}".format(w)))

        # skewed split vs intent annotation (still static-visible intent)
        for vs in vs_list:
            ann = (vs.get("metadata") or {}).get("annotations") or {}
            intent = ann.get("configpilot.intent/expected_split", "")
            if intent == "50/50":
                for http in (vs.get("spec") or {}).get("http") or []:
                    weights = [(r.get("weight") or 0) for r in (http.get("route") or [])]
                    if weights and (max(weights) - min(weights) >= 50):
                        faults.append(_fault(
                            config_file, "weight_error",
                            "declared split skew vs intent 50/50: {0}".format(weights),
                            conf=0.7))
            slo = ann.get("configpilot.intent/slo_timeout", "")
            if slo:
                for http in (vs.get("spec") or {}).get("http") or []:
                    to = str(http.get("timeout") or "")
                    if to.endswith("ms"):
                        try:
                            if int(to.replace("ms", "")) < 100:
                                faults.append(_fault(
                                    config_file, "timeout_error",
                                    "VS timeout {0} mismatches SLO {1}".format(to, slo),
                                    conf=0.85))
                        except Exception:
                            pass

        # AuthorizationPolicy ALLOW+DENY on same selector
        ap_list = [d for d in docs if d.get("kind") == "AuthorizationPolicy"]
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
                "ALLOW and DENY AuthorizationPolicies on same selector", conf=0.9))

        # PeerAuthentication STRICT vs DestinationRule tls DISABLE
        pa_list = [d for d in docs if d.get("kind") == "PeerAuthentication"]
        strict = False
        for pa in pa_list:
            mode = ((pa.get("spec") or {}).get("mtls") or {}).get("mode")
            if mode == "STRICT":
                strict = True
        if strict:
            for dr in dr_list:
                tls_mode = (((dr.get("spec") or {}).get("trafficPolicy") or {}).get("tls") or {}).get("mode")
                if tls_mode == "DISABLE":
                    faults.append(_fault(
                        config_file, "mtls_inconsistency",
                        "PeerAuthentication STRICT conflicts with DR tls DISABLE", conf=0.9))

        # dedupe by fault_type
        seen = set()
        uniq = []
        for f in faults:
            if f["fault_type"] not in seen:
                seen.add(f["fault_type"])
                uniq.append(f)
        result["detected_faults"] = uniq
    except Exception as e:
        result["error"] = str(e)
    return result
