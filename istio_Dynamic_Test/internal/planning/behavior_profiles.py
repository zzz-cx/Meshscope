"""Explicit controlled-backend contracts for statistical/stateful obligations.

Profiles supply stimuli, never expected policy values. Expectations are compiled
from the immutable reference model. These rules do not apply to arbitrary apps:
the adapter must supply correlated attempt receipts and isolated Envoy counters.
"""
from __future__ import annotations

import copy
import math
import re
from collections import Counter

from istio_config_parser.models.relational_model import destination_rule_context, digest, service_ref
from .relational import (assertion_accepts_request, assertion_for_policy,
                         plan_obligations, rewrite_expected, select_rule)

CONTRACT = "configpilot.controlled-http-backend/1"
PARAMETERIZED_CONTRACT = "configpilot.controlled-http-backend/2"
RULE = "controlled-whole-route-context/1"
PARAMETERIZED_RULE = "parameterized-controlled-context/2"


def seconds(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s)", str(value))
    if not match:
        raise ValueError("explicit ms/s duration required")
    return float(match[1]) / (1000 if match[2] == "ms" else 1)


def _context(model, rule, profile):
    """Closed vocabulary over the whole model; unknown third policies block reuse."""
    if profile.get("backend_contract") not in {CONTRACT, PARAMETERIZED_CONTRACT}:
        raise ValueError("controlled backend contract required")
    kind, raw = profile["kind"], rule["raw"]
    if kind not in ("split", "retry-budget", "pool"):
        raise ValueError("unknown behavior profile")
    allowed = {"routing", "request_headers", "response_headers", "rewrite"}
    if kind == "retry-budget":
        allowed |= {"retry", "timeout"}
    elif kind == "pool":
        allowed.add("retry")
    for p in model["policies"]:
        if p["rule_id"] == rule["id"] and (p["kind"] not in allowed or
                (p["kind"] in {"request_headers", "response_headers", "rewrite"} and p["semantics"] != "supported")):
            return None
        if p['rule_id'] == rule['id'] and p['kind'] == 'request_headers':
            reserved = {'x-audit-request', 'x-audit-failures', 'x-audit-delay', 'x-test-mode'}
            operations = p['parameters']
            if reserved & {k.lower() for k in list(operations.get('set', {})) + list(operations.get('remove', []))}:
                return None
    if model["diagnostics"] or any(r["kind"] == "EnvoyFilter" for r in model["resources"]):
        return None
    destinations = raw.get("route") or []
    if not destinations or any(set(d)-{"destination", "weight"} or
            set(d.get("destination", {}))-{"host", "port"} for d in destinations):
        return None
    expected = {service_ref(d["destination"]["host"], rule["namespace"]): d.get("weight", 100)
                for d in destinations}
    if len(expected) != len(destinations) or sum(expected.values()) != 100 or any(v <= 0 for v in expected.values()):
        return None
    drs, unknown_scope = destination_rule_context(model, rule)
    if unknown_scope:
        return None
    result = {"destinations": expected, "kind": kind}
    if profile['backend_contract'] == PARAMETERIZED_CONTRACT:
        result['backend_contract'] = PARAMETERIZED_CONTRACT
    if kind != "pool" and drs:
        return None  # No guessed DR inheritance, retry or outlier state.
    if kind == "split":
        if len(expected) < 2 or not 200 <= profile.get("samples", 0) <= 10000:
            return None
    else:
        if len(expected) != 1:
            return None
        retry = raw.get("retries", {})
        if set(retry)-{"attempts", "perTryTimeout", "retryOn"}:
            return None
        if kind == "retry-budget":
            attempts = retry.get('attempts')
            if not isinstance(attempts, int) or retry.get("retryOn") != "5xx":
                return None
            try:
                per_try, total = seconds(retry.get("perTryTimeout")), seconds(raw.get("timeout"))
            except ValueError:
                return None  # Defaults/other duration forms need their own semantics.
            # This version proves two distinct stimuli; it does not guess all
            # timeout/retry combinations or eliminate either activation phase.
            if profile['backend_contract'] == CONTRACT and (attempts, per_try, total) != (2, .25, .5):
                return None
            if profile['backend_contract'] == PARAMETERIZED_CONTRACT and not (
                    1 <= attempts <= 3 and .25 <= per_try <= .60 and abs(total-2*per_try) < .00001):
                return None
            result.update(attempts=attempts, per_try=per_try, total=total)
        else:
            if retry != {"attempts": 0} or len(drs) != 1:
                return None
            dr = drs[0]
            spec = dr["spec"]
            cp = spec.get("trafficPolicy", {}).get("connectionPool", {})
            if (set(spec)-{"host", "trafficPolicy"} or
                    set(spec.get("trafficPolicy", {})) != {"connectionPool"} or
                    set(cp) != {"tcp", "http"} or set(cp["tcp"]) != {"maxConnections"} or
                    set(cp["http"]) != {"http1MaxPendingRequests"} or
                    service_ref(spec.get("host", ""), dr["namespace"]) not in expected):
                return None
            connections, pending = cp["tcp"]["maxConnections"], cp["http"]["http1MaxPendingRequests"]
            if connections != 1 or pending != 1:
                return None  # Calibrated small-pool contract, not a general threshold proof.
            result.update(dr_id=dr["id"], connections=connections, pending=pending)
    return result


