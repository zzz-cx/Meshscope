import copy
import unittest

from istio_config_parser.models.relational_model import build_relational_model
from istio_Dynamic_Test.internal.planning.behavior_profiles import PARAMETERIZED_CONTRACT
from istio_Dynamic_Test.internal.planning.relational import evaluate_obligations, plan_obligations
from istio_Dynamic_Test.internal.planning.parallel import plan_partitions
from istio_Dynamic_Test.tests.test_behavior_profiles import fixture, synthetic
from istio_Dynamic_Test.tests.test_relational_planning import config, route


class MultiServiceContextTests(unittest.TestCase):
    def test_dense_unrelated_predicates_do_not_starve_target_or_overlap_witnesses(self):
        vip = route('/shop/vip/', 'vip')
        vip['match'][0].update(headers={'x-tier': {'exact': 'gold'}}, queryParams={'region': {'exact': 'cn'}})
        routes = [vip, route('/shop/', 'orders')]
        for i in range(8):
            extra = route('/extra%d/' % i, 'products')
            extra['match'][0].update(headers={'x-field%d' % i: {'exact': 'value%d' % i}},
                                    queryParams={'q%d' % i: {'exact': str(i)}})
            routes.append(extra)
        model = build_relational_model(config(routes))
        for reuse in (False, True):
            plan = plan_obligations(model, reuse=reuse)
            self.assertEqual(plan['summary']['unplanned_obligations'], 0)
            self.assertEqual(len(plan['obligations']), 11)  # 10 routes + observable precedence.

    def test_target_seeding_does_not_authorize_shadowed_or_unknown_matches(self):
        first, second = route('/shop/', 'orders'), route('/shop/vip/', 'vip')
        model = build_relational_model(config([first, second]))
        plan = plan_obligations(model)
        hidden = next(o for o in plan['obligations'] if '#/spec/http/1/routing' in o['id'])
        self.assertTrue(hidden['unplanned_reason'])
        second['match'][0]['uri'] = {'regex': '/shop/.*'}
        plan = plan_obligations(build_relational_model(config([second])))
        self.assertEqual(plan['summary']['selected_probes'], 0)

    def test_parameterized_contract_requires_actual_backend_timing_attestation(self):
        docs, profiles = fixture('split')
        profiles[0]['backend_contract'] = PARAMETERIZED_CONTRACT
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        evidence = synthetic(plan)
        for e in evidence['observations']:
            e['backend_contract'] = PARAMETERIZED_CONTRACT
            for s in e['samples']:
                for r in s['backend_receipts']:
                    r.update(backend_contract=PARAMETERIZED_CONTRACT, planned_delay=.01)
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['PASS'], 4)
        evidence['observations'][0]['samples'][0]['backend_receipts'][0]['planned_delay'] = .1
        self.assertEqual(evaluate_obligations(plan, evidence)['summary']['PASS'], 0)

    def test_exact_unrelated_dr_does_not_block_but_related_or_unknown_scope_does(self):
        docs = config([route('/orders/', 'orders')])
        dr = {'kind': 'DestinationRule', 'metadata': {'name': 'other', 'namespace': 'demo'},
              'spec': {'host': 'products.demo.svc.cluster.local', 'trafficPolicy': {'connectionPool': {'tcp': {'maxConnections': 1}}}}}
        docs['destination_rules'] = [dr]
        self.assertEqual(plan_obligations(build_relational_model(docs))['summary']['selected_probes'], 1)
        for host, extra in [('orders', {}), ('*.demo.svc.cluster.local', {}), ('products', {'exportTo': ['*']}), ('products', {'workloadSelector': {'matchLabels': {'app': 'x'}}})]:
            changed = copy.deepcopy(docs)
            changed['destination_rules'][0]['spec'].update(host=host, **extra)
            self.assertEqual(plan_obligations(build_relational_model(changed))['summary']['selected_probes'], 0)

    def test_many_distinct_pool_rules_keep_actual_state_domains(self):
        docs, profiles = fixture('pool')
        dr2 = copy.deepcopy(docs['destination_rules'][0])
        dr2['metadata']['name'] = 'unrelated-pool'
        dr2['spec']['host'] = 'products'
        docs['destination_rules'].append(dr2)
        profiles[0]['backend_contract'] = PARAMETERIZED_CONTRACT
        model = build_relational_model(docs)
        plan = plan_obligations(model, profiles=profiles,
                                resource_ids=['VirtualService/demo/shop', 'DestinationRule/demo/pool'])
        self.assertEqual(plan['summary']['unplanned_obligations'], 0)
        self.assertTrue(all('connection-pool:DestinationRule/demo/pool' in p['footprint']['state_domains'] for p in plan['candidate_probes']))
        docs['destination_rules'][1]['spec']['host'] = 'orders'
        self.assertEqual(plan_obligations(build_relational_model(docs), profiles=profiles)['summary']['selected_probes'], 0)

    def test_parameterized_retry_stimulus_is_derived_from_reference(self):
        docs, profiles = fixture('retry-budget')
        profiles[0]['backend_contract'] = PARAMETERIZED_CONTRACT
        r = docs['virtual_services'][0]['spec']['http'][0]
        r.update(retries={'attempts': 3, 'retryOn': '5xx', 'perTryTimeout': '400ms'}, timeout='800ms')
        model = build_relational_model(docs)
        plan = plan_obligations(model, profiles=profiles)
        self.assertEqual(plan['summary']['unplanned_obligations'], 0)
        recovery = next(p for p in plan['candidate_probes'] if p['phase'] == 'recover')
        slow = next(p for p in plan['candidate_probes'] if p['phase'] == 'slow')
        self.assertEqual(recovery['stimulus']['failures_before_success'], 3)
        self.assertAlmostEqual(slow['stimulus']['delay_seconds'], .64)
        self.assertEqual(slow['stimulus']['derived_from_reference'], model['model_hash'])
        jobs = [{'job_id': 'retry', 'resource_ids': ['VirtualService/demo/shop'], 'profiles': profiles}]
        self.assertEqual(plan_partitions(model, jobs, backend='thread', max_workers=2), plan_partitions(model, jobs))
        r['headers']['request']['set']['x-audit-delay'] = '0'
        self.assertEqual(plan_obligations(build_relational_model(docs), profiles=profiles)['summary']['selected_probes'], 0)


if __name__ == '__main__':
    unittest.main()
