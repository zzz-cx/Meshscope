"""End-to-end artifact, execution and resource tests for the new default path."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from configpilot.workflow import load_json, run_validation, write_json
from configpilot.cli import build_parser, cmd_check
from istio_config_parser.models.relational_model import build_relational_model, dependency_slice, digest
from istio_Dynamic_Test.internal.planning.engine import ClosureIndex, build_plan
from istio_Dynamic_Test.internal.planning.relational import plan_obligations
from istio_Dynamic_Test.internal.pipeline.scheduling.locks import LockManager
from istio_Dynamic_Test.internal.traffic.controlled import http_call, execute_controlled_plan
from istio_Dynamic_Test.internal.traffic.controlled_backend import ControlledBackends
from istio_Dynamic_Test.internal.traffic.receipts import ReceiptCollector
from istio_Dynamic_Test.internal.traffic.leases import execution_lease
from istio_Dynamic_Test.tests import test_controlled_execution as controlled_tests
from istio_Dynamic_Test.tests.test_relational_planning import simple_model, evidence_for
from istio_Dynamic_Test.tests.test_behavior_profiles import fixture


class IndexedPlanningTests(unittest.TestCase):
    def test_index_matches_directional_fixed_point_on_cycles_and_unknowns(self):
        rng = random.Random(20261116)
        types = ['attached_to', 'references', 'precedes', 'shared_time_budget',
                 'may_short_circuit', 'inherits_overrides', 'future_relation']
        for case in range(18):
            nodes = ['n%d' % i for i in range(12)]
            relations = [{'id': 'r%d' % i, 'type': rng.choice(types),
                'participants': rng.sample(nodes, rng.randint(2, 4))} for i in range(case*2)]
            index = ClosureIndex(relations)
            for source in nodes+[r['id'] for r in relations]:
                self.assertEqual(index.slice(source), dependency_slice({'relations': relations}, source))

    def test_compute_backends_preserve_the_entire_plan(self):
        model = simple_model()
        expected = plan_obligations(model)
        for backend in ('serial', 'thread', 'process'):
            actual, metrics = build_plan(model, backend=backend, workers=2)
            self.assertEqual(actual, expected)
            self.assertEqual(metrics['backend'], backend)

    def test_wrong_cache_and_missing_go_binary_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'cache'):
            plan_obligations(simple_model(), dependency_cache={'reference_model_hash': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'go-binary'):
            build_plan(simple_model(), backend='go')


class WorkflowTests(unittest.TestCase):
    def test_plan_replay_diagnostics_and_frozen_run_integrity(self):
        model = simple_model()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            planned = run_validation(artifact={'relational_model': model}, output_dir=root/'planned')
            self.assertEqual(planned['status'], 'PLANNED')
            self.assertEqual(planned['coverage']['total_obligations'], 3)
            self.assertEqual(planned['coverage']['assessed_obligations'], 0)
            plan = load_json(root/'planned/probe_plan.json')
            evidence = evidence_for(plan)
            evidence['observations'][0]['backend_receipts'][0]['backend_identity'] = 'Service/demo/vip'
            result = run_validation(artifact=model, output_dir=root/'replayed', frozen_plan=plan, evidence=evidence)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['results']['FAIL'], 1)
            self.assertEqual(result['results']['INCONCLUSIVE'], 1)
            graph = load_json(root/'replayed/dependency_graph.json')
            self.assertTrue(any(n['kind'] == 'evidence' for n in graph['nodes']))
            diagnostics = load_json(root/'replayed/diagnostics.json')
            self.assertEqual(len(diagnostics['failures']), 1)
            self.assertTrue(diagnostics['failures'][0]['candidate_resources'])
            with patch('builtins.print'):
                self.assertEqual(cmd_check(build_parser().parse_args(['check', '--run-dir', str(root/'replayed')])), 2)
            changed = load_json(root/'replayed/run_report.json')
            changed['status'] = 'PASSED'
            write_json(root/'replayed/run_report.json', changed)
            with self.assertRaisesRegex(ValueError, 'report status'):
                cmd_check(build_parser().parse_args(['check', '--run-dir', str(root/'replayed')]))
            with self.assertRaisesRegex(ValueError, 'new or empty'):
                run_validation(artifact=model, output_dir=root/'planned')

    def test_unsupported_obligations_remain_in_denominator(self):
        docs, _ = fixture('retry-budget')
        model = build_relational_model(docs)
        with tempfile.TemporaryDirectory() as temporary:
            report = run_validation(artifact=model, output_dir=temporary)
            self.assertGreater(report['coverage']['unplanned_obligations'], 0)
            self.assertEqual(report['results']['INCONCLUSIVE'], len(plan_obligations(model)['obligations']))
            self.assertEqual(report['coverage']['assessment_ratio'], 0)

    def test_interruption_preserves_persisted_counterevidence(self):
        model = simple_model()
        plan = plan_obligations(model)
        evidence = evidence_for(plan)
        first = evidence['observations'][0]
        first['backend_receipts'][0]['backend_identity'] = 'Service/demo/vip'
        def interrupted(plan, **options):
            options['persist_observation'](first)
            raise RuntimeError('simulated interruption after first completed observation')
        with tempfile.TemporaryDirectory() as temporary, patch(
                'istio_Dynamic_Test.internal.traffic.controlled.execute_controlled_plan', side_effect=interrupted):
            report = run_validation(artifact=model, output_dir=temporary, execute=True,
                ingress_url='http://127.0.0.1:1', control_url='http://127.0.0.1:2',
                activation_headers={'shop.example.com': {'x-audit-generation': 'prepared'}})
            self.assertEqual(report['status'], 'FAILED')
            self.assertEqual(report['results']['FAIL'], 1)
            self.assertIsNotNone(report['engine_error'])
            self.assertEqual(len(load_json(Path(temporary)/'captured_evidence.json')['observations']), 1)

    def test_cli_uses_new_engine_and_retains_explicit_legacy(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(['dynamic', '--compute-backend', 'process']).action, 'dynamic')
        self.assertEqual(parser.parse_args(['legacy-dynamic', '--', '--help']).dynamic_args, ['--', '--help'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root/'aligned.json', {'relational_model': simple_model()})
            process = subprocess.run([sys.executable, '-m', 'configpilot', 'plan', '--aligned', str(root/'aligned.json'),
                '--output-dir', str(root/'run')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(load_json(root/'run/run_report.json')['status'], 'PLANNED')


class ReservationBudgetTests(unittest.TestCase):
    def test_capacity_is_reserved_atomically_with_resource_reads(self):
        locks = LockManager(capacity=4)
        first = locks.try_reserve(['read:config:A', 'load:3'])
        self.assertIsNotNone(first)
        self.assertIsNone(locks.try_reserve(['read:config:A', 'load:2']))
        self.assertIsNone(locks.try_reserve(['config:A', 'load:1']))
        first.release()
        second = locks.try_reserve(['config:A', 'load:4'])
        self.assertIsNotNone(second)
        self.assertEqual(locks.peak_load, 4)
        second.release()
        self.assertEqual(locks._used_load, 0)

    def test_endpoint_lease_refuses_overlapping_runs_and_releases(self):
        with execution_lease('http://127.0.0.1:19791'):
            with self.assertRaises(RuntimeError):
                with execution_lease('http://localhost:19791'):
                    self.fail('overlapping lease was admitted')
        with execution_lease('http://127.0.0.1:19791'):
            pass


class BackendLifecycleTests(unittest.TestCase):
    def test_capacity_release_and_no_global_reset(self):
        backend = ControlledBackends('demo', {'orders': 0}, max_records=2).start()
        try:
            url = 'http://127.0.0.1:%d/' % backend.endpoints['orders']
            for rid in ('one', 'two'):
                self.assertEqual(http_call(url, 'GET', headers={'x-audit-request': rid})[0], 200)
            self.assertEqual(http_call(url, 'GET', headers={'x-audit-request': 'three'})[0], 503)
            self.assertEqual(backend.record_count, 2)
            code, _, _ = http_call(backend.control_url+'release', 'POST', body=b'{"ids":["one"]}')
            self.assertEqual(code, 200)
            self.assertNotIn('one', backend.counts)
            self.assertEqual(http_call(url, 'GET', headers={'x-audit-request': 'three'})[0], 200)
            self.assertEqual(http_call(backend.control_url, 'POST', body=b'{"reset":true}')[0], 400)
        finally:
            backend.close()

    def test_retention_never_removes_unfinished_attempts(self):
        backend = ControlledBackends('demo', {'orders': 0}, retention_seconds=30)
        backend.records = {'done': [{'finished_at': time.time()-40}], 'active': [{'observed_at': time.time()-40}]}
        backend.counts, backend.record_count = {'done': 1, 'active': 1}, 2
        backend._expire(force=True)
        self.assertEqual(set(backend.records), {'active'})
        self.assertEqual(backend.record_count, 1)

    def test_release_refuses_a_real_running_attempt(self):
        backend = ControlledBackends('demo', {'orders': 0}).start()
        try:
            url = 'http://127.0.0.1:%d/' % backend.endpoints['orders']
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(http_call, url, 'GET', headers={'x-audit-request': 'active', 'x-audit-delay': '.2'})
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    with backend.lock:
                        if backend.records.get('active'):
                            break
                    time.sleep(.005)
                self.assertEqual(http_call(backend.control_url+'release', 'POST', body=b'{"ids":["active"]}')[0], 409)
                self.assertEqual(future.result()[0], 200)
                self.assertEqual(http_call(backend.control_url+'release', 'POST', body=b'{"ids":["active"]}')[0], 200)
        finally:
            backend.close()

    def test_shared_collection_batches_ids_and_reuses_correlated_snapshot(self):
        queries = []
        def call(url, method, **options):
            ids = json.loads(options['body'])['ids']
            queries.append(ids)
            return 200, {}, json.dumps({'contract': 'configpilot.controlled-http-backend/2',
                'per_request_state': True, 'complete': True, 'records': {rid: [{'event_id': rid}] for rid in ids}}).encode()
        collector = ReceiptCollector(call, 'http://127.0.0.1/', poll_interval=5)
        collector.register(['a', 'b'])
        first = collector.poll(['a'])
        collector.poll(['b'])
        self.assertEqual(queries, [[], ['a', 'b']])
        self.assertEqual(collector.stats['cache_hits'], 1)
        first['records']['a'][0]['event_id'] = 'mutated'
        self.assertEqual(collector.poll(['a'])['records']['a'][0]['event_id'], 'a')

    def test_snapshot_must_start_after_client_completion(self):
        queries = []
        def call(url, method, **options):
            ids = json.loads(options['body'])['ids']
            queries.append(ids)
            return 200, {}, json.dumps({'contract': 'configpilot.controlled-http-backend/2',
                'per_request_state': True, 'complete': True, 'records': {rid: [] for rid in ids}}).encode()
        collector = ReceiptCollector(call, 'http://127.0.0.1/', poll_interval=5)
        collector.register(['a', 'b'])
        collector.poll(['a'])
        collector.poll(['b'], not_before=time.perf_counter())
        self.assertEqual(len(queries), 3)


class GenericExecutionTests(unittest.TestCase):
    setUp = controlled_tests.ControlledHTTPTests.setUp
    tearDown = controlled_tests.ControlledHTTPTests.tearDown

    def model(self):
        docs, _ = fixture('retry-budget')
        rule = docs['virtual_services'][0]['spec']['http'][0]
        rule.pop('retries')
        rule.pop('timeout')
        first, second = copy.deepcopy(rule), copy.deepcopy(rule)
        for index, item in enumerate((first, second)):
            item['name'] = 'plain-%d' % index
            item['match'][0]['uri']['prefix'] = '/shop/%d/' % index
            item['rewrite']['uri'] = '/backend/%d/' % index
        docs['virtual_services'][0]['spec']['http'] = [first, second]
        return build_relational_model(docs)

    def options(self):
        return {'ingress_url': 'http://127.0.0.1:%d' % self.proxy.server_port,
                'control_url': self.backend.control_url, 'max_workers': 2,
                'activation_headers': {'shop.example.com': {'x-audit-generation': 'ready-v1'}}}

    def test_same_vs_stateless_probes_are_concurrent_and_individually_judged(self):
        plan = plan_obligations(self.model())
        _, results, metrics = execute_controlled_plan(plan, **self.options())
        self.assertEqual(results['summary'], {'PASS': 8, 'FAIL': 0, 'INCONCLUSIVE': 0})
        self.assertEqual(metrics['scheduler']['peak_busy_workers'], 2)
        self.assertLessEqual(metrics['peak_reserved_load'], metrics['capacity_budget'])
        self.assertEqual(metrics['mesh_configuration_writes'], 0)

    def test_workflow_saves_evidence_before_reclaiming_receipts(self):
        options = self.options()
        with tempfile.TemporaryDirectory() as temporary:
            report = run_validation(artifact=self.model(), output_dir=temporary, execute=True,
                ingress_url=options['ingress_url'], control_url=options['control_url'],
                activation_headers=options['activation_headers'], workers=2)
            self.assertEqual(report['status'], 'PASSED')
            self.assertTrue((Path(temporary)/'captured_evidence.json').is_file())
            self.assertGreater(report['execution']['receipt_cleanup']['released_records'], 0)
            self.assertEqual(self.backend.record_count, 0)

    def test_capacity_budget_limits_parallel_traffic(self):
        options = {**self.options(), 'capacity': 1}
        _, results, metrics = execute_controlled_plan(plan_obligations(self.model()), **options)
        self.assertEqual(results['summary']['PASS'], 8)
        self.assertEqual(metrics['peak_reserved_load'], 1)
        self.assertEqual(metrics['scheduler']['peak_busy_workers'], 1)

    def test_split_adapter_detects_all_traffic_reaching_one_target(self):
        docs, profiles = fixture('split')
        profiles[0]['backend_contract'] = 'configpilot.controlled-http-backend/2'
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        _, results, metrics = execute_controlled_plan(plan, **self.options())
        self.assertEqual(metrics['http_requests'], 200)
        self.assertEqual(results['summary']['FAIL'], 1)

    def test_backend_overload_is_not_reported_as_policy_success(self):
        self.backend.max_records = 1
        _, results, _ = execute_controlled_plan(plan_obligations(self.model()), **self.options())
        self.assertEqual(results['summary']['PASS'], 0)
        self.assertGreater(results['summary']['INCONCLUSIVE'], 0)

    def test_configuration_change_invalidates_results_without_claiming_strategy_failure(self):
        snapshots = iter([{'policy': {'uid': 'a', 'resourceVersion': '1'}},
                          {'policy': {'uid': 'a', 'resourceVersion': '2'}}])
        options = self.options()
        with tempfile.TemporaryDirectory() as temporary:
            report = run_validation(artifact=self.model(), output_dir=temporary, execute=True,
                ingress_url=options['ingress_url'], control_url=options['control_url'],
                activation_headers=options['activation_headers'], workers=2,
                config_snapshotter=lambda model: next(snapshots))
            self.assertEqual(report['status'], 'INCONCLUSIVE')
            self.assertEqual(report['results']['PASS'], 0)
            self.assertEqual(report['results']['FAIL'], 0)
            self.assertFalse(report['execution']['configuration_fence']['stable'])


if __name__ == '__main__':
    unittest.main()