def plan_profiles(model, profiles, *, reuse=True, namespace=None, resource_ids=None, dependency_cache=None):
    base = plan_obligations(model, reuse=False, namespace=namespace, resource_ids=resource_ids,
                            dependency_cache=dependency_cache)
    rules = {r["id"]: r for r in model["rules"]}
    policies = {p["id"]: p for p in model["policies"]}
    relations = {r["id"]: r for r in model["relations"]}
    contexts = {}
    for profile in profiles:
        matches = [r for r in rules.values() if r["id"] == profile.get("rule_id") or
                   (profile.get("rule_name") and r["name"] == profile["rule_name"])]
        if len(matches) != 1 or matches[0]["id"] in contexts:
            raise ValueError("profile must resolve to exactly one distinct rule")
        context = _context(model, matches[0], profile)
        if context:
            contexts[matches[0]["id"]] = (context, profile)
    candidates, decisions = [], []
    for o in base["obligations"]:
        node, rel = policies.get(o["source"]), relations.get(o["source"])
        owner = rules.get(o["rule_id"])
        if rel and rel["type"] == "shared_time_budget":
            owner = rules[policies[rel["participants"][0]]["rule_id"]]
        if node and node["kind"] == "traffic_policy":
            owners = [rules[rid] for rid, (ctx, _) in contexts.items() if ctx.get("dr_id") == node["resource_id"]]
            owner = owners[0] if len(owners) == 1 else None
        if not owner or owner["id"] not in contexts:
            # Mixed generic/profile planning is deliberately unsupported here.
            o["unplanned_reason"] = "no closed controlled profile for complete policy context"
            continue
        ctx, profile = contexts[owner["id"]]
        contract = profile['backend_contract']
        assertion = assertion_for_policy(node, owner) if node else None
        phase, count, concurrency = "normal", 1, 1
        if node and node["kind"] == "routing":
            if ctx["kind"] == "split":
                assertion = {"kind": "distribution", "expected": ctx["destinations"],
                             "tolerance": .12, "min_samples": profile["samples"]}
                phase, count, concurrency = "distribution", profile["samples"], 4
        elif node and node["kind"] == "retry":
            if ctx["kind"] == "retry-budget":
                assertion = {"kind": "retry_recovery", "expected_attempts": ctx["attempts"] + 1}
                phase = "recover"
            else:
                assertion, phase = {"kind": "no_retry", "expected_attempts": 1}, "fail-once"
        elif node and node["kind"] == "timeout" and ctx["kind"] == "retry-budget":
            assertion, phase = {"kind": "total_timeout", "seconds": ctx["total"]}, "slow"
        elif rel and rel["type"] == "shared_time_budget" and ctx["kind"] == "retry-budget":
            assertion, phase = {"kind": "shared_budget", "seconds": ctx["total"], "per_try": ctx["per_try"]}, "slow"
        elif node and node["kind"] == "traffic_policy" and ctx["kind"] == "pool":
            assertion, phase, count, concurrency = {"kind": "pool_overflow", "expected": ctx}, "burst", 16, 16
        if not assertion:
            o["unplanned_reason"] = "unsupported assertion in controlled profile"
            continue
        # A simple observation may be reusable on a split batch, but its oracle
        # must accept every configured destination, not silently select one.
        assertion["allowed_destinations"] = sorted(ctx["destinations"])
        o.update(H=assertion, rule_id=owner["id"], unplanned_reason=None)
        o["G"].update(own_predicate=copy.deepcopy(owner["predicate"]), selection_group=owner["resource_id"],
                      expected_selected_rule=owner["id"], controlled_stimulus=phase,
                      exclude_preceding_rules=[r["id"] for r in rules.values() if r["resource_id"] == owner["resource_id"] and r["index"] < owner["index"]])
        simple_assertion = assertion["kind"] in {"destination", "request_header_set", "request_path_rewrite", "response_header_set"}
        o["K"].update(phase="any admitted non-burst phase" if simple_assertion else phase,
                      concurrency={"maximum": 4 if ctx["kind"] == "split" else 1} if simple_assertion else concurrency,
                      backend_contract=contract, requests="at least one" if simple_assertion else count)
        o["E"].update(quality="complete correlated controlled-backend attempts and client responses",
                      backend_contract=contract, minimum_samples=count)
        request = copy.deepcopy(profile["request"])
        request["headers"] = {**request.get("headers", {}), "x-test-mode": phase}
        stimulus = None
        if contract == PARAMETERIZED_CONTRACT:
            delay = ctx['per_try'] * (1.6 if phase == 'slow' else .10) if ctx['kind'] == 'retry-budget' else .5 if phase == 'burst' else .01
            failures = ctx['attempts'] if phase == 'recover' else 1 if phase == 'fail-once' else 0
            request['headers'].update({'x-audit-delay': str(delay), 'x-audit-failures': str(failures)})
            stimulus = {'delay_seconds': delay, 'failures_before_success': failures, 'derived_from_reference': model['model_hash']}
        for p in policies.values():
            if p["rule_id"] == owner["id"] and p["kind"] == "request_headers":
                for name in p["parameters"].get("remove", []):
                    request["headers"].setdefault(name.lower(), "configpilot-remove-witness")
        selected, _ = select_rule(model, request, owner["resource_id"])
        if not selected or selected["id"] != owner["id"] or not assertion_accepts_request(assertion, request):
            o["unplanned_reason"] = "profile request has no confirmed activation witness"
            continue
        probe = {"origin": o["id"], "request": request, "selected_rule": owner["id"],
                 "reference_model_hash": model["model_hash"], "phase": phase,
                 "context": ctx, "backend_contract": contract,
                 "load": {"requests": count, "concurrency": concurrency}, "cost": 1,
                 "slice": o["slice"], "footprint": {"config_reads": o["slice"]["nodes"],
                     "config_writes": [], "state_domains": ["controlled:"+owner["resource_id"]],
                     "capacity": {"requests": count, "concurrency": concurrency}}}
        if stimulus:
            probe['stimulus'] = stimulus
            if ctx['kind'] == 'pool':
                probe['footprint']['state_domains'].append('connection-pool:'+ctx['dr_id'])
        probe["probe_hash"] = digest(probe)
        probe["id"] = "probe:" + probe["probe_hash"][:24]
        candidates.append(probe)
    simple = {"destination", "request_header_set", "request_path_rewrite", "response_header_set"}
    for p in candidates:
        for o in base["obligations"]:
            own, same = p["origin"] == o["id"], p["selected_rule"] == o["rule_id"]
            # Whole-context admission above, followed by stimulus-specific
            # coverage. No inference of joint safety from pairwise labels.
            compatible = same and (o["H"]["kind"] in simple and p["phase"] != "burst" or
                                  o["K"]["phase"] == p["phase"])
            covered = not o["unplanned_reason"] and (own or reuse and compatible)
            decisions.append({"probe_id": p["id"], "obligation_id": o["id"], "W": int(covered),
                              "decision": "eligible" if covered else "unknown" if o["unplanned_reason"] else "ineligible",
                              "reason": (PARAMETERIZED_RULE if p['backend_contract'] == PARAMETERIZED_CONTRACT else RULE) if covered else o["unplanned_reason"] or "different activation phase or effective rule",
                              "probe_hash": p["probe_hash"], "reference_model_hash": model["model_hash"]})
    cover = {p["id"]: {d["obligation_id"] for d in decisions if d["probe_id"] == p["id"] and d["W"]} for p in candidates}
    remaining = set().union(*cover.values()) if cover else set()
    selected = []
    while remaining:
        best = max(candidates, key=lambda p: len(cover[p["id"]] & remaining))
        selected.append(best["id"])
        remaining -= cover[best["id"]]
    base.update(reuse_enabled=reuse, profile_plan=True, profiles=copy.deepcopy(profiles),
                candidate_probes=candidates, selected_probe_ids=selected, coverage_decisions=decisions,
                compatibility={"collection": "controlled correlated backend plus isolated cluster counters",
                               "probe_reuse": (PARAMETERIZED_RULE if any(p.get('backend_contract') == PARAMETERIZED_CONTRACT for p in candidates) else RULE) if reuse else "disabled", "concurrency": "serial probes; explicit per-probe load"})
    if any(p.get('backend_contract') == PARAMETERIZED_CONTRACT for p in candidates):
        base['compatibility']['concurrency'] = 'external run-level configuration, state, capacity and evidence admission required'
    base["summary"] = {"obligations": len(base["obligations"]), "candidate_probes": len(candidates),
                       "selected_probes": len(selected), "unplanned_obligations": sum(bool(o["unplanned_reason"]) for o in base["obligations"]),
                       "planned_http_requests": sum(p["load"]["requests"] for p in candidates if p["id"] in selected)}
    base.pop("plan_hash", None)
    base["plan_hash"] = digest(base)
    return base


