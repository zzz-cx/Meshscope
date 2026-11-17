"""Behavioral tests for reference semantics, coverage and evidence boundaries."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from istio_config_parser.models.relational_model import build_relational_model, dependency_slice, digest, service_ref
from istio_Dynamic_Test.internal.planning.relational import (
    EVIDENCE_SCHEMA, evaluate_obligations, plan_obligations, select_rule,
)
from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator


def config(routes):
    return {"virtual_services": [{"apiVersion": "networking.istio.io/v1beta1", "kind": "VirtualService",
        "metadata": {"name": "shop", "namespace": "demo"},
        "spec": {"hosts": ["shop.example.com"], "gateways": ["demo/gateway"], "http": routes}}],
        "services": [{"kind": "Service", "metadata": {"name": name, "namespace": "demo"}, "spec": {}}
                     for name in ("orders", "products", "vip")],
        "gateways": [{"kind": "Gateway", "metadata": {"name": "gateway", "namespace": "demo"}, "spec": {}}]}


def route(path, destination, headers=None):
    result = {"match": [{"uri": {"prefix": path}}], "route": [{"destination": {"host": destination}}]}
    if headers:
        result["headers"] = {"request": {"set": headers}}
    return result


def simple_model():
    return build_relational_model(config([route("/orders/", "orders", {"x-source": "shop"}), route("/products/", "products")]))


def evidence_for(plan):
    probes = {p["id"]: p for p in plan["candidate_probes"]}
    evidence = {"schema": EVIDENCE_SCHEMA, "reference_model_hash": plan["reference_model_hash"], "run_id": "test-run", "observations": []}
    for pid in plan["selected_probe_ids"]:
        probe = probes[pid]
        destination = "orders" if probe["request"]["path"].startswith("/orders/") else "products"
        rid = "test-run:"+pid
        evidence["observations"].append({"probe_id": pid, "probe_hash": probe["probe_hash"],
            "reference_model_hash": plan["reference_model_hash"], "run_id": "test-run",
            "activation_confirmed": True, "execution_id": pid, "request_id": rid,
            "sent_request": copy.deepcopy(probe["request"]), "started_at": 1.0, "completed_at": 2.0,
            "backend_receipts": [{"event_id": rid, "source_kind": "backend_receipt", "observed_at": 1.5,
                "request_id": rid, "backend_identity": "Service/demo/"+destination,
                "request_headers": {"x-source": "shop"} if destination == "orders" else {}, "headers_complete": True}]})
    return evidence


class RelationalPlanningTests(unittest.TestCase):
    def test_same_probe_reuses_route_and_header_but_not_other_path(self):
        model = simple_model()
        before, after = plan_obligations(model, reuse=False), plan_obligations(model)
        self.assertEqual(len(before["obligations"]), 3)
        self.assertEqual(before["summary"]["selected_probes"], 3)
        self.assertEqual(after["summary"]["selected_probes"], 2)
        self.assertEqual(evaluate_obligations(after, evidence_for(after))["summary"], {"PASS": 3, "FAIL": 0, "INCONCLUSIVE": 0})
        pids = {p["id"]: p for p in after["candidate_probes"]}
        for d in after["coverage_decisions"]:
            if d["W"] and "/products/" in pids[d["probe_id"]]["request"]["path"]:
                self.assertNotIn("http/0", d["obligation_id"])

    def test_target_counterevidence_is_failure_not_untriggered(self):
        plan = plan_obligations(simple_model())
        evidence = evidence_for(plan)
        for observation in evidence["observations"]:
            if observation["sent_request"]["path"].startswith("/orders/"):
                observation["backend_receipts"][0]["backend_identity"] = "Service/demo/products"
        results = evaluate_obligations(plan, evidence)
        self.assertEqual(results["summary"], {"PASS": 1, "FAIL": 1, "INCONCLUSIVE": 1})

    def test_missing_header_is_failure_and_missing_evidence_is_inconclusive(self):
        plan = plan_obligations(simple_model())
        evidence = evidence_for(plan)
        for observation in evidence["observations"]:
            observation["backend_receipts"][0]["request_headers"] = {}
        self.assertEqual(evaluate_obligations(plan, evidence)["summary"]["FAIL"], 1)
        evidence["observations"] = []
        self.assertEqual(evaluate_obligations(plan, evidence)["summary"]["INCONCLUSIVE"], 3)

    def test_stale_uncorrelated_and_wrong_probe_evidence_never_pass(self):
        plan = plan_obligations(simple_model())
        for mutation in ("stale", "uncorrelated", "probe", "request", "run"):
            evidence = evidence_for(plan)
            for observation in evidence["observations"]:
                if mutation == "stale":
                    observation["backend_receipts"][0]["observed_at"] = 0.0
                elif mutation == "uncorrelated":
                    observation["backend_receipts"][0]["request_id"] = "other"
                elif mutation == "probe":
                    observation["probe_hash"] = "other"
                elif mutation == "request":
                    observation["sent_request"]["path"] = "/other"
                else:
                    observation["run_id"] = "other"
            self.assertEqual(evaluate_obligations(plan, evidence)["summary"]["PASS"], 0)

    def test_slices_include_all_preceding_rules_and_coapplying_budget(self):
        raw = config([route("/admin/", "vip"), route("/", "orders")])
        raw["virtual_services"][0]["spec"]["http"][1].update({"retries": {"attempts": 2}, "timeout": "200ms"})
        model = build_relational_model(raw)
        retry = next(p for p in model["policies"] if p["kind"] == "retry")
        section = dependency_slice(model, retry["id"])
        self.assertIn(model["rules"][0]["id"], section["nodes"])
        self.assertTrue(any(n.endswith("/timeout") for n in section["nodes"]))
        self.assertTrue(any(n.startswith("Service/demo/") for n in section["nodes"]))

    def test_later_rule_witness_avoids_earlier_header_match(self):
        first = route("/orders/", "vip")
        first["match"][0]["headers"] = {"x-user": {"exact": "alice"}}
        model = build_relational_model(config([first, route("/orders/", "orders")]))
        plan = plan_obligations(model)
        later = model["rules"][1]
        candidates = [p for p in plan["candidate_probes"] if p["selected_rule"] == later["id"]]
        self.assertTrue(candidates)
        for probe in candidates:
            self.assertNotEqual(probe["request"]["headers"].get("x-user"), "alice")

    def test_shadowed_rule_is_retained_and_order_relation_has_probe(self):
        model = build_relational_model(config([route("/s0/", "orders"), route("/s0/vip/", "vip")]))
        plan = plan_obligations(model)
        later = model["rules"][1]["id"]
        obligation = next(o for o in plan["obligations"] if o["rule_id"] == later and o["H"]["kind"] == "destination")
        self.assertTrue(obligation["unplanned_reason"])
        self.assertTrue(any(o["H"]["kind"] == "ordered_selection" and not o["unplanned_reason"] for o in plan["obligations"]))

    def test_unknown_predicate_never_licenses_later_selection(self):
        first = route("/", "vip")
        first["match"][0]["uri"] = {"regex": "/admin/.*"}
        plan = plan_obligations(build_relational_model(config([first, route("/orders/", "orders")])))
        self.assertEqual(plan["selected_probe_ids"], [])
        self.assertGreaterEqual(plan["summary"]["unplanned_obligations"], 2)

    def test_six_distinct_routes_are_not_reduced_by_policy_label(self):
        routes = [route("/r%d/" % i, "orders" if i % 2 else "products") for i in range(6)]
        plan = plan_obligations(build_relational_model(config(routes)))
        self.assertEqual(plan["summary"]["obligations"], 6)
        self.assertEqual(plan["summary"]["selected_probes"], 6)

    def test_unknown_budget_relation_and_directives_remain_obligations(self):
        raw = config([route("/orders/", "orders")])
        raw["virtual_services"][0]["spec"]["http"][0].update({"retries": {"attempts": 2}, "timeout": "200ms", "unrecognizedField": {"enabled": True}})
        plan = plan_obligations(build_relational_model(raw))
        kinds = {o["H"]["kind"] for o in plan["obligations"]}
        self.assertTrue({"retry", "timeout", "shared_time_budget", "opaque:unrecognizedField"} <= kinds)
        self.assertEqual(plan["selected_probe_ids"], [])
        empty = {"schema": EVIDENCE_SCHEMA, "reference_model_hash": plan["reference_model_hash"], "run_id": "empty", "observations": []}
        self.assertEqual(evaluate_obligations(plan, empty)["summary"]["INCONCLUSIVE"], len(plan["obligations"]))

    def test_third_unknown_policy_invalidates_otherwise_valid_reuse(self):
        raw = config([route("/orders/", "orders", {"x-source": "shop"}), route("/products/", "products")])
        baseline = plan_obligations(build_relational_model(raw))
        self.assertEqual(baseline["summary"]["unplanned_obligations"], 0)
        raw["virtual_services"][0]["spec"]["http"][0]["mirror"] = {"host": "vip"}
        plan = plan_obligations(build_relational_model(raw))
        orders = [o for o in plan["obligations"] if "http/0" in (o["rule_id"] or "")]
        self.assertEqual(len(orders), 3)
        self.assertTrue(all(o["unplanned_reason"] for o in orders))
        self.assertEqual(plan["summary"]["selected_probes"], 1)

    def test_authority_and_transport_headers_do_not_use_ordinary_header_rule(self):
        for header in ("Host", "Content-Length", ":authority"):
            raw = config([route("/orders/", "orders", {header: "other"})])
            plan = plan_obligations(build_relational_model(raw))
            self.assertEqual(plan["selected_probe_ids"], [])
            raw = config([route("/orders/", "orders")])
            raw["virtual_services"][0]["spec"]["http"][0]["match"][0]["headers"] = {header: {"exact": "other"}}
            self.assertEqual(plan_obligations(build_relational_model(raw))["selected_probe_ids"], [])

    def test_cross_virtualservice_ambiguity_and_unresolved_refs_are_unknown(self):
        raw = config([route("/orders/", "orders")])
        other = copy.deepcopy(raw["virtual_services"][0])
        other["metadata"]["name"] = "other"
        raw["virtual_services"].append(other)
        plan = plan_obligations(build_relational_model(raw))
        self.assertEqual(plan["selected_probe_ids"], [])
        raw["virtual_services"].pop()
        raw["services"] = []
        self.assertEqual(plan_obligations(build_relational_model(raw))["selected_probe_ids"], [])

    def test_reference_model_hash_and_identity_are_preserved(self):
        model = simple_model()
        mutated = copy.deepcopy(model)
        mutated["rules"][0]["raw"]["route"][0]["destination"]["host"] = "vip"
        with self.assertRaises(ValueError):
            plan_obligations(mutated)
        self.assertEqual(service_ref("orders.other.svc.cluster.local", "demo"), "Service/other/orders")
        self.assertEqual(service_ref("api.example.com", "demo"), "ExternalHost/api.example.com")
        with self.assertRaises(ValueError):
            raw = config([])
            raw["services"].append(copy.deepcopy(raw["services"][0]))
            build_relational_model(raw)

    def test_kubernetes_list_and_gateway_alias_have_canonical_identity(self):
        raw = config([route("/orders/", "orders")])
        raw["services"] = {"kind": "List", "metadata": {"resourceVersion": ""}, "items": raw["services"]}
        raw["virtual_services"][0]["spec"]["gateways"] = ["gateway"]
        model = build_relational_model(raw)
        self.assertEqual(model["rules"][0]["gateways"], ["demo/gateway"])
        self.assertEqual(plan_obligations(model)["summary"]["selected_probes"], 1)
        self.assertIn("four_dimensions", model["policies"][0])

    def test_witness_search_is_bounded_and_cannot_drop_obligations(self):
        raw = config([route("/orders/", "orders")])
        raw["virtual_services"][0]["spec"]["http"][0]["match"][0]["headers"] = {
            "header-%d" % i: {"exact": "value"} for i in range(30)}
        model = build_relational_model(raw)
        plan = plan_obligations(model)
        self.assertEqual(plan["summary"]["obligations"], 1)
        self.assertEqual(plan["summary"]["unplanned_obligations"], 0)
        from istio_Dynamic_Test.internal.planning.relational import witness_requests
        self.assertEqual(list(witness_requests(model, model['rules'][0], limit=0)), [])
        with patch('istio_Dynamic_Test.internal.planning.relational.witness_requests',
                   side_effect=lambda m, r: witness_requests(m, r, limit=0)):
            exhausted = plan_obligations(model)
        self.assertEqual(exhausted['summary']['obligations'], 1)
        self.assertEqual(exhausted['summary']['unplanned_obligations'], 1)

    def test_same_backend_event_cannot_be_reassigned_to_other_execution(self):
        plan = plan_obligations(simple_model())
        evidence = evidence_for(plan)
        shared = evidence["observations"][0]["backend_receipts"][0]["event_id"]
        for observation in evidence["observations"]:
            observation["backend_receipts"][0]["event_id"] = shared
        self.assertEqual(evaluate_obligations(plan, evidence)["summary"]["PASS"], 0)

    def test_semantic_entry_requires_explicit_model_and_preserves_legacy(self):
        generator = SemanticGenerator(artifact={"relational_model": simple_model()})
        self.assertEqual(generator.generate_obligation_plan()["summary"]["obligations"], 3)
        with self.assertRaises(FileNotFoundError):
            SemanticGenerator(artifact={"expected_tuples": []}).generate_obligation_plan()

    def test_static_export_embeds_model_even_without_matched_tuples(self):
        from istio_config_parser.main_parser import parse_static_semantic
        class EmptyIR:
            def get_all_services(self):
                return []
            def get_summary(self):
                return {}
        with tempfile.TemporaryDirectory() as directory, \
                patch("istio_config_parser.main_parser.parse_unified_from_dir", return_value=(EmptyIR(), config([route("/orders/", "orders")]))), \
                patch("istio_config_parser.main_parser.system_ir_to_legacy", return_value=({}, {})):
            result = parse_static_semantic(output_path=str(Path(directory)/"aligned.json"))
            artifact = result["artifact"]
            self.assertEqual(artifact["expected_tuples"], [])
            self.assertEqual(len(artifact["relational_model"]["rules"]), 1)
            self.assertEqual(SemanticGenerator(artifact=artifact).generate_obligation_plan()["summary"]["obligations"], 1)

    def test_real_static_parser_retains_cross_namespace_reference_context(self):
        import yaml
        from istio_config_parser.main_parser import parse_static_semantic
        raw = config([route("/orders/", "orders", {"x-source": "shop"}), route("/products/", "products")])
        raw["virtual_services"][0]["spec"]["gateways"] = ["shared/gateway"]
        raw["gateways"][0]["metadata"]["namespace"] = "shared"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for key, folder in [("virtual_services", "virtualservices"), ("services", "services"), ("gateways", "gateways")]:
                for doc in raw[key]:
                    meta = doc["metadata"]
                    path = base/"control"/folder/meta["namespace"]/(meta["name"]+".yaml")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
            (base/"data").mkdir()
            result = parse_static_semantic(control_plane_dir=str(base/"control"), data_plane_dir=str(base/"data"),
                namespace="demo", enable_parallel=False, output_path=str(base/"aligned.json"))
            artifact = result["artifact"]
            model = artifact["relational_model"]
            self.assertTrue(any(r["id"] == "Gateway/shared/gateway" for r in model["resources"]))
            plan = SemanticGenerator(artifact=artifact).generate_obligation_plan()
            self.assertEqual(plan["target_namespace"], "demo")
            self.assertEqual(plan["summary"]["selected_probes"], 2)


if __name__ == "__main__":
    unittest.main()
