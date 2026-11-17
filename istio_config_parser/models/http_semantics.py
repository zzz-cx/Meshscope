"""Shared bounded HTTP semantics over parsed models; no YAML or traffic I/O."""
import fnmatch
import itertools
from urllib.parse import parse_qs, urlencode, urlsplit
from .relational_model import SPECIAL_HEADERS, service_ref, digest


def string_match(value, condition):
    if not isinstance(condition, dict) or len(condition) != 1:
        return None
    key, wanted = next(iter(condition.items()))
    if key == "exact":
        return value is not None and str(value) == str(wanted)
    if key == "prefix":
        return value is not None and str(value).startswith(str(wanted))
    return None


def clause_matches(clause, request):
    known = {"uri", "headers", "method", "authority", "queryParams", "name"}
    values = [None] if set(clause)-known else []
    parsed = urlsplit(request["path"])
    fields = {"uri": parsed.path or "/", "method": request.get("method", "GET"), "authority": request["host"]}
    for key, actual in fields.items():
        if key in clause:
            values.append(string_match(actual, clause[key]))
    headers = {k.lower(): v for k, v in request.get("headers", {}).items()}
    for key, condition in (clause.get("headers") or {}).items():
        values.append(None if key.lower() in SPECIAL_HEADERS or key.startswith(":") else string_match(headers.get(key.lower()), condition))
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, condition in (clause.get("queryParams") or {}).items():
        values.append(string_match((query.get(key) or [None])[0], condition))
    if False in values:
        return False
    return None if None in values else True


def rule_matches(rule, request):
    if not any(fnmatch.fnmatchcase(request["host"].lower(), h.lower()) for h in rule["hosts"]):
        return False
    results = [clause_matches(c, request) for c in rule["predicate"]]
    return True if True in results else None if None in results else False


def select_rule(model, request, resource):
    candidates = sorted((r for r in model["rules"] if r["resource_id"] == resource), key=lambda r: r["index"])
    for rule in candidates:
        hit = rule_matches(rule, request)
        if hit is None:
            return None, "unknown preceding or current predicate"
        if hit:
            # Cross-VS ordering is deliberately not guessed, even when a
            # concrete request happens to select one rule in each resource.
            for other in model["rules"]:
                if other["resource_id"] != resource and set(other["gateways"]) & set(rule["gateways"]):
                    if rule_matches(other, request) is not False:
                        return None, "another VirtualService may select this request"
            return rule, "first matching rule in selection group"
    return None, "no rule selected"


def _constrained_request(clauses, host):
    """Construct a candidate conjunction; callers still check full selection.

    A seed is only an input, never proof that a rule is selected. Unsupported
    conditions and incompatible exact/prefix intersections produce no seed.
    """
    def choose(conditions, default):
        candidates = [default] + [str(v) for condition in conditions for v in condition.values()]
        return next((value for value in candidates
                     if all(string_match(value, condition) is True for condition in conditions)), None)
    if any('authority' in c and string_match(host, c['authority']) is not True for c in clauses):
        return None
    path = choose([c['uri'] for c in clauses if 'uri' in c], '/')
    method = choose([c['method'] for c in clauses if 'method' in c], 'GET')
    if path is None or method is None:
        return None
    values = {}
    for field in ('headers', 'queryParams'):
        conditions = {}
        for clause in clauses:
            for name, condition in (clause.get(field) or {}).items():
                conditions.setdefault(name.lower() if field == 'headers' else name, []).append(condition)
        values[field] = {name: choose(items, 'configpilot-other') for name, items in conditions.items()}
        if any(value is None for value in values[field].values()):
            return None
    query = urlencode(sorted(values['queryParams'].items()))
    return {'host': host, 'path': path+('?' + query if query else ''), 'method': method,
            'headers': values['headers']}


def witness_requests(model, rule, limit=256):
    """Generate bounded witnesses, including values avoiding earlier rules."""
    peers = [r for r in model["rules"] if r["resource_id"] == rule["resource_id"]]
    hosts = [h for h in rule["hosts"] if "*" not in h]
    for clause in rule["predicate"]:
        # Start with the target's own requirements, then useful intersections.
        # Unrelated Header/query dimensions must not exhaust the entire finite
        # search before a valid target input is even considered.
        count, seen = 0, set()
        intersections = [[clause]] + [[clause, match] for peer in peers for match in peer['predicate']]
        for host, conjunction in itertools.product(hosts, intersections):
            if count >= limit:
                break
            request = _constrained_request(conjunction, host)
            if request is None:
                continue
            identity = digest(request)
            if identity in seen:
                continue
            seen.add(identity)
            count += 1
            if rule_matches(rule, request) is True:
                yield request
        paths = {"/"}
        uri = clause.get("uri") or {"prefix": "/"}
        if "exact" in uri:
            paths = {uri["exact"]}
        elif "prefix" in uri:
            prefix = uri["prefix"]
            paths = {prefix, prefix+"__configpilot__"}
            for peer in peers:
                for match in peer["predicate"]:
                    for value in (match.get("uri") or {}).values():
                        if isinstance(value, str) and value.startswith(prefix):
                            paths.add(value)
        else:
            continue
        dimensions, query_dimensions = {}, {}
        for peer in peers:
            for match in peer["predicate"]:
                for name, condition in (match.get("headers") or {}).items():
                    values = dimensions.setdefault(name.lower(), {None, "configpilot-other"})
                    for kind, value in condition.items():
                        if kind in ("exact", "prefix"):
                            values.add(str(value))
                for name, condition in (match.get("queryParams") or {}).items():
                    values = query_dimensions.setdefault(name, {None, "configpilot-other"})
                    values.update(str(v) for k, v in condition.items() if k in ("exact", "prefix"))
        keys = sorted(dimensions)
        query_keys = sorted(query_dimensions)
        method = clause.get("method") or {"exact": "GET"}
        methods = [method.get("exact") or method.get("prefix", "GET")]
        for host, path, verb in itertools.product(hosts, sorted(paths), methods):
            dimensions_values = [sorted(dimensions[k], key=lambda x: str(x)) for k in keys] + [sorted(query_dimensions[k], key=lambda x: str(x)) for k in query_keys]
            for combined in itertools.product(*dimensions_values):
                if count >= limit:
                    break
                count += 1
                values, query_values = combined[:len(keys)], combined[len(keys):]
                query = urlencode([(k, v) for k, v in zip(query_keys, query_values) if v is not None])
                request = {"host": host, "path": path+("?"+query if query else ""), "method": verb,
                           "headers": {k: v for k, v in zip(keys, values) if v is not None}}
                if rule_matches(rule, request) is True:
                    yield request
            if count >= limit:
                break