def _quality(plan, evidence, probe, execution, seen_requests, seen_events):
    if (execution.get('configuration_stable', True) is not True or
            execution.get("run_id") != evidence["run_id"] or not execution.get("execution_id") or
            execution.get("reference_model_hash") != plan["reference_model_hash"] or
            execution.get("probe_hash") != probe["probe_hash"] or
            execution.get("backend_contract") != probe['backend_contract'] or execution.get("sent_request") != probe["request"]):
        return False
    samples = execution.get("samples", [])
    if len(samples) != probe["load"]["requests"] or execution.get("attempt_capture_complete") is not True:
        return False
    for s in samples:
        rid = s.get("request_id")
        if (not rid or seen_requests[rid] != 1 or s.get("activation_confirmed") is not True or
                not isinstance(s.get("status"), int) or s.get("transport_error")):
            return False
        try:
            if not execution["started_at"] <= s["started_at"] <= s["completed_at"] <= execution["completed_at"]:
                return False
            for r in s.get("backend_receipts", []):
                if (r.get("source_kind") != "backend_receipt" or r.get("request_id") != rid or
                        not r.get("event_id") or seen_events[r["event_id"]] != 1 or
                        not s["started_at"] <= r["observed_at"] <= s["completed_at"] or
                        not r.get("backend_identity")):
                    return False
                if probe['backend_contract'] == PARAMETERIZED_CONTRACT and (r.get('backend_contract') != PARAMETERIZED_CONTRACT or
                        r.get('planned_delay') != probe['stimulus']['delay_seconds']):
                    return False
        except (KeyError, TypeError):
            return False
    return True


