"""Versioned, source-preserving policy relations, exported by the parser.

This is a reference model, not a proof that the data plane implements it.
Unknown directives are retained; resource graph edges are not treated as
evidence of non-interference. The first executable semantics are HTTP route
selection and request-header set. Other relations are useful context but do
not authorize probe substitution.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

SCHEMA = "configpilot.relations/1"
SEMANTICS = "http-obligation-semantics/2"
SUPPORTED_SEMANTICS = {SEMANTICS, "http-selection-header-set/1"}
SPECIAL_HEADERS = {"host", "connection", "content-length", "transfer-encoding", "upgrade", "te", "trailer"}
SEMANTIC_RULES = {
    "precedes": {"meaning": "first matching HTTP rule within one VirtualService selection group", "executable": True},
    "attached_to": {"meaning": "directive is activated in its owner rule context", "executable": True},
    "references": {"meaning": "source depends on named resource identity; resolution is not runtime proof", "executable": False},
    "shared_time_budget": {"meaning": "retry attempts and per-try limits share the route total budget", "executable": False},
    "may_short_circuit": {"meaning": "fault handling may prevent downstream policy activation; requires conditional semantics", "executable": False},
    "inherits_overrides": {"meaning": "subset and parent policies require field-level inheritance resolution", "executable": False},
}


def supported_headers(parameters, *, response=False):
    if not isinstance(parameters, dict) or set(parameters)-({"set"} if response else {"set", "remove"}):
        return False
    values, removed = parameters.get("set") or {}, parameters.get("remove") or []
    if not isinstance(values, dict) or not isinstance(removed, list) or not (values or removed):
        return False
    names = list(values)+removed
    forbidden = SPECIAL_HEADERS | ({"server", "date"} if response else set())
    return (all(isinstance(k, str) and k.lower() not in forbidden and not k.startswith(":") for k in names)
            and not ({k.lower() for k in values} & {k.lower() for k in removed})
            and not any("%" in str(v) for v in values.values()))


def supported_rewrite(parameters):
    return (isinstance(parameters, dict) and set(parameters) == {"uri"}
            and isinstance(parameters["uri"], str) and parameters["uri"].startswith("/")
            and not any(c in parameters["uri"] for c in ("?", "#", "%")))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def documents(block):
    if isinstance(block, list):
        return [d for item in block for d in documents(item)]
    if not isinstance(block, dict):
        return []
    if isinstance(block.get("items"), list):
        return documents(block["items"])
    if "spec" in block or ("kind" in block and "metadata" in block):
        return [block]
    return [d for value in block.values() for d in documents(value)]


def resource_id(kind, namespace, name):
    return "%s/%s/%s" % (kind, namespace, name)


def service_ref(host, namespace):
    """Resolve Kubernetes service names without truncating external domains."""
    parts = str(host).rstrip(".").split(".")
    if len(parts) == 1:
        return resource_id("Service", namespace, parts[0])
    if len(parts) == 2:
        return resource_id("Service", parts[1], parts[0])
    if len(parts) in (3, 5) and parts[2] == "svc" and (len(parts) == 3 or parts[3:] == ["cluster", "local"]):
        return resource_id("Service", parts[1], parts[0])
    return "ExternalHost/" + str(host).rstrip(".")


def destination_rule_context(model, rule):
    """Resolve exact DR host scope; retain uncertainty for richer scope rules.

    This only proves that a distinct exact host does not configure the target
    cluster. It does not interpret inheritance, selection among competing DRs,
    EnvoyFilter patches, workload selectors or wildcard/export scope.
    """
    if any(r['kind'] == 'EnvoyFilter' for r in model['resources']):
        return [], 'EnvoyFilter scope is not interpreted'
    targets = {service_ref(d.get('destination', {}).get('host', ''), rule['namespace'])
               for d in rule['raw'].get('route') or []}
    relevant = []
    for r in model['resources']:
        if r['kind'] != 'DestinationRule':
            continue
        spec = r['spec']
        host = spec.get('host')
        if (not isinstance(host, str) or not host or '*' in host or
                set(spec)-{'host', 'trafficPolicy', 'subsets'}):
            return [], 'DestinationRule scope requires additional semantics'
        if service_ref(host, r['namespace']) in targets:
            relevant.append(r)
    return relevant, None


def build_relational_model(configs):
    resources, rules, policies, relations, diagnostics = [], [], [], [], []
    kinds = {"virtual_services": "VirtualService", "destination_rules": "DestinationRule",
             "services": "Service", "gateways": "Gateway", "envoy_filters": "EnvoyFilter"}
    by_id = {}
    for key, kind in kinds.items():
        for doc in documents(configs.get(key)):
            meta = doc.get("metadata") or {}
            ns, name = meta.get("namespace", "default"), meta.get("name")
            if not name:
                diagnostics.append({"code": "missing_resource_identity", "kind": kind})
                continue
            rid = resource_id(kind, ns, name)
            if rid in by_id:
                raise ValueError("duplicate resource identity: " + rid)
            item = {"id": rid, "kind": kind, "namespace": ns, "name": name,
                    "spec": copy.deepcopy(doc.get("spec") or {}),
                    "source_version": meta.get("resourceVersion"), "source_uid": meta.get("uid")}
            resources.append(item)
            by_id[rid] = item

    def relate(kind, participants, **condition):
        item = {"type": kind, "participants": participants, "condition": condition,
                "semantics_version": SEMANTICS}
        item["id"] = "relation:" + digest(item)[:24]
        relations.append(item)

    def policy(owner, kind, parameters, pointer, executable=False):
        pid = owner["id"] + "/" + kind
        item = {"id": pid, "kind": kind, "rule_id": owner.get("rule_id", owner["id"]),
                "resource_id": owner["resource_id"], "parameters": copy.deepcopy(parameters),
                "source_pointer": pointer, "semantics": "supported" if executable else "unknown"}
        item['paoc'] = {'predicate': copy.deepcopy(owner.get('predicate') or [{}]),
            'action': {'type': kind},
            'scope': {'resource': owner['resource_id'], 'rule': owner.get('id'),
                      'namespace': by_id[owner['resource_id']]['namespace'],
                      'hosts': copy.deepcopy(owner.get('hosts')), 'gateways': copy.deepcopy(owner.get('gateways'))},
            'constraint': copy.deepcopy(parameters)}
        item["four_dimensions"] = {
            "if": copy.deepcopy(owner.get("predicate")),
            "what": {"type": kind, "parameters": copy.deepcopy(parameters)},
            "when": {"trigger": {"routing": "request_selection", "request_headers": "forwarded_request",
                "retry": "retryable_upstream_failure", "timeout": "total_request_budget"}.get(kind, "unresolved"),
                "owner_rule": owner.get("id")},
            "where": {"resource": owner["resource_id"], "rule": owner.get("id"),
                      "hosts": copy.deepcopy(owner.get("hosts")), "gateways": copy.deepcopy(owner.get("gateways"))}}
        policies.append(item)
        if owner.get("is_rule"):
            relate("attached_to", [pid, owner["id"]])
        return item

    for resource in resources:
        rid, ns, spec = resource["id"], resource["namespace"], resource["spec"]
        if resource["kind"] == "VirtualService":
            group = []
            for index, raw in enumerate(spec.get("http") or []):
                rule_id = rid + "#/spec/http/%d" % index
                rule = {"id": rule_id, "resource_id": rid, "is_rule": True,
                        "index": index, "name": raw.get("name"),
                        "hosts": copy.deepcopy(spec.get("hosts") or []),
                        "gateways": [g if g == "mesh" or "/" in g else ns+"/"+g for g in (spec.get("gateways") or ["mesh"])],
                        "predicate": copy.deepcopy(raw.get("match") or [{}]),
                        "namespace": ns, "raw": copy.deepcopy(raw)}
                rules.append(rule)
                if set(spec)-{"hosts", "gateways", "http", "tcp", "tls"}:
                    diagnostics.append({"code": "unsupported_virtualservice_scope", "rule_id": rule_id,
                                        "fields": sorted(set(spec)-{"hosts", "gateways", "http", "tcp", "tls"})})
                group.append(rule)
                route = policy(rule, "routing", raw.get("route"), rule_id+"/route", "route" in raw)
                for destination in raw.get("route") or []:
                    target = destination.get("destination") or {}
                    ref = service_ref(target.get("host", ""), ns)
                    relate("references", [route["id"], ref], subset=target.get("subset"), port=target.get("port"))
                    if ref not in by_id:
                        diagnostics.append({"code": "unresolved_target", "policy_id": route["id"], "target": ref})
                children = {}
                mapping = {"retries": "retry", "timeout": "timeout", "fault": "fault_injection",
                           "rewrite": "rewrite", "redirect": "redirect", "directResponse": "direct_response",
                           "mirror": "mirror", "mirrors": "mirrors", "corsPolicy": "cors"}
                for key, kind in mapping.items():
                    if key in raw:
                        children[kind] = policy(rule, kind, raw[key], rule_id+"/"+key,
                                                kind == "rewrite" and supported_rewrite(raw[key]))
                headers = raw.get("headers") or {}
                for side in ("request", "response"):
                    if side in headers:
                        parameters = headers[side]
                        supported = supported_headers(parameters, response=side == "response")
                        children[side+"_headers"] = policy(rule, side+"_headers", parameters,
                            rule_id+"/headers/"+side, supported)
                for index_dest, destination in enumerate(raw.get("route") or []):
                    if set(destination)-{"destination", "weight"}:
                        policy(rule, "opaque:destination_options:%d" % index_dest, destination,
                               rule_id+"/route/%d" % index_dest)
                if "retry" in children and "timeout" in children:
                    relate("shared_time_budget", [children["retry"]["id"], children["timeout"]["id"]],
                           owner_rule=rule_id)
                if "fault_injection" in children:
                    for kind in ("retry", "timeout"):
                        if kind in children:
                            relate("may_short_circuit", [children["fault_injection"]["id"], children[kind]["id"]],
                                   owner_rule=rule_id)
                known = {"name", "match", "route", "headers"} | set(mapping)
                for key in sorted(set(raw)-known):
                    policy(rule, "opaque:"+key, raw[key], rule_id+"/"+key)
            for later in group:
                for earlier in group[:later["index"]]:
                    relate("precedes", [earlier["id"], later["id"]], selection_group=rid)
            for key in ("tcp", "tls"):
                if spec.get(key):
                    policy({"id": rid, "resource_id": rid}, "opaque:"+key, spec[key], rid+"#/spec/"+key)
        elif resource["kind"] == "DestinationRule":
            parent = None
            if spec.get("trafficPolicy"):
                parent = policy({"id": rid, "resource_id": rid}, "traffic_policy",
                                spec["trafficPolicy"], rid+"#/spec/trafficPolicy")
            for index, subset in enumerate(spec.get("subsets") or []):
                if subset.get("trafficPolicy"):
                    child = policy({"id": rid+"/subset/"+str(index), "resource_id": rid}, "traffic_policy",
                                   subset["trafficPolicy"], rid+"#/spec/subsets/%d/trafficPolicy" % index)
                    if parent:
                        relate("inherits_overrides", [child["id"], parent["id"]],
                               subset=subset.get("name"), requires_field_level_resolution=True)
        elif resource["kind"] == "EnvoyFilter":
            policy({"id": rid, "resource_id": rid}, "opaque:envoy_filter", spec, rid+"#/spec")

    # Resource links carry identity and unresolved state, not executable semantics.
    for rule in rules:
        ns = rule["namespace"]
        for gateway in rule["gateways"]:
            if gateway == "mesh":
                continue
            parts = gateway.split("/", 1)
            ref = resource_id("Gateway", parts[0] if len(parts) == 2 else ns, parts[-1])
            relate("references", [rule["id"], ref])
            if ref not in by_id:
                diagnostics.append({"code": "unresolved_gateway", "rule_id": rule["id"], "target": ref})
    for policy_node in policies:
        if policy_node["kind"] != "routing":
            continue
        owner = by_id[policy_node["resource_id"]]
        for destination in policy_node["parameters"] or []:
            dest = destination.get("destination") or {}
            target = service_ref(dest.get("host", ""), owner["namespace"])
            for resource in resources:
                if resource["kind"] == "DestinationRule" and service_ref(resource["spec"].get("host", ""), resource["namespace"]) == target:
                    relate("references", [policy_node["id"], resource["id"]], subset=dest.get("subset"))

    model = {"schema": SCHEMA, "semantics_version": SEMANTICS, "semantic_rules": copy.deepcopy(SEMANTIC_RULES), "plane": "control_reference",
             "resources": sorted(resources, key=lambda r: r["id"]), "rules": rules,
             "policies": policies, "relations": relations, "diagnostics": diagnostics,
             "limitations": ["generic semantics cover HTTP selection, ordinary header set/remove, and literal URI rewrite",
                             "statistical/stateful policies require explicit controlled execution profiles",
                             "cross-VirtualService ordering, inheritance resolution and shared state are not proven",
                             "control reference is not evidence of data-plane activation"]}
    model["model_hash"] = digest(model)
    return model


def validate_model(model):
    if model.get("schema") != SCHEMA or model.get("semantics_version") not in SUPPORTED_SEMANTICS:
        raise ValueError("unsupported relational model schema or semantics")
    unsigned = {k: v for k, v in model.items() if k != "model_hash"}
    if model.get("model_hash") != digest(unsigned):
        raise ValueError("relational model hash mismatch")


def dependency_slice(model, policy_id):
    """Directional closure: preceding siblings enter; unrelated readers do not."""
    source_relation = next((r for r in model["relations"] if r["id"] == policy_id), None)
    selected = set(source_relation["participants"]) if source_relation else {policy_id}
    edge_ids = {policy_id} if source_relation else set()
    changed = True
    while changed:
        changed = False
        for relation in model["relations"]:
            members, kind = relation["participants"], relation["type"]
            hit = ((kind == "attached_to" and bool(selected.intersection(members)))
                   or (kind in ("references", "inherits_overrides") and members[0] in selected)
                   or (kind == "precedes" and members[1] in selected)
                   or (kind in ("shared_time_budget", "may_short_circuit") and bool(selected.intersection(members))))
            if hit:
                edge_ids.add(relation["id"])
                new = set(members)-selected
                if new:
                    selected.update(new)
                    changed = True
    return {"nodes": sorted(selected), "relations": sorted(edge_ids)}