def single_destination(rule):
    destinations = rule["raw"].get("route") or []
    if len(destinations) != 1 or destinations[0].get("weight", 100) != 100:
        return None
    destination = destinations[0].get("destination") or {}
    if not destination.get("host") or destination.get("subset"):
        return None
    return service_ref(destination["host"], rule["namespace"])


def _overlap_status(first, second):
    """Prove basic disjointness; otherwise require an actual witness."""
    if not set(first["hosts"]) & set(second["hosts"]):
        return "unknown"
    all_disjoint = True
    for a, b in itertools.product(first["predicate"], second["predicate"]):
        disjoint = False
        fields_a = {"uri": a.get("uri", {"prefix": "/"}), **{"header:"+k.lower(): v for k, v in a.get("headers", {}).items()}}
        fields_b = {"uri": b.get("uri", {"prefix": "/"}), **{"header:"+k.lower(): v for k, v in b.get("headers", {}).items()}}
        for key in ("method", "authority"):
            if key in a:
                fields_a[key] = a[key]
            if key in b:
                fields_b[key] = b[key]
        fields_a.update({"query:"+k: v for k, v in a.get("queryParams", {}).items()})
        fields_b.update({"query:"+k: v for k, v in b.get("queryParams", {}).items()})
        for name in set(fields_a) & set(fields_b):
            ca, cb = fields_a[name], fields_b[name]
            if len(ca) != 1 or len(cb) != 1 or set(ca)-{"exact", "prefix"} or set(cb)-{"exact", "prefix"}:
                continue
            ka, va = next(iter(ca.items()))
            kb, vb = next(iter(cb.items()))
            if ka == kb == "exact":
                disjoint |= va != vb
            elif ka == kb == "prefix":
                disjoint |= not (va.startswith(vb) or vb.startswith(va))
            else:
                exact, prefix = (va, vb) if ka == "exact" else (vb, va)
                disjoint |= not exact.startswith(prefix)
        all_disjoint &= disjoint
    return "disjoint" if all_disjoint else "unknown"


def rewrite_expected(assertion, request):
    """Return an unambiguous literal rewrite; never guess an OR-match prefix."""
    parsed = urlsplit(request["path"])
    results = set()
    for clause in assertion["matches"]:
        if clause_matches(clause, request) is not True:
            continue
        uri = clause.get("uri") or {"prefix": "/"}
        if set(uri) == {"prefix"}:
            value = assertion["rewrite_uri"] + parsed.path[len(uri["prefix"]):]
        elif set(uri) == {"exact"}:
            value = assertion["rewrite_uri"]
        else:
            return None
        results.add(value+("?"+parsed.query if parsed.query else ""))
    return next(iter(results)) if len(results) == 1 else None


def assertion_for_policy(node, owner):
    """Shared assertion compiler, used by generic and controlled profiles."""
    expected_backend = single_destination(owner) if owner else None
    if node["kind"] == "routing" and expected_backend:
        return {"kind": "destination", "expected": expected_backend}
    if node["semantics"] != "supported" or not owner:
        return None
    if node["kind"] in ("request_headers", "response_headers"):
        parameters = node["parameters"]
        return {"kind": "response_header_set" if node["kind"] == "response_headers" else "request_header_set",
                "expected": {k.lower(): str(v) for k, v in (parameters.get("set") or {}).items()},
                "absent": [k.lower() for k in parameters.get("remove") or []], "expected_backend": expected_backend}
    if node["kind"] == "rewrite":
        return {"kind": "request_path_rewrite", "rewrite_uri": node["parameters"]["uri"],
                "matches": owner["predicate"], "expected_backend": expected_backend}
    return None


def assertion_accepts_request(assertion, request):
    if assertion["kind"] == "request_path_rewrite":
        return rewrite_expected(assertion, request) is not None
    if assertion["kind"] == "request_header_set":
        headers = {k.lower(): v for k, v in request.get("headers", {}).items()}
        return all(name in headers for name in assertion.get("absent", []))
    return True