def _assert(assertion, probe, execution):
    samples = execution["samples"]
    receipts = [r for s in samples for r in s.get("backend_receipts", [])]
    kind = assertion["kind"]
    if kind == "distribution":
        if len(samples) < assertion["min_samples"] or any(len(s.get("backend_receipts", [])) != 1 for s in samples):
            return None, "distribution requires one observed destination per sample"
        counts = Counter(r["backend_identity"] for r in receipts)
        passed = not (set(counts)-set(assertion["expected"])) and all(
            abs(counts[k]/len(samples)-weight/100) <= assertion["tolerance"] for k, weight in assertion["expected"].items())
        return passed, {"counts": dict(counts), "samples": len(samples), "absolute_tolerance": assertion["tolerance"]}
    if kind in {"retry_recovery", "no_retry", "total_timeout", "shared_budget"}:
        if len(samples) != 1 or not receipts:
            return None, "attempt evidence required"
        s = samples[0]
        elapsed = s["completed_at"]-s["started_at"]
        allowed = set(assertion["allowed_destinations"])
        correct_target = all(r["backend_identity"] in allowed for r in receipts)
        if kind in {"retry_recovery", "no_retry"}:
            codes = [r.get("produced_status") for r in sorted(receipts, key=lambda r: r["observed_at"])]
            if None in codes:
                return None, "backend completion evidence required"
            expected_codes = [503] * (assertion['expected_attempts']-1) + [200] if kind == "retry_recovery" else [503]
            passed = correct_target and len(receipts) == assertion["expected_attempts"] and codes == expected_codes and s["status"] == expected_codes[-1]
        else:
            budget = assertion["seconds"]
            passed = correct_target and s["status"] == 504 and .80*budget <= elapsed <= budget+.20
            if kind == "shared_budget":
                passed &= len(receipts) >= 2 and all(r.get("planned_delay", 0) > assertion["per_try"] for r in receipts)
        return bool(passed), {"status": s["status"], "attempts": len(receipts), "elapsed": elapsed}
    if kind == "pool_overflow":
        counter = execution.get("cluster_counter", {})
        flags = [s.get("response_headers", {}).get("x-audit-response-flags") for s in samples]
        flags_complete = all(s.get("response_headers_complete") is True for s in samples) and all(isinstance(f, str) and f for f in flags)
        counter_complete = (counter.get("source") == "isolated-envoy-cluster" and counter.get("complete") is True and
                            counter.get("backend_identity") in assertion["allowed_destinations"])
        if not flags_complete and not counter_complete:
            return None, "Envoy response flags or isolated overflow counter required"
        if not receipts or max(s["started_at"] for s in samples) >= min(r.get("finished_at", math.inf) for r in receipts):
            return None, "burst trigger not established before upstream completion"
        delta = counter["after"]-counter["before"] if counter_complete else None
        overflow_flags = sum('UO' in f.split(',') for f in flags) if flags_complete else 0
        statuses = Counter(s["status"] for s in samples)
        # This contract proves overflow under saturation, not exact fairness or
        # every boundary value of connection/pending thresholds.
        passed = (overflow_flags > 0 or delta is not None and delta > 0) and statuses[503] > 0 and statuses[200] > 0 and all(
            r["backend_identity"] in assertion["allowed_destinations"] for r in receipts)
        return passed, {"overflow_delta": delta, "overflow_response_flags": overflow_flags,
                        "statuses": {str(status): count for status, count in statuses.items()}, "backend_attempts": len(receipts)}
    if not receipts:
        return None, "no backend activation evidence"
    if any(r["backend_identity"] not in assertion["allowed_destinations"] for r in receipts):
        if kind == "destination":
            return False, "unexpected destination"
        return None, "observation outside reference destination context"
    if kind == "destination":
        return all(r["backend_identity"] == assertion["expected"] for r in receipts), "observed destination"
    if kind == "request_path_rewrite":
        if any(r.get("path") is None for r in receipts):
            return None, "missing rewritten path"
        return all(r["path"] == rewrite_expected(assertion, probe["request"]) for r in receipts), "backend rewritten path"
    if kind in {"request_header_set", "response_header_set"}:
        entries = samples if kind == "response_header_set" else receipts
        key, complete = ("response_headers", "response_headers_complete") if kind == "response_header_set" else ("request_headers", "headers_complete")
        if any(e.get(complete) is not True or not isinstance(e.get(key), dict) for e in entries):
            return None, "incomplete header evidence"
        return all(all(e[key].get(k) == v for k, v in assertion["expected"].items()) and
                   all(k not in e[key] for k in assertion.get("absent", [])) for e in entries), "correlated header observations"
    return None, "unsupported assertion"


