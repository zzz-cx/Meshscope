import copy
import json
import unittest

from istio_config_parser.models.relational_model import build_relational_model
from istio_Dynamic_Test.internal.planning.relational import EVIDENCE_SCHEMA, evaluate_obligations, plan_obligations, rewrite_expected
from istio_Dynamic_Test.internal.planning.behavior_profiles import CONTRACT
from istio_Dynamic_Test.tests.test_relational_planning import config, route, evidence_for


def fixture(kind):
    r = route('/shop/', 'orders', {'x-source': 'shop'})
    r.update(name='tested', rewrite={'uri': '/backend/'})
    r['headers']['request']['remove'] = ['x-secret']
    r['headers']['response'] = {'set': {'x-version': '1'}}
    docs = config([r])
    if kind == 'split':
        r['route'] = [{'destination': {'host': 'orders'}, 'weight': 70}, {'destination': {'host': 'products'}, 'weight': 30}]
    elif kind == 'retry-budget':
        r.update(retries={'attempts': 2, 'retryOn': '5xx', 'perTryTimeout': '250ms'}, timeout='500ms')
    else:
        r['retries'] = {'attempts': 0}
        docs['destination_rules'] = [{'kind': 'DestinationRule', 'metadata': {'name': 'pool', 'namespace': 'demo'},
            'spec': {'host': 'orders', 'trafficPolicy': {'connectionPool': {'tcp': {'maxConnections': 1}, 'http': {'http1MaxPendingRequests': 1}}}}}]
    profiles = [{'rule_name': 'tested', 'kind': kind, 'backend_contract': CONTRACT, 'samples': 200,
                 'request': {'host': 'shop.example.com', 'path': '/shop/item?q=1', 'method': 'GET', 'headers': {}}}]
    return docs, profiles


def synthetic(plan):
    evidence = {'schema': EVIDENCE_SCHEMA, 'reference_model_hash': plan['reference_model_hash'], 'run_id': 'run', 'observations': []}
    for p in plan['candidate_probes']:
        if p['id'] not in plan['selected_probe_ids']:
            continue
        e = {'probe_id': p['id'], 'probe_hash': p['probe_hash'], 'run_id': 'run', 'execution_id': p['id'],
             'reference_model_hash': plan['reference_model_hash'], 'backend_contract': CONTRACT,
             'sent_request': copy.deepcopy(p['request']), 'started_at': 1, 'completed_at': 3,
             'attempt_capture_complete': True, 'samples': []}
        for i in range(p['load']['requests']):
            rid = p['id']+str(i)
            destination = 'orders' if i % 10 < 7 else 'products'
            receipts = [{'event_id': rid, 'source_kind': 'backend_receipt', 'request_id': rid, 'observed_at': 1.1,
                         'backend_identity': 'Service/demo/'+destination, 'headers_complete': True,
                         'request_headers': {'x-source': 'shop'}, 'path': '/backend/item?q=1', 'produced_status': 200}]
            e['samples'].append({'request_id': rid, 'activation_confirmed': True, 'started_at': 1,
                                 'completed_at': 2, 'status': 200, 'backend_receipts': receipts,
                                 'response_headers_complete': True, 'response_headers': {'x-version': '1'}})
        evidence['observations'].append(e)
    return evidence


