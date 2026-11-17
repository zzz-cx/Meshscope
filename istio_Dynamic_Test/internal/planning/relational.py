"""Conservative serial planning over the parser's relational reference model.

No YAML parsing and no mutation of declared intent. A finite witness search
may establish reachability, but failure to find a witness is UNKNOWN, never a
proof of unreachability. Unsupported policies remain explicit obligations.
"""
from __future__ import annotations

import copy

from istio_config_parser.models.relational_model import (
    dependency_slice, destination_rule_context, digest, validate_model,
)

PLAN_SCHEMA = "configpilot.obligation-plan/1"
EVIDENCE_SCHEMA = "configpilot.obligation-evidence/1"
REUSE_RULE = "same-effective-rule-observations/2"


from istio_config_parser.models.http_semantics import (
    string_match, clause_matches, rule_matches, select_rule, witness_requests, _constrained_request,
    single_destination, _overlap_status, rewrite_expected, assertion_for_policy,
    assertion_accepts_request,
)


def plan_obligations(model, *, reuse=True, namespace=None, profiles=None, resource_ids=None, dependency_cache=None):
    validate_model(model)
    selected_resources = None if resource_ids is None else set(resource_ids)
    if isinstance(resource_ids, str) or selected_resources is not None and selected_resources - {r['id'] for r in model['resources']}:
        raise ValueError('resource_ids must identify resources in the complete reference model')
    if profiles:
        from .behavior_profiles import plan_profiles
        return plan_profiles(model, profiles, reuse=reuse, namespace=namespace, resource_ids=resource_ids,
                             dependency_cache=dependency_cache)
    if dependency_cache is not None and dependency_cache.get('reference_model_hash') != model['model_hash']:
        raise ValueError('dependency cache reference model mismatch')

    def dependency(source):
        if dependency_cache is None:
            return dependency_slice(model, source)
        if source not in dependency_cache['slices']:
            raise ValueError('dependency cache missing source: '+source)
        return copy.deepcopy(dependency_cache['slices'][source])
    rules = {r["id"]: r for r in model["rules"]}
    policies = {p["id"]: p for p in model["policies"]}
    resource_namespaces = {r["id"]: r["namespace"] for r in model["resources"]}
    obligations, candidates, decisions = [], [], []
    required_fields = ["execution_id", "request_id", "probe_hash", "reference_model_hash", "activation_confirmed"]
    unresolved = {d.get("policy_id") or d.get("rule_id") for d in model["diagnostics"]}

    def add_obligation(oid, source, assertion, owner=None, reason=None):
        item = {"id": oid, "source": source, "rule_id": owner["id"] if owner else None,
                "G": {"own_predicate": copy.deepcopy(owner["predicate"]) if owner else None,
                      "selection_group": owner["resource_id"] if owner else None,
                      "expected_selected_rule": owner["id"] if owner else None,
                      "exclude_preceding_rules": [r["id"] for r in rules.values() if owner and
                          r["resource_id"] == owner["resource_id"] and r["index"] < owner["index"]],
                      "activation_is_tested_behavior": True},
                "H": assertion, "E": {"required": required_fields, "backend_receipt_required": True,
                      "quality": "complete request-correlated backend observation"},
                "K": {"reference_model_hash": model["model_hash"], "phase": "request",
                      "concurrency": 1, "configuration_mutations": []},
                "unplanned_reason": reason}
        obligations.append(item)
        return item

    def add_candidate(obligation, request, selected):
        sid = dependency(obligation["source"])
        reads = {n.split("#", 1)[0] for n in sid["nodes"] if n.startswith(("VirtualService/", "Service/", "DestinationRule/", "Gateway/"))}
        reads.add(selected["resource_id"])
        probe = {"origin": obligation["id"], "request": request, "selected_rule": selected["id"],
                 "reference_model_hash": model["model_hash"], "phase": "request", "cost": 1,
                 "slice": sid, "footprint": {"config_reads": sorted(reads), "config_writes": [],
                     "state_domains": ["unisolated:"+selected["resource_id"]], "capacity": {"requests": 1, "concurrency": 1}}}
        probe["probe_hash"] = digest(probe)
        probe["id"] = "probe:"+probe["probe_hash"][:24]
        candidates.append(probe)

    for node in policies.values():
        if namespace and resource_namespaces.get(node["resource_id"]) != namespace:
            continue
        if selected_resources is not None and node['resource_id'] not in selected_resources:
            continue
        owner = rules.get(node["rule_id"])
        compiled = assertion_for_policy(node, owner)
        assertion = compiled or {"kind": node["kind"], "expected": copy.deepcopy(node["parameters"])}
        reason = None
        if not compiled:
            reason = "no trustworthy generic trigger/evidence adapter for " + node["kind"]
        elif compiled["kind"] != "destination" and not compiled.get("expected_backend"):
            reason = "observation has no unambiguous destination context"
        if not reason:
            siblings = [p for p in policies.values() if p["rule_id"] == owner["id"]]
            if any(p["semantics"] != "supported" for p in siblings):
                reason = "co-applying policy semantics are incomplete; preserve independent obligation"
            if any(p["id"] in unresolved for p in siblings) or owner["id"] in unresolved:
                reason = "unresolved reference in activation context"
            drs, unknown_scope = destination_rule_context(model, owner)
            if drs or unknown_scope:
                reason = "shared policy scope requires additional semantics"
        obligation = add_obligation("obligation:"+node["id"], node["id"], assertion, owner, reason)
        obligation["slice"] = dependency(node["id"])
        if reason:
            continue
        found = False
        for request in witness_requests(model, owner):
            request = copy.deepcopy(request)
            if assertion["kind"] == "request_header_set":
                for name in assertion.get("absent", []):
                    request["headers"].setdefault(name, "configpilot-remove-witness")
            selected, why = select_rule(model, request, owner["resource_id"])
            if selected and selected["id"] == owner["id"] and assertion_accepts_request(assertion, request):
                add_candidate(obligation, request, selected)
                found = True
                break
        if not found:
            obligation["unplanned_reason"] = "no confirmed activation witness; may be shadowed, ambiguous or unsupported"

    for relation in model["relations"]:
        kind, members = relation["type"], relation["participants"]
        if kind not in ("precedes", "shared_time_budget", "may_short_circuit", "inherits_overrides"):
            continue
        owner_resource = rules[members[0]]["resource_id"] if members[0] in rules else policies[members[0]]["resource_id"]
        if namespace and resource_namespaces.get(owner_resource) != namespace:
            continue
        if selected_resources is not None and owner_resource not in selected_resources:
            continue
        if kind == "precedes":
            first, later = (rules[m] for m in members)
            if _overlap_status(first, later) == "disjoint":
                continue  # Proven non-overlap has no dynamic selection interaction.
            obligation = add_obligation("obligation:"+relation["id"], relation["id"],
                {"kind": "ordered_selection", "expected": single_destination(first), "participants": members}, first,
                "no overlap witness or distinct observable destination")
            obligation["slice"] = {"nodes": members, "relations": [relation["id"]]}
            for request in witness_requests(model, later):
                if rule_matches(first, request) is not True:
                    continue
                selected, why = select_rule(model, request, first["resource_id"])
                supported_context = all(p["semantics"] == "supported" for p in policies.values() if p["rule_id"] in members)
                resolved_context = all(p["id"] not in unresolved for p in policies.values() if p["rule_id"] in members) and all(m not in unresolved for m in members)
                no_shared_unknown = all(not drs and not reason for drs, reason in
                                        (destination_rule_context(model, r) for r in (first, later)))
                if selected and selected["id"] == first["id"] and single_destination(first) and single_destination(later) and single_destination(first) != single_destination(later) and supported_context and resolved_context and no_shared_unknown:
                    obligation["unplanned_reason"] = None
                    add_candidate(obligation, request, selected)
                    break
        else:
            obligation = add_obligation("obligation:"+relation["id"], relation["id"],
                {"kind": kind, "participants": members}, reason="relation retained; controlled trigger and evidence not implemented")
            slices = [dependency(m) for m in members]
            obligation["slice"] = {"nodes": sorted({n for s in slices for n in s["nodes"]}),
                                    "relations": sorted({n for s in slices for n in s["relations"]})}

    def safe_reuse(probe):
        siblings = [p for p in policies.values() if p["rule_id"] == probe["selected_rule"]]
        if any(p["semantics"] != "supported" for p in siblings):
            return False
        if any(p["id"] in unresolved for p in siblings) or probe["selected_rule"] in unresolved:
            return False
        drs, unknown_scope = destination_rule_context(model, rules[probe['selected_rule']])
        if drs or unknown_scope:
            return False
        return True

    for probe in candidates:
        reuse_safe = reuse and safe_reuse(probe)
        for obligation in obligations:
            own = probe["origin"] == obligation["id"]
            same = probe["selected_rule"] == obligation["rule_id"]
            covered = False
            if obligation["unplanned_reason"]:
                state, why = "unknown", obligation["unplanned_reason"]
            elif own:
                state, why, covered = "eligible", "independent baseline witness", True
            elif not reuse_safe:
                state, why = "unknown", "no applicable whole-context reuse rule"
            elif same and obligation["H"]["kind"] in ("destination", "request_header_set", "response_header_set", "request_path_rewrite", "ordered_selection"):
                participants = obligation["H"].get("participants")
                relation_hit = ((not participants or all(rule_matches(rules[m], probe["request"]) is True for m in participants))
                                and assertion_accepts_request(obligation["H"], probe["request"]))
                if relation_hit:
                    state, why, covered = "eligible", REUSE_RULE, True
                else:
                    state, why = "ineligible", "request does not exercise this selection relation"
            else:
                state, why = "ineligible", "different effective rule or assertion capability"
            decisions.append({"probe_id": probe["id"], "obligation_id": obligation["id"],
                              "decision": state, "reason": why, "W": int(covered),
                              "reference_model_hash": model["model_hash"], "probe_hash": probe["probe_hash"]})
    cover = {p['id']: set() for p in candidates}
    for decision in decisions:
        if decision['W']:
            cover[decision['probe_id']].add(decision['obligation_id'])
    remaining = set().union(*cover.values()) if cover else set()
    selected = []
    candidate_order = {p['id']: index for index, p in enumerate(candidates)}
    while remaining:
        best = max(candidates, key=lambda p: (len(cover[p["id"]] & remaining)/p["cost"], -candidate_order[p['id']]))
        selected.append(best["id"])
        remaining -= cover[best["id"]]
    plan = {"schema": PLAN_SCHEMA, "reference_model_hash": model["model_hash"], "semantics_version": model["semantics_version"], "target_namespace": namespace,
            "reuse_enabled": reuse, "obligations": obligations, "candidate_probes": candidates,
            "selected_probe_ids": selected, "coverage_decisions": decisions,
            "compatibility": {"collection": "not inferred; evidence adapter must prove correlation",
                              "probe_reuse": REUSE_RULE if reuse else "disabled", "concurrency": "serial only"},
            "summary": {"obligations": len(obligations), "candidate_probes": len(candidates),
                        "selected_probes": len(selected), "unplanned_obligations": sum(bool(o["unplanned_reason"]) for o in obligations)}}
    if selected_resources is not None:
        plan['target_resource_ids'] = sorted(selected_resources)
    plan["plan_hash"] = digest(plan)
    return plan


