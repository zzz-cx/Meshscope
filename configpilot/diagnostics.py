"""Join configuration, policy, obligation and evidence identities for diagnosis."""
from collections import deque


def build_diagnostics(model, plan, results, evidence=None):
    nodes, edges, adjacency = {}, [], {}
    def node(identity, kind, **attributes):
        nodes.setdefault(identity, {'id': identity, 'kind': kind, **attributes})
    def edge(source, target, kind, **attributes):
        edges.append({'source': source, 'target': target, 'type': kind, **attributes})
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    for resource in model['resources']:
        node(resource['id'], 'resource', resource_kind=resource['kind'], namespace=resource['namespace'], name=resource['name'])
    for rule in model['rules']:
        node(rule['id'], 'rule', name=rule.get('name'), index=rule['index'])
        edge(rule['id'], rule['resource_id'], 'owned_by')
    for policy in model['policies']:
        node(policy['id'], 'policy', policy_kind=policy['kind'], source_pointer=policy['source_pointer'])
        owner = policy['rule_id'] if policy['rule_id'] in nodes else policy['resource_id']
        edge(policy['id'], owner, 'owned_by')
    for relation in model['relations']:
        node(relation['id'], 'relation', relation_type=relation['type'], condition=relation['condition'])
        for position, identity in enumerate(relation['participants']):
            if identity not in nodes:
                node(identity, 'unresolved_reference')
            edge(identity, relation['id'], 'participates_in', position=position)
    judgments = {r['obligation_id']: r for r in results['results']}
    for obligation in plan['obligations']:
        node(obligation['id'], 'obligation', verdict=judgments[obligation['id']]['verdict'])
        if obligation['source'] in nodes:
            edge(obligation['id'], obligation['source'], 'verifies')
    for probe in plan['candidate_probes']:
        if probe['id'] in plan['selected_probe_ids']:
            node(probe['id'], 'probe', selected=True)
    for decision in plan['coverage_decisions']:
        if decision['W'] and decision['probe_id'] in nodes:
            edge(decision['probe_id'], decision['obligation_id'], 'planned_support')
    for observation in (evidence or {}).get('observations', []):
        if observation['probe_id'] not in nodes:
            continue
        for sample in observation.get('samples', [observation]):
            for receipt in sample.get('backend_receipts', []):
                if not receipt.get('event_id'):
                    continue
                identity = 'evidence:'+receipt['event_id']
                node(identity, 'evidence', request_id=receipt.get('request_id'),
                     observed_backend=receipt.get('backend_identity'))
                edge(identity, observation['probe_id'], 'observed_for')
    failures, pending = [], []
    by_policy = {p['id']: p for p in model['policies']}
    by_rule = {r['id']: r for r in model['rules']}
    for obligation in plan['obligations']:
        result = judgments[obligation['id']]
        if result['verdict'] == 'PASS':
            continue
        source = obligation['source']
        distance, todo = {source: 0}, deque([source])
        scope = set(obligation.get('slice', {}).get('nodes', [])) | {source}
        for identity in list(scope):
            if identity in by_policy:
                scope.add(by_policy[identity]['resource_id'])
                scope.add(by_policy[identity]['rule_id'])
            if identity in by_rule:
                scope.add(by_rule[identity]['resource_id'])
        allowed = scope | set(obligation.get('slice', {}).get('relations', []))
        while todo:
            current = todo.popleft()
            for following in adjacency.get(current, []):
                if following in allowed and following not in distance:
                    distance[following] = distance[current]+1
                    todo.append(following)
        candidates = [{'resource_id': identity, 'distance': distance.get(identity),
                       'basis': 'declared dependency; candidate, not proven root cause'}
                      for identity in scope if identity in nodes and nodes[identity]['kind'] == 'resource']
        candidates.sort(key=lambda item: (item['distance'] is None, item['distance'] or 0, item['resource_id']))
        item = {'obligation_id': obligation['id'], 'source': source, 'verdict': result['verdict'],
                'reason': result['reason'], 'candidate_resources': candidates,
                'potential_services': sorted(identity for identity in scope if identity.startswith('Service/')),
                'evidence': result['evidence']}
        (failures if result['verdict'] == 'FAIL' else pending).append(item)
    graph = {'schema': 'configpilot.evidence-dependency-graph/1', 'reference_model_hash': model['model_hash'],
             'plan_hash': plan['plan_hash'], 'nodes': list(nodes.values()), 'edges': edges,
             'relations': model['relations'], 'service_edges_are_observed_calls': False}
    diagnostics = {'schema': 'configpilot.diagnostics/1', 'reference_model_hash': model['model_hash'],
                   'failures': failures, 'inconclusive': pending,
                   'ranking': 'dependency distance heuristic; not a causal root-cause guarantee'}
    return graph, diagnostics