class BehaviorProfileTests(unittest.TestCase):
    def test_four_obligations_share_split_batch_without_duplicating_baseline_load(self):
        docs, profiles = fixture('split')
        model = build_relational_model(docs)
        before, after = [plan_obligations(model, reuse=r, profiles=profiles) for r in (False, True)]
        self.assertEqual(before['summary']['planned_http_requests'], 203)
        self.assertEqual(after['summary']['planned_http_requests'], 200)
        self.assertEqual(after['summary']['selected_probes'], 1)
        e = synthetic(after)
        self.assertEqual(evaluate_obligations(after, e)['summary'], {'PASS': 4, 'FAIL': 0, 'INCONCLUSIVE': 0})
        for sample in e['observations'][0]['samples']:
            sample['backend_receipts'][0]['backend_identity'] = 'Service/demo/orders'
        self.assertEqual(evaluate_obligations(after, e)['summary']['FAIL'], 1)

    def test_duplicate_missing_or_uncorrelated_samples_cannot_pass(self):
        docs, profiles = fixture('split')
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        for mutation in ('missing', 'duplicate', 'wrong-run', 'stale', 'incomplete'):
            e = synthetic(plan)
            execution = e['observations'][0]
            if mutation == 'missing':
                execution['samples'].pop()
            elif mutation == 'duplicate':
                execution['samples'][1] = copy.deepcopy(execution['samples'][0])
            elif mutation == 'wrong-run':
                execution['run_id'] = 'other'
            elif mutation == 'stale':
                execution['samples'][0]['backend_receipts'][0]['observed_at'] = 0
            else:
                execution['attempt_capture_complete'] = False
            self.assertEqual(evaluate_obligations(plan, e)['summary']['PASS'], 0, mutation)

    def test_retry_recovery_and_slow_budget_cannot_replace_each_other(self):
        docs, profiles = fixture('retry-budget')
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        selected = [p for p in plan['candidate_probes'] if p['id'] in plan['selected_probe_ids']]
        self.assertEqual({p['phase'] for p in selected}, {'recover', 'slow'})
        for d in plan['coverage_decisions']:
            p = next(p for p in plan['candidate_probes'] if p['id'] == d['probe_id'])
            o = next(o for o in plan['obligations'] if o['id'] == d['obligation_id'])
            if o['H']['kind'] == 'retry_recovery' and p['phase'] == 'slow':
                self.assertEqual(d['W'], 0)
        self.assertEqual(plan['summary']['unplanned_obligations'], 0)

    def test_unknown_third_policy_or_inheritance_blocks_profile_reuse(self):
        for kind in ('split', 'retry-budget', 'pool'):
            docs, profiles = fixture(kind)
            docs['virtual_services'][0]['spec']['http'][0]['mirror'] = {'host': 'vip'}
            plan = plan_obligations(build_relational_model(docs), profiles=profiles)
            self.assertEqual(plan['summary']['selected_probes'], 0)
            self.assertGreater(plan['summary']['unplanned_obligations'], 0)

    def test_unspecified_or_unsupported_duration_remains_unknown(self):
        for value in (None, '1m', '250000000ns'):
            docs, profiles = fixture('retry-budget')
            retry = docs['virtual_services'][0]['spec']['http'][0]['retries']
            if value is None:
                retry.pop('perTryTimeout')
            else:
                retry['perTryTimeout'] = value
            plan = plan_obligations(build_relational_model(docs), profiles=profiles)
            self.assertEqual(plan['summary']['selected_probes'], 0)
            self.assertEqual(plan['summary']['unplanned_obligations'], plan['summary']['obligations'])

    def test_retry_attempts_are_correlated_and_timeout_does_not_mask_missing_retry(self):
        docs, profiles = fixture('retry-budget')
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        evidence = synthetic(plan)
        probes = {p['id']: p for p in plan['candidate_probes']}
        for e in evidence['observations']:
            s = e['samples'][0]
            original = s['backend_receipts'][0]
            if probes[e['probe_id']]['phase'] == 'recover':
                s['backend_receipts'] = []
                for i, code in enumerate((503, 503, 200)):
                    receipt = copy.deepcopy(original)
                    receipt.update(event_id=original['event_id']+str(i), observed_at=1.1+i*.1, produced_status=code)
                    s['backend_receipts'].append(receipt)
                recovery = s
            else:
                s.update(status=504, completed_at=1.5)
                original.update(observed_at=1.01, planned_delay=.4)
                second = copy.deepcopy(original)
                second.update(event_id=original['event_id']+'second', observed_at=1.27)
                s['backend_receipts'].append(second)
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['PASS'], 7)
        recovery.update(status=503, backend_receipts=recovery['backend_receipts'][:1])
        result = evaluate_obligations(plan, evidence)
        self.assertEqual(result['summary']['FAIL'], 1)
        self.assertIn('/retry', next(r['obligation_id'] for r in result['results'] if r['verdict'] == 'FAIL'))

    def test_pool_503_without_envoy_overflow_evidence_is_not_a_pass(self):
        docs, profiles = fixture('pool')
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        evidence = synthetic(plan)
        probes = {p['id']: p for p in plan['candidate_probes']}
        for e in evidence['observations']:
            for i, s in enumerate(e['samples']):
                for r in s['backend_receipts']:
                    r.update(backend_identity='Service/demo/orders', finished_at=1.6)
                if probes[e['probe_id']]['phase'] == 'burst':
                    s['response_headers']['x-audit-response-flags'] = '-' if i < 2 else 'UO'
                    if i >= 2:
                        s.update(status=503, backend_receipts=[])
                    burst = e
                else:
                    s['status'] = s['backend_receipts'][0]['produced_status'] = 503
        result = evaluate_obligations(plan, evidence)
        self.assertEqual(result['summary']['PASS'], 6)
        # Persisted judgments must compare exactly with evidence replay, including
        # HTTP status histograms whose JSON keys are necessarily strings.
        self.assertEqual(result, json.loads(json.dumps(result)))
        self.assertEqual(result, evaluate_obligations(plan, json.loads(json.dumps(evidence))))
        for s in burst['samples']:
            del s['response_headers']['x-audit-response-flags']
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['INCONCLUSIVE'], 1)
        for s in burst['samples']:
            s['response_headers']['x-audit-response-flags'] = '-'
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['FAIL'], 1)

    def test_pool_requires_no_retry_and_does_not_merge_saturation_with_fail_once(self):
        docs, profiles = fixture('pool')
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        self.assertEqual(plan['summary']['unplanned_obligations'], 0)
        self.assertEqual({p['phase'] for p in plan['candidate_probes'] if p['id'] in plan['selected_probe_ids']}, {'fail-once', 'burst'})
        docs['virtual_services'][0]['spec']['http'][0]['retries']['attempts'] = 1
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        self.assertEqual(plan['summary']['selected_probes'], 0)

    def test_literal_rewrite_preserves_suffix_query_and_complete_header_removal(self):
        docs, _ = fixture('retry-budget')
        r = docs['virtual_services'][0]['spec']['http'][0]
        del r['retries'], r['timeout']
        plan = plan_obligations(build_relational_model(docs))
        self.assertEqual(plan['summary']['selected_probes'], 1)
        p = next(p for p in plan['candidate_probes'] if p['id'] in plan['selected_probe_ids'])
        self.assertIn('x-secret', p['request']['headers'])
        assertion = next(o['H'] for o in plan['obligations'] if o['H']['kind'] == 'request_path_rewrite')
        self.assertEqual(rewrite_expected(assertion, {'host': 'shop.example.com', 'path': '/shop/item?q=1', 'method': 'GET', 'headers': {}}), '/backend/item?q=1')
        evidence = evidence_for(plan)
        e = evidence['observations'][0]
        e['backend_receipts'][0]['backend_identity'] = 'Service/demo/orders'
        e['backend_receipts'][0]['request_headers'] = {'x-source': 'shop'}
        e['backend_receipts'][0]['path'] = rewrite_expected(assertion, p['request'])
        e.update(response_headers={'x-version': '1'}, response_headers_complete=True)
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['PASS'], 4)
        e['backend_receipts'][0]['request_headers']['x-secret'] = 'still-present'
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['FAIL'], 1)


if __name__ == '__main__':
    unittest.main()