def evaluate_profiles(plan, evidence):
    probes = {p["id"]: p for p in plan["candidate_probes"]}
    observations = evidence.get("observations", [])
    requests = Counter(s.get("request_id") for e in observations for s in e.get("samples", []))
    events = Counter(r.get("event_id") for e in observations for s in e.get("samples", []) for r in s.get("backend_receipts", []))
    results = []
    for o in plan["obligations"]:
        eligible = {d["probe_id"] for d in plan["coverage_decisions"] if d["obligation_id"] == o["id"] and d["W"]} & set(plan["selected_probe_ids"])
        outcomes, details, used = [], [], []
        for e in observations:
            pid = e.get("probe_id")
            if pid not in eligible:
                continue
            if not _quality(plan, evidence, probes[pid], e, requests, events):
                details.append("incomplete, stale, duplicate or uncorrelated execution evidence")
                continue
            passed, detail = _assert(o["H"], probes[pid], e)
            details.append(detail)
            if passed is not None:
                outcomes.append("PASS" if passed else "FAIL")
                used.append({"probe_id": pid, "execution_id": e["execution_id"],
                             "request_ids": [s["request_id"] for s in e["samples"]]})
        verdict = "FAIL" if "FAIL" in outcomes else "PASS" if "PASS" in outcomes else "INCONCLUSIVE"
        results.append({"obligation_id": o["id"], "verdict": verdict, "evaluated": verdict != "INCONCLUSIVE",
                        "reason": o["unplanned_reason"] or details or "no evidence", "evidence": used})
    return {"schema": "configpilot.obligation-results/1", "reference_model_hash": plan["reference_model_hash"],
            "plan_hash": plan["plan_hash"], "results": results,
            "summary": {v: sum(r["verdict"] == v for r in results) for v in ("PASS", "FAIL", "INCONCLUSIVE")}}
