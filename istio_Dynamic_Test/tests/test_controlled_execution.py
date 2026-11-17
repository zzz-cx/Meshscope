"""HTTP adapter integration tests. The test proxy is not a real Envoy oracle."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from istio_Dynamic_Test.internal.models.testcase import (
    TestCase, TestSuite, PolicyType, ExecutionResult, CollectionResult,
    ValidationStatus, PipelineResult,
)
from istio_Dynamic_Test.internal.pipeline.scheduling.locks import mutation_trigger
from istio_Dynamic_Test.internal.planning.behavior_profiles import PARAMETERIZED_CONTRACT
from istio_Dynamic_Test.internal.planning.relational import plan_obligations
from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator
from istio_Dynamic_Test.internal.traffic.controlled import execute_controlled_plan, http_call
from istio_Dynamic_Test.internal.traffic.controlled_backend import ControlledBackends
from istio_Dynamic_Test.internal.validation.composite import CompositeValidator
from istio_Dynamic_Test.internal.validation.report import ReportGenerator
from istio_Dynamic_Test.tests.test_behavior_profiles import fixture
from istio_config_parser.models.relational_model import build_relational_model


class MigrationTests(unittest.TestCase):
    def test_generated_retry_has_no_vs_abort_and_keeps_attempts(self):
        raw = SemanticGenerator()._tuple_to_cases({'constraint': {'attempts': 2},
            'scope': {'service': 'orders'}}, PolicyType.RETRY, 1)[0]
        tc = TestCase.from_matrix_dict(raw)
        self.assertEqual(tc.expected_retry_attempts, 2)
        self.assertEqual(mutation_trigger(tc), '')
        self.assertNotIn('fault_type', raw['request_params'])

    def test_old_matrix_cannot_inject_or_warmup_or_send(self):
        from istio_Dynamic_Test.internal.pipeline import cli
        cases = [TestCase(case_id=str(policy), name='legacy', host='orders', policy_types=[policy],
                         trigger_condition='simulate_config_fault')
                 for policy in (PolicyType.RETRY, PolicyType.CIRCUIT_BREAKER, PolicyType.CONNECTION_POOL_OUTLIER)]
        with patch.object(cli, 'SSHClient') as ssh, patch.object(cli, 'FaultInjector') as injector, \
             patch.object(cli, 'ReportGenerator'):
            ssh.return_value.run_command.return_value = ('{"items": []}', '')
            collector, executor = Mock(), Mock()
            tester = cli.DynamicTester(executor=executor, collector=collector)
            results = tester.run(TestSuite(cases=cases))
            self.assertTrue(all(r.validation.overall_status == ValidationStatus.INCONCLUSIVE for r in results))
            collector.warmup_for_suite.assert_not_called()
            executor.execute.assert_not_called()
            injector.assert_not_called()

    def test_503_totals_and_duplicate_logs_cannot_pass(self):
        for policy in (PolicyType.RETRY, PolicyType.CIRCUIT_BREAKER, PolicyType.CONNECTION_POOL,
                       PolicyType.CONNECTION_POOL_OUTLIER):
            tc = TestCase(case_id='a', name='a', policy_types=[policy])
            result = CompositeValidator().validate(tc, ExecutionResult(case_id='a',
                total_requests=100, success_rate=80, status_codes={'503':20, '200':80}),
                CollectionResult(case_id='a', envoy_logs={'pod':'200 503 503'}))
            self.assertEqual(result.overall_status, ValidationStatus.INCONCLUSIVE)
            report = ReportGenerator._build_json([PipelineResult(test_case=tc, validation=result)])
            self.assertEqual((report['failed'], report['passed'], report['inconclusive']), (0, 0, 1))


class ControlledHTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend = ControlledBackends('demo', {'orders': 0, 'products': 0}).start()
        owner = self
        self.retry_enabled, self.generation, self.overflow_enabled = True, 'ready-v1', True
        self.semaphore = threading.BoundedSemaphore(2)
        self.sent = 0
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                owner.sent += 1
                mode = self.headers.get('x-test-mode', 'normal')
                code, data, flag = 200, b'{}', '-'
                acquired = mode != 'burst' or owner.semaphore.acquire(blocking=False)
                try:
                    if not acquired:
                        code, flag = 503, 'UO' if owner.overflow_enabled else '-'
                    else:
                        headers = dict(self.headers)
                        headers['x-source'] = 'shop'
                        headers.pop('x-secret', None)
                        path = self.path.replace('/shop/', '/backend/', 1)
                        url = 'http://127.0.0.1:%d%s' % (owner.backend.endpoints['orders'], path)
                        attempts = 3 if mode == 'recover' and owner.retry_enabled else 2 if mode == 'slow' else 1
                        for _ in range(attempts):
                            try:
                                code, _, data = http_call(url, 'GET', headers=headers,
                                                         timeout=.25 if mode == 'slow' else 2)
                            except OSError:
                                code, data = 504, b'{}'
                            if code == 200 or mode not in ('recover', 'slow'): break
                finally:
                    if mode == 'burst' and acquired: owner.semaphore.release()
                self.send_response(code)
                self.send_header('x-audit-generation', owner.generation)
                self.send_header('x-audit-response-flags', flag)
                self.send_header('x-version', '1')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        self.thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.thread.join()
        self.backend.close()

    def run_plan(self, kind, **kwargs):
        docs, profiles = fixture(kind)
        profiles[0]['backend_contract'] = PARAMETERIZED_CONTRACT
        plan = plan_obligations(build_relational_model(docs), profiles=profiles)
        options = {'ingress_url':'http://127.0.0.1:%d' % self.proxy.server_port,
                   'control_url':self.backend.control_url,
                   'activation_headers':{'shop.example.com':{'x-audit-generation':'ready-v1'}},
                   'max_workers':2}
        options.update(kwargs)
        return execute_controlled_plan(plan, **options)

    def test_retry_recovery_and_budget_with_real_http_receipts(self):
        evidence, results, metrics = self.run_plan('retry-budget')
        self.assertEqual(results['summary']['FAIL'], 0)
        self.assertEqual(results['summary']['INCONCLUSIVE'], 0)
        self.assertEqual(metrics['mesh_configuration_writes'], 0)
        self.assertEqual(metrics['http_requests'], 2)
        phases = [sorted(r['produced_status'] for r in s['backend_receipts'])
                  for e in evidence['observations'] for s in e['samples']]
        self.assertIn([200,503,503], phases)

    def test_missing_retry_is_detected_not_hidden_by_timeout(self):
        self.retry_enabled = False
        _, results, _ = self.run_plan('retry-budget')
        self.assertGreater(results['summary']['FAIL'], 0)

    def test_stale_generation_cannot_pass(self):
        self.generation = 'old'
        _, results, _ = self.run_plan('retry-budget')
        self.assertEqual(results['summary']['PASS'], 0)
        self.assertGreater(results['summary']['INCONCLUSIVE'], 0)

    def test_pool_requires_proxy_overflow_not_merely_503(self):
        _, results, metrics = self.run_plan('pool')
        self.assertEqual(results['summary']['FAIL'], 0)
        self.assertEqual(results['summary']['INCONCLUSIVE'], 0)
        self.assertEqual(metrics['http_requests'], 17)
        self.overflow_enabled = False
        _, results, _ = self.run_plan('pool')
        self.assertGreater(results['summary']['FAIL'], 0)

    def test_activation_precondition_is_required_before_sending(self):
        with self.assertRaisesRegex(ValueError, 'activation'):
            self.run_plan('retry-budget', activation_headers={})
        self.assertEqual(self.sent, 0)

    def test_incomplete_attempt_capture_cannot_pass(self):
        reply = self.backend._reply
        def incomplete(handler, status, payload):
            if 'records' in payload:
                payload = dict(payload, complete=False)
            reply(handler, status, payload)
        with patch.object(self.backend, '_reply', side_effect=incomplete):
            _, results, _ = self.run_plan('retry-budget')
        self.assertEqual(results['summary']['PASS'], 0)
        self.assertGreater(results['summary']['INCONCLUSIVE'], 0)

    def test_read_only_control_api_rejects_global_reset(self):
        status, _, _ = http_call(self.backend.control_url, 'POST', body=json.dumps({'reset':True}).encode())
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
