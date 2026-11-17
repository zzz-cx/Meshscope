"""Bidirectional finite-witness comparison of already projected relation models.

This does not parse raw Envoy dumps or claim whole-domain equivalence. Unknown
policies, scopes and missing witnesses are retained rather than guessed.
"""
import json

from .relational_model import validate_model, service_ref, destination_rule_context


def effective_behavior(model, request, *, gateway=None):
    from .http_semantics import select_rule, rewrite_expected
    if model['diagnostics']:
        return None, 'model has unresolved or unsupported scope diagnostics'
    resources = {r['resource_id'] for r in model['rules'] if gateway is None or gateway in r['gateways']}
    selected, unknown = [], []
    for resource in sorted(resources):
        rule, reason = select_rule(model, request, resource)
        if rule and (gateway is None or gateway in rule['gateways']):
            selected.append(rule)
        elif rule is None and reason != 'no rule selected':
            unknown.append(reason)
    if unknown or len(selected) > 1:
        return None, '; '.join(sorted(set(unknown))) or 'multiple selection groups need an explicit execution context'
    if not selected:
        return {'selected': False}, None
    rule = selected[0]
    allowed = {'routing', 'request_headers', 'response_headers', 'rewrite'}
    siblings = [p for p in model['policies'] if p['rule_id'] == rule['id']]
    if any(p['kind'] not in allowed or p['semantics'] != 'supported' for p in siblings):
        return None, 'selected rule has unsupported co-applying policy semantics'
    drs, reason = destination_rule_context(model, rule)
    if drs or reason:
        return None, 'selected rule depends on unresolved shared/DR semantics'
    destinations = {}
    services = {r['id']: r for r in model['resources'] if r['kind'] == 'Service'}
    for entry in rule['raw'].get('route') or []:
        destination = entry.get('destination') or {}
        if set(entry)-{'destination', 'weight'} or set(destination)-{'host', 'port'}:
            return None, 'unsupported destination scope or options'
        port = destination.get('port') or {}
        if set(port)-{'number'}:
            return None, 'unsupported port scope'
        target = service_ref(destination.get('host', ''), rule['namespace'])
        number = port.get('number')
        if number is None:
            ports = services.get(target, {}).get('spec', {}).get('ports', [])
            if len(ports) != 1 or not isinstance(ports[0].get('port'), int):
                return None, 'implicit destination port cannot be resolved'
            number = ports[0]['port']
        weight = entry.get('weight', 100)
        if not isinstance(number, int) or not isinstance(weight, int) or weight < 0:
            return None, 'unsupported destination port or weight'
        if weight:
            destinations[(target, number)] = destinations.get((target, number), 0)+weight
    if not destinations or sum(destinations.values()) != 100:
        return None, 'unsupported destination weights'
    headers = {k.lower(): str(v) for k, v in request.get('headers', {}).items()}
    response, path = {}, request['path']
    for policy in siblings:
        parameters = policy['parameters']
        if policy['kind'] == 'request_headers':
            headers.update({k.lower(): str(v) for k, v in (parameters.get('set') or {}).items()})
            for key in parameters.get('remove') or []:
                headers.pop(key.lower(), None)
        elif policy['kind'] == 'response_headers':
            response = {'set': {k.lower(): str(v) for k, v in (parameters.get('set') or {}).items()},
                        'remove': sorted(k.lower() for k in parameters.get('remove') or [])}
        elif policy['kind'] == 'rewrite':
            path = rewrite_expected({'matches': rule['predicate'], 'rewrite_uri': parameters['uri']}, request)
            if path is None:
                return None, 'ambiguous literal rewrite'
    return {'selected': True, 'destinations': sorted((host, port, weight) for (host, port), weight in destinations.items()),
            'path': path, 'request_headers': headers, 'response_headers': response}, None


def compare_models(expected, actual, *, gateway=None, limit=2048):
    from .http_semantics import witness_requests
    validate_model(expected)
    validate_model(actual)
    if not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError('witness limit must be in 1..10000')
    witnesses, gaps, truncated = {}, [], False
    for side, model in [('expected', expected), ('actual', actual)]:
        for rule in model['rules']:
            if gateway is not None and gateway not in rule['gateways']:
                continue
            found = False
            for request in witness_requests(model, rule):
                found = True
                key = json.dumps(request, sort_keys=True)
                if key not in witnesses and len(witnesses) >= limit:
                    truncated = True
                    break
                witnesses[key] = request
            if not found:
                gaps.append({'side': side, 'rule_id': rule['id'], 'reason': 'no supported finite witness'})
    rows = []
    for request in witnesses.values():
        before, first_reason = effective_behavior(expected, request, gateway=gateway)
        after, second_reason = effective_behavior(actual, request, gateway=gateway)
        verdict = 'UNKNOWN' if before is None or after is None else 'SAME' if before == after else 'DIFFERENT'
        rows.append({'request': request, 'verdict': verdict, 'expected': before, 'actual': after,
                     'unknown_reasons': [r for r in (first_reason, second_reason) if r]})
    counts = {name: sum(r['verdict'] == name for r in rows) for name in ['SAME', 'DIFFERENT', 'UNKNOWN']}
    status = ('DIFFERENT' if counts['DIFFERENT'] else 'INCONCLUSIVE' if counts['UNKNOWN'] or gaps or truncated or not rows
              else 'NO_DIFFERENCE_OBSERVED')
    return {'schema': 'configpilot.bounded-behavior-comparison/1', 'status': status,
        'expected_model_hash': expected['model_hash'], 'actual_model_hash': actual['model_hash'],
        'global_equivalence_proven': False, 'projection_required': 'both inputs must already be projected into relation models',
        'witness_generation': 'union of expected and actual rule witnesses', 'summary': counts,
        'witness_gaps': gaps, 'truncated': truncated, 'comparisons': rows}
