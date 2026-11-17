import copy
import unittest

from istio_config_parser.models.relational_model import build_relational_model
from istio_Dynamic_Test.internal.planning.parallel import evaluate_batch, plan_partitions
from istio_Dynamic_Test.internal.planning.relational import plan_obligations
from istio_Dynamic_Test.tests.test_relational_planning import config, route, evidence_for, simple_model


class ParallelPlanningTests(unittest.TestCase):
    def test_partition_union_preserves_whole_plan_obligations_and_positive_edges(self):
        raw = config([route('/orders/', 'orders', {'x-source': 'shop'})])
        other = copy.deepcopy(raw['virtual_services'][0])
        other['metadata']['name'] = 'other'
        other['spec']['hosts'] = ['other.example.com']
        other['spec']['http'] = [route('/other/', 'vip')]
        raw['virtual_services'].append(other)
        model = build_relational_model(raw)
        whole = plan_obligations(model)
        parts = plan_partitions(model, [
            {'job_id': 'shop', 'resource_ids': ['VirtualService/demo/shop']},
            {'job_id': 'other', 'resource_ids': ['VirtualService/demo/other']}])
        self.assertEqual({o['id'] for o in whole['obligations']},
                         {o['id'] for item in parts for o in item['plan']['obligations']})
        self.assertEqual(set(whole['selected_probe_ids']),
                         {pid for item in parts for pid in item['plan']['selected_probe_ids']})
        def edges(plan):
            return {(d['probe_id'], d['obligation_id']) for d in plan['coverage_decisions'] if d['W']}
        self.assertEqual(edges(whole), set().union(*(edges(item['plan']) for item in parts)))

    def test_scope_does_not_hide_cross_resource_competitors(self):
        raw = config([route('/orders/', 'orders')])
        other = copy.deepcopy(raw['virtual_services'][0])
        other['metadata']['name'] = 'other'
        other['spec']['http'] = [route('/orders/', 'products')]
        raw['virtual_services'].append(other)
        model = build_relational_model(raw)
        plan = plan_obligations(model, resource_ids=['VirtualService/demo/shop'])
        self.assertEqual(plan['summary']['obligations'], 1)
        self.assertEqual(plan['summary']['unplanned_obligations'], 1)
        self.assertEqual(plan['summary']['selected_probes'], 0)
        with self.assertRaises(ValueError):
            plan_obligations(model, resource_ids=['VirtualService/demo/missing'])

    def test_thread_and_process_plans_keep_full_model_and_verdicts(self):
        model = simple_model()
        jobs = [{'job_id': 'one', 'resource_ids': ['VirtualService/demo/shop']}]
        baseline = plan_partitions(model, jobs)
        for backend in ('thread', 'process'):
            self.assertEqual(plan_partitions(model, jobs, backend=backend, max_workers=2), baseline)
        plan = baseline[0]['plan']
        evidence = evidence_for(plan)
        wrong = copy.deepcopy(evidence)
        wrong['observations'][0]['backend_receipts'][0]['backend_identity'] = 'Service/demo/vip'
        eval_jobs = [{'job_id': 'healthy', 'plan': plan, 'evidence': evidence},
                     {'job_id': 'mutant', 'plan': plan, 'evidence': wrong}]
        expected = evaluate_batch(eval_jobs)
        self.assertGreater(expected[1]['result']['summary']['FAIL'], 0)
        for backend in ('thread', 'process'):
            self.assertEqual(evaluate_batch(eval_jobs, backend=backend, max_workers=2), expected)

    def test_bad_evidence_raises_and_duplicate_job_ids_are_rejected(self):
        plan = plan_obligations(simple_model())
        evidence = evidence_for(plan)
        evidence['reference_model_hash'] = 'wrong'
        job = {'job_id': 'bad', 'plan': plan, 'evidence': evidence}
        with self.assertRaises(ValueError):
            evaluate_batch([job], backend='thread', max_workers=2)
        with self.assertRaises(ValueError):
            evaluate_batch([job, job])


if __name__ == '__main__':
    unittest.main()