def evaluate_obligations(plan, evidence):
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("reference_model_hash") != plan["reference_model_hash"] or not evidence.get("run_id"):
        raise ValueError("evidence schema or reference model mismatch")
    if plan.get("plan_hash") != digest({k: v for k, v in plan.items() if k != "plan_hash"}):
        raise ValueError("plan hash mismatch")
    if plan.get("profile_plan"):
        from .behavior_profiles import evaluate_profiles
        return evaluate_profiles(plan, evidence)
    by_probe = {p["id"]: p for p in plan["candidate_probes"]}
    observations = {}
    identities = {}
    event_owners = {}
    for item in evidence.get("observations", []):
        observations.setdefault(item.get("probe_id"), []).append(item)
        identity = (item.get("probe_id"), item.get("execution_id"), item.get("request_id"))
        identities.setdefault(item.get("request_id"), set()).add(identity)
        for receipt in item.get("backend_receipts") or []:
            event_owners.setdefault(receipt.get("event_id"), set()).add(identity)
    results = []
    selected_ids = set(plan['selected_probe_ids'])
    covered_by = {}
    for decision in plan['coverage_decisions']:
        if decision['W'] and decision['probe_id'] in selected_ids:
            covered_by.setdefault(decision['obligation_id'], set()).add(decision['probe_id'])
    for obligation in plan["obligations"]:
        eligible = covered_by.get(obligation['id'], set())
        outcomes, used, reasons = [], [], []
        for pid in sorted(eligible):
            for observation in observations.get(pid, []):
                probe = by_probe[pid]
                valid = (observation.get("probe_hash") == probe["probe_hash"]
                         and observation.get("reference_model_hash") == plan["reference_model_hash"]
                         and observation.get("activation_confirmed") is True
                         and observation.get("attempt_capture_complete", True) is True
                         and observation.get('configuration_stable', True) is True
                         and observation.get("run_id") == evidence["run_id"]
                         and len(identities.get(observation.get("request_id"), ())) == 1
                         and observation.get("sent_request") == probe["request"]
                         and bool(observation.get("request_id")) and bool(observation.get("execution_id")))
                receipts = observation.get("backend_receipts")
                if not valid or not isinstance(receipts, list) or len(receipts) != 1:
                    reasons.append("missing/stale/ambiguous execution or backend evidence")
                    continue
                receipt = receipts[0]
                if receipt.get("request_id") != observation["request_id"] or receipt.get("source_kind") != "backend_receipt" or not receipt.get("event_id") or len(event_owners.get(receipt.get("event_id"), ())) != 1:
                    reasons.append("backend evidence cannot be correlated")
                    continue
                try:
                    fresh = observation["started_at"] <= receipt["observed_at"] <= observation["completed_at"]
                except (KeyError, TypeError):
                    fresh = False
                if not fresh:
                    reasons.append("backend evidence has no fresh execution window")
                    continue
                assertion = obligation["H"]
                if assertion["kind"] in ("destination", "ordered_selection"):
                    if not receipt.get("backend_identity"):
                        reasons.append("missing actual destination")
                        continue
                    passed = receipt["backend_identity"] == assertion["expected"]
                elif assertion["kind"] in ("request_header_set", "request_path_rewrite", "response_header_set"):
                    if receipt.get("backend_identity") != assertion["expected_backend"]:
                        reasons.append("header evidence is outside the expected destination context")
                        continue
                    if assertion["kind"] == "request_path_rewrite":
                        expected_path = rewrite_expected(assertion, probe["request"])
                        if receipt.get("path") is None or expected_path is None:
                            reasons.append("missing or ambiguous rewritten path")
                            continue
                        passed = receipt["path"] == expected_path
                        outcomes.append("PASS" if passed else "FAIL")
                        used.append({"probe_id": pid, "event_id": receipt["event_id"], "request_id": observation["request_id"]})
                        continue
                    response_side = assertion["kind"] == "response_header_set"
                    headers = observation.get("response_headers") if response_side else receipt.get("request_headers")
                    complete = observation.get("response_headers_complete") if response_side else receipt.get("headers_complete")
                    if not isinstance(headers, dict) or complete is not True:
                        reasons.append("missing complete backend request headers")
                        continue
                    headers = {k.lower(): str(v) for k, v in headers.items()}
                    passed = all(headers.get(k) == v for k, v in assertion["expected"].items()) and all(k not in headers for k in assertion.get("absent", []))
                else:
                    reasons.append("unsupported assertion")
                    continue
                outcomes.append("PASS" if passed else "FAIL")
                used.append({"probe_id": pid, "event_id": receipt["event_id"], "request_id": observation["request_id"]})
        verdict = "FAIL" if "FAIL" in outcomes else "PASS" if "PASS" in outcomes else "INCONCLUSIVE"
        results.append({"obligation_id": obligation["id"], "verdict": verdict,
                        "evaluated": verdict != "INCONCLUSIVE", "evidence": used,
                        "reason": "assertion contradicted by correlated evidence" if verdict == "FAIL" else
                            "assertion supported by correlated evidence" if verdict == "PASS" else
                            obligation["unplanned_reason"] or "; ".join(sorted(set(reasons))) or "no complete evidence"})
    return {"schema": "configpilot.obligation-results/1", "reference_model_hash": plan["reference_model_hash"],
            "plan_hash": plan["plan_hash"], "results": results,
            "summary": {status: sum(r["verdict"] == status for r in results) for status in ("PASS", "FAIL", "INCONCLUSIVE")}}
