"""Supported behavior comparison, Web integration and optional Go equivalence."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from consistency_checker.config import GlobalConfig
from consistency_checker.web.relational import install_relational_api
from istio_config_parser.models.behavior_compare import compare_models
from istio_config_parser.models.relational_model import build_relational_model
from istio_Dynamic_Test.internal.planning.engine import build_plan
from istio_Dynamic_Test.internal.planning.relational import plan_obligations
from istio_Dynamic_Test.tests.test_relational_planning import config, route, simple_model, evidence_for


def comparison_model(routes):
    docs = config(routes)
    for service in docs['services']:
        service['spec']['ports'] = [{'port': 80}]
    return build_relational_model(docs)


class BoundedComparisonTests(unittest.TestCase):
    def test_actual_only_route_is_a_behavior_difference(self):
        before = comparison_model([route('/orders/', 'orders')])
        after = comparison_model([route('/orders/', 'orders'), route('/residual/', 'products')])
        result = compare_models(before, after)
        self.assertEqual(result['status'], 'DIFFERENT')
        self.assertFalse(result['global_equivalence_proven'])
        self.assertTrue(any(r['request']['path'].startswith('/residual/') and r['verdict'] == 'DIFFERENT'
                            for r in result['comparisons']))

    def test_route_order_changes_behavior_without_changing_policy_multiset(self):
        first, second = route('/api/admin/', 'vip'), route('/api/', 'orders')
        result = compare_models(comparison_model([first, second]), comparison_model([second, first]))
        self.assertEqual(result['status'], 'DIFFERENT')

    def test_unreachable_extra_rule_does_not_imply_effective_mismatch(self):
        before = comparison_model([route('/api/', 'orders')])
        after = comparison_model([route('/api/', 'orders'), route('/api/', 'products')])
        self.assertEqual(compare_models(before, after)['status'], 'NO_DIFFERENCE_OBSERVED')

    def test_opaque_predicates_or_ports_remain_unknown(self):
        r = route('/api/', 'orders')
        r['match'][0]['uri'] = {'regex': '/api/.*'}
        model = comparison_model([r])
        self.assertEqual(compare_models(model, model)['status'], 'INCONCLUSIVE')
        self.assertEqual(compare_models(simple_model(), simple_model())['status'], 'INCONCLUSIVE')

    def test_explicit_paoc_and_field_sources_are_retained(self):
        policy = simple_model()['policies'][0]
        self.assertEqual(set(policy['paoc']), {'predicate', 'action', 'scope', 'constraint'})
        self.assertIn('source_pointer', policy)


class RelationalAPITests(unittest.TestCase):
    def test_plan_graph_and_failed_evidence_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = GlobalConfig(validation_output_dir=temporary)
            app = Flask(__name__)
            install_relational_api(app, cfg, 'default')
            client = app.test_client()
            response = client.post('/api/validation/plan', json={'artifact': {'relational_model': simple_model()}})
            self.assertEqual(response.status_code, 200)
            report = response.get_json()['report']
            self.assertEqual(report['plan']['obligations'], 3)
            self.assertEqual(report['status'], 'PLANNED')
            graph = client.get('/api/validation/runs/'+report['run_id']+'/graph')
            self.assertEqual(graph.status_code, 200)
            self.assertEqual(graph.get_json()['schema'], 'configpilot.evidence-dependency-graph/1')
            restarted = Flask(__name__+'-restarted')
            install_relational_api(restarted, cfg, 'default')
            self.assertEqual(restarted.test_client().get('/api/validation/runs/'+report['run_id']+'/report').status_code, 200)
            self.assertEqual(len(client.get('/api/validation/runs').get_json()['runs']), 1)
            plan = json.loads((Path(report['output_dir'])/'probe_plan.json').read_text(encoding='utf-8'))
            evidence = evidence_for(plan)
            evidence['observations'][0]['backend_receipts'][0]['backend_identity'] = 'Service/demo/vip'
            replay = client.post('/api/validation/evaluate', json={'artifact': simple_model(), 'evidence': evidence})
            self.assertEqual(replay.get_json()['report']['status'], 'FAILED')
            self.assertEqual(client.get('/api/validation/capabilities').get_json()['default_engine'], 'relational')

    def test_missing_execution_preconditions_do_not_fall_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Flask(__name__)
            install_relational_api(app, GlobalConfig(validation_output_dir=temporary), 'demo')
            client = app.test_client()
            response = client.post('/api/validation/run', json={'artifact': simple_model()})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()['engine'], 'relational')


@unittest.skipUnless(os.getenv('CONFIGPILOT_TEST_GO_BINARY'), 'optional compiled Go binary not configured')
class GoEngineTests(unittest.TestCase):
    def test_portable_go_backend_preserves_full_plan_and_verdicts(self):
        binary = os.environ['CONFIGPILOT_TEST_GO_BINARY']
        model = simple_model()
        expected = plan_obligations(model)
        for count in (1, 2, 4):
            actual, metrics = build_plan(model, backend='go', workers=count, go_binary=binary)
            self.assertEqual(actual, expected)
            self.assertEqual(metrics['backend'], 'go')


if __name__ == '__main__':
    unittest.main()
