"""写出一份 Bookinfo demo 报告，覆盖三层检验与图展示。"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consistency_checker.config import get_config
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.models.data_models import ConfigEdge, DynamicBehavior, PolicyType, StaticPolicy
from consistency_checker.visualizer.graph_generator import GraphGenerator
from consistency_checker.visualizer.report_generator import ComprehensiveReportGenerator
from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator
from consistency_checker.storage import get_store
from istio_config_parser.main_parser import _expected_tuples_from_pairs, _simple_graph_from_pairs

NS = "default"
REPORT_ID = "report_demo_bookinfo"


def _vs(name: str, hosts: list, http: list, gateways: list | None = None) -> dict:
    spec: dict = {"hosts": hosts, "http": http}
    if gateways:
        spec["gateways"] = gateways
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "VirtualService",
        "metadata": {"name": name, "namespace": NS},
        "spec": spec,
    }


def _dr(name: str, host: str, subsets: list) -> dict:
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "DestinationRule",
        "metadata": {"name": name, "namespace": NS},
        "spec": {
            "host": host,
            "subsets": [{"name": s, "labels": {"version": s}} for s in subsets],
            "trafficPolicy": {
                "connectionPool": {"tcp": {"maxConnections": 100}},
                "outlierDetection": {"consecutive5xxErrors": 5, "interval": "10s"},
            },
        },
    }


def _gw(name: str, selector: dict | None) -> dict:
    spec: dict = {"servers": [{"port": {"number": 80, "name": "http", "protocol": "HTTP"}, "hosts": ["*"]}]}
    if selector is not None:
        spec["selector"] = selector
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "Gateway",
        "metadata": {"name": name, "namespace": NS},
        "spec": spec,
    }


def _svc(name: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": NS},
        "spec": {"ports": [{"port": 9080, "name": "http"}]},
    }


def _tuple(tid: str, ftype: str, plane: str, svc: str, predicate: dict, action: dict, constraint: dict, subsets: list) -> dict:
    return {
        "tuple_id": tid,
        "function_type": ftype,
        "plane": plane,
        "predicate": predicate,
        "action": action,
        "scope": {"namespace": NS, "service": svc, "subsets": subsets},
        "constraint": constraint,
        "source_resources": [],
    }


def _pair(ftype: str, svc: str, status: str, diffs: list, cp: dict | None, dp: dict | None, raw: dict | None = None) -> dict:
    item = {
        "function_type": ftype,
        "service_name": svc,
        "namespace": NS,
        "alignment_status": status,
        "differences": diffs,
        "control_tuples": [cp] if cp else [],
        "data_tuples": [dp] if dp else [],
        "control_plane": {"raw_config": raw} if raw else None,
        "data_plane": {
            "raw_config": {
                "cluster": f"outbound|{svc}",
                "routes": (dp or {}).get("constraint", {}).get("destinations"),
                "timeout": (dp or {}).get("constraint", {}).get("timeout"),
            }
        } if dp else None,
    }
    return item


def build_artifact() -> dict:
    vs_productpage = _vs(
        "bookinfo",
        ["*"],
        [{"match": [{"uri": {"prefix": "/productpage"}}], "route": [{"destination": {"host": "productpage", "port": {"number": 9080}}}]}],
        gateways=["bookinfo-gateway", "missing-gateway"],
    )
    vs_reviews = _vs(
        "reviews",
        ["reviews"],
        [
            {
                "match": [{"uri": {"prefix": "/"}}],
                "route": [
                    {"destination": {"host": "reviews", "subset": "v1"}, "weight": 80},
                    {"destination": {"host": "reviews", "subset": "v2"}, "weight": 20},
                ],
                "retries": {"attempts": 3, "retryOn": "5xx"},
                "timeout": "2s",
            },
            {
                "match": [{"uri": {"prefix": "/"}}],
                "route": [{"destination": {"host": "reviews", "subset": "v3"}, "weight": 100}],
            },
        ],
    )
    vs_ratings = _vs(
        "ratings",
        ["ratings"],
        [{"route": [{"destination": {"host": "ratings", "subset": "v1"}}], "timeout": "1s"}],
    )
    dr_reviews = _dr("reviews", "reviews", ["v1", "v2"])
    dr_ratings = _dr("ratings", "ratings", ["v1"])
    gw_bookinfo = _gw("bookinfo-gateway", {"istio": "ingressgateway"})
    gw_dup = _gw("frontend-gateway", {"istio": "ingressgateway"})
    gw_empty = _gw("empty-selector-gateway", None)
    ef = {
        "apiVersion": "networking.istio.io/v1alpha3",
        "kind": "EnvoyFilter",
        "metadata": {"name": "productpage-ratelimit", "namespace": NS},
        "spec": {"workloadSelector": {"labels": {"app": "productpage"}}},
    }

    configs = {
        "virtual_services": [vs_productpage, vs_reviews, vs_ratings],
        "destination_rules": [dr_reviews, dr_ratings],
        "gateways": [gw_bookinfo, gw_dup, gw_empty],
        "envoy_filters": [ef],
        "services": [_svc(n) for n in ("productpage", "reviews", "ratings", "details")],
    }

    pairs = [
        _pair(
            "routing", "productpage", "matched", [],
            _tuple("default.productpage.routing.0", "routing", "control_plane", "productpage",
                   {"uri": {"prefix": "/productpage"}}, {"type": "route"},
                   {"destinations": [{"host": "productpage", "weight": 100}]}, []),
            _tuple("default.productpage.routing.0", "routing", "data_plane", "productpage",
                   {"uri": {"prefix": "/productpage"}}, {"type": "route"},
                   {"destinations": [{"host": "productpage", "weight": 100}]}, []),
            vs_productpage,
        ),
        _pair(
            "routing", "reviews", "mismatched",
            [{"kind": "discrete", "description": "reviews 路由权重与数据面不一致：声明 v1 80% / v2 20%，Envoy 为 50% / 50%",
              "control": {"v1": 80, "v2": 20}, "data": {"v1": 50, "v2": 50}}],
            _tuple("default.reviews.routing.0", "routing", "control_plane", "reviews",
                   {"uri": {"prefix": "/"}}, {"type": "route"},
                   {"destinations": [
                       {"host": "reviews", "subset": "v1", "weight": 80},
                       {"host": "reviews", "subset": "v2", "weight": 20},
                   ], "weights": {"v1": 80, "v2": 20}}, ["v1", "v2"]),
            _tuple("default.reviews.routing.0", "routing", "data_plane", "reviews",
                   {"uri": {"prefix": "/"}}, {"type": "route"},
                   {"destinations": [
                       {"host": "reviews", "subset": "v1", "weight": 50},
                       {"host": "reviews", "subset": "v2", "weight": 50},
                   ], "weights": {"v1": 50, "v2": 50}}, ["v1", "v2"]),
            vs_reviews,
        ),
        _pair(
            "traffic_shifting", "reviews", "partial_matched",
            [{"kind": "numeric", "description": "reviews 流量分割部分匹配：v2 权重偏差 10%，仍超出容差 τ=0.1 的边缘",
              "control": {"v1": 90, "v2": 10}, "data": {"v1": 80, "v2": 20}}],
            _tuple("default.reviews.traffic_shifting", "traffic_shifting", "control_plane", "reviews",
                   {}, {"type": "traffic_shifting"},
                   {"weights": {"v1": 90, "v2": 10}}, ["v1", "v2"]),
            _tuple("default.reviews.traffic_shifting", "traffic_shifting", "data_plane", "reviews",
                   {}, {"type": "traffic_shifting"},
                   {"weights": {"v1": 80, "v2": 20}}, ["v1", "v2"]),
            dr_reviews,
        ),
        _pair(
            "timeout", "ratings", "mismatched",
            [{"kind": "timeout", "description": "ratings 超时不一致：VirtualService timeout=1s，Envoy route timeout=5s",
              "control": "1s", "data": "5s"}],
            _tuple("default.ratings.timeout", "timeout", "control_plane", "ratings",
                   {}, {"type": "timeout"}, {"timeout": "1s", "timeout_seconds": 1}, ["v1"]),
            _tuple("default.ratings.timeout", "timeout", "data_plane", "ratings",
                   {}, {"type": "timeout"}, {"timeout": "5s", "timeout_seconds": 5}, ["v1"]),
            vs_ratings,
        ),
        _pair(
            "retry", "details", "control_only",
            [{"kind": "missing", "description": "details 声明了重试策略，sidecar dump 中没有对应 retry_policy"}],
            _tuple("default.details.retry", "retry", "control_plane", "details",
                   {}, {"type": "retry"}, {"attempts": 3, "retry_on": "5xx"}, []),
            None,
            _vs("details", ["details"], [{"retries": {"attempts": 3, "retryOn": "5xx"}, "route": [{"destination": {"host": "details"}}]}]),
        ),
        _pair(
            "fault_injection", "productpage", "data_only",
            [{"kind": "missing", "description": "productpage Envoy 存在 abort 故障注入，控制面 YAML 未声明"}],
            None,
            _tuple("default.productpage.fault", "fault_injection", "data_plane", "productpage",
                   {"uri": {"prefix": "/productpage"}}, {"type": "abort"},
                   {"abort_percent": 10, "http_status": 503}, []),
        ),
        _pair(
            "circuit_breaker", "ratings", "mismatched",
            [{"kind": "discrete", "description": "ratings 熔断阈值不一致：声明 consecutive5xx=5，数据面为 2",
              "control": 5, "data": 2}],
            _tuple("default.ratings.cb", "circuit_breaker", "control_plane", "ratings",
                   {}, {"type": "circuit_breaker"},
                   {"consecutive_errors": 5, "max_connections": 100}, ["v1"]),
            _tuple("default.ratings.cb", "circuit_breaker", "data_plane", "ratings",
                   {}, {"type": "circuit_breaker"},
                   {"consecutive_errors": 2, "max_connections": 100}, ["v1"]),
            dr_ratings,
        ),
        _pair(
            "rate_limit", "productpage", "control_only",
            [{"kind": "missing", "description": "productpage EnvoyFilter 限流已声明，数据面未看到 local_ratelimit 过滤器"}],
            _tuple("default.productpage.rl", "rate_limit", "control_plane", "productpage",
                   {}, {"type": "rate_limit"}, {"requests_per_unit": 10, "unit": "second"}, []),
            None,
            ef,
        ),
        _pair(
            "routing", "ratings", "matched", [],
            _tuple("default.ratings.routing.0", "routing", "control_plane", "ratings",
                   {}, {"type": "route"},
                   {"destinations": [{"host": "ratings", "subset": "v1", "weight": 100}]}, ["v1"]),
            _tuple("default.ratings.routing.0", "routing", "data_plane", "ratings",
                   {}, {"type": "route"},
                   {"destinations": [{"host": "ratings", "subset": "v1", "weight": 100}]}, ["v1"]),
            vs_ratings,
        ),
    ]

    conflicts = [
        {
            "type": "missing_subset",
            "severity": "high",
            "virtualservice": "reviews",
            "namespace": NS,
            "service": "reviews",
            "missing_subset": "v3",
            "available_subsets": ["v1", "v2"],
            "description": "VirtualService 'reviews' 引用 subset 'v3'，但 DestinationRule 中 reviews 只定义了 ['v1', 'v2']",
        },
        {
            "type": "gateway_unmatched",
            "severity": "high",
            "virtualservice": "bookinfo",
            "namespace": NS,
            "gateway": "missing-gateway",
            "description": "VirtualService 'bookinfo' 绑定 Gateway 'missing-gateway'，但未找到对应 Gateway 资源",
        },
        {
            "type": "gateway_selector_empty",
            "severity": "medium",
            "gateway": "empty-selector-gateway",
            "namespace": NS,
            "description": "Gateway 'empty-selector-gateway' 未设置 selector，无法绑定到 ingress/gateway workload",
        },
        {
            "type": "gateway_selector_conflict",
            "severity": "high",
            "gateways": ["default/bookinfo-gateway", "default/frontend-gateway"],
            "selector": {"istio": "ingressgateway"},
            "description": "多个 Gateway ['default/bookinfo-gateway', 'default/frontend-gateway'] 使用相同 selector {'istio': 'ingressgateway'}，入口选择器冲突",
        },
        {
            "type": "route_priority_conflict",
            "severity": "high",
            "virtualservice": "reviews",
            "namespace": NS,
            "rules": [0, 1],
            "description": "VirtualService 'reviews' 第 0 与第 1 条 HTTP 规则匹配条件相同，优先级冲突",
        },
    ]

    graph_data = _simple_graph_from_pairs(pairs, configs)
    expected = _expected_tuples_from_pairs(pairs)

    service_relations = {
        "productpage": {
            "incomingVirtualServices": [{"name": "bookinfo", "rules": vs_productpage["spec"]["http"]}],
            "subsets": [],
            "rateLimit": [{"requests_per_unit": 10, "unit": "second"}],
            "gateways": ["bookinfo-gateway"],
            "weights": {},
        },
        "reviews": {
            "incomingVirtualServices": [{"name": "reviews", "rules": vs_reviews["spec"]["http"]}],
            "subsets": [{"name": "v1"}, {"name": "v2"}],
            "rateLimit": [],
            "gateways": [],
            "weights": {"v1": {"weight": 80}, "v2": {"weight": 20}},
        },
        "ratings": {
            "incomingVirtualServices": [{"name": "ratings", "rules": vs_ratings["spec"]["http"]}],
            "subsets": [{"name": "v1"}],
            "rateLimit": [],
            "gateways": [],
            "weights": {"v1": {"weight": 100}},
            "circuitBreaker": {"consecutive5xxErrors": 5},
        },
        "details": {
            "incomingVirtualServices": [{"name": "details", "rules": []}],
            "subsets": [],
            "rateLimit": [],
            "gateways": [],
            "weights": {},
        },
    }
    dp_relations = {
        name: {"inbound": [], "outbound": [], "weights": rel.get("weights") or {}}
        for name, rel in service_relations.items()
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "namespace": NS,
        "tau": 0.1,
        "demo": True,
        "summary": {
            "total_services": 4,
            "total_functions": len(pairs),
            "aligned_pair_count": sum(1 for p in pairs if p["alignment_status"] in ("matched", "partial_matched")),
            "conflict_count": len(conflicts),
            "expected_tuple_count": len(expected),
            "tau": 0.1,
        },
        "pairs": pairs,
        "conflicts": conflicts,
        "expected_tuples": expected,
        "control_plane": {"serviceRelations": service_relations},
        "data_plane": {"serviceRelations": dp_relations},
        "graph_data": graph_data,
        "control_plane_configs": configs,
    }


def build_policies() -> list:
    return [
        StaticPolicy(
            policy_id="policy_0001",
            policy_type=PolicyType.TRAFFIC_SPLIT,
            source_service="productpage",
            target_service="reviews",
            namespace=NS,
            config_name="reviews-split-primary",
            config_type="VirtualService",
            rules={"predicate": {"uri": {"prefix": "/"}}, "action": {"type": "traffic_shifting"},
                   "constraint": {"weights": {"v1": 80, "v2": 20}}},
            applies_to=["v1", "v2", "v3"],
        ),
        StaticPolicy(
            policy_id="policy_0002",
            policy_type=PolicyType.TRAFFIC_SPLIT,
            source_service="productpage",
            target_service="reviews",
            namespace=NS,
            config_name="reviews-split-canary",
            config_type="DestinationRule",
            rules={"action": {"type": "traffic_shifting"}, "constraint": {"weights": {"v1": 90, "v2": 10}}},
            applies_to=["v1", "v2"],
        ),
        StaticPolicy(
            policy_id="policy_0003",
            policy_type=PolicyType.TIMEOUT,
            source_service="reviews",
            target_service="ratings",
            namespace=NS,
            config_name="ratings-timeout",
            config_type="VirtualService",
            rules={"action": {"type": "timeout"}, "constraint": {"timeout": "1s"}},
            applies_to=["v1"],
        ),
        StaticPolicy(
            policy_id="policy_0004",
            policy_type=PolicyType.CIRCUIT_BREAKER,
            source_service="reviews",
            target_service="ratings",
            namespace=NS,
            config_name="ratings-cb",
            config_type="DestinationRule",
            rules={"action": {"type": "circuit_breaker"}, "constraint": {"consecutive_errors": 5}},
            applies_to=["v1"],
        ),
        StaticPolicy(
            policy_id="policy_0005",
            policy_type=PolicyType.ROUTING,
            source_service="productpage",
            target_service="reviews",
            namespace=NS,
            config_name="reviews",
            config_type="VirtualService",
            rules={"predicate": {"uri": {"prefix": "/"}}, "action": {"type": "route"}},
            applies_to=["v1", "v2"],
        ),
    ]


def build_behaviors() -> list:
    return [
        DynamicBehavior(
            test_case_id="case_001",
            policy_type=PolicyType.TRAFFIC_SPLIT,
            source_service="productpage",
            target_service="reviews",
            test_params={"path": "/reviews/1", "subset": "v1"},
            expected_behavior={"weights": {"v1": 80, "v2": 20}},
            actual_behavior={"weights": {"v1": 51, "v2": 49}},
            is_verified=False,
            verification_details={"overall_result": {"passed": False}, "dimension_checks": {"weight": {"passed": False}}},
        ),
        DynamicBehavior(
            test_case_id="case_002",
            policy_type=PolicyType.ROUTING,
            source_service="productpage",
            target_service="reviews",
            test_params={"path": "/reviews/1", "header": "end-user=jason", "subset": "v2"},
            expected_behavior={"destination": "reviews/v2"},
            actual_behavior={"destination": "reviews/v1"},
            is_verified=False,
            verification_details={"overall_result": {"passed": False}, "dimension_checks": {"route": {"passed": False}}},
        ),
        DynamicBehavior(
            test_case_id="case_003",
            policy_type=PolicyType.CIRCUIT_BREAKER,
            source_service="reviews",
            target_service="ratings",
            test_params={"fault": "5xx"},
            expected_behavior={"open_after": 5},
            actual_behavior={"open_after": 2, "ejected": True},
            is_verified=False,
            verification_details={"overall_result": {"passed": False}, "dimension_checks": {"outlier": {"passed": False}}},
        ),
        DynamicBehavior(
            test_case_id="case_004",
            policy_type=PolicyType.ROUTING,
            source_service="*",
            target_service="productpage",
            test_params={"path": "/productpage"},
            expected_behavior={"status": 200},
            actual_behavior={"status": 200},
            is_verified=True,
            verification_details={"overall_result": {"passed": True}},
        ),
    ]


def wipe_old(config) -> None:
    cons = Path(config.consistency_output_dir)
    vis = Path(config.visualization_output_dir)
    kept = {"aligned_semantic.json"}
    if cons.exists():
        for path in cons.iterdir():
            if path.name in kept:
                continue
            if path.suffix == ".json":
                path.unlink()
                print("deleted", path)
    if vis.exists():
        for path in vis.iterdir():
            if path.suffix in {".json", ".html"}:
                path.unlink()
                print("deleted", path)


def main() -> None:
    os.chdir(ROOT)
    config = get_config()
    wipe_old(config)

    artifact = build_artifact()
    aligned_path = os.path.join(config.consistency_output_dir, "aligned_semantic.json")
    os.makedirs(config.consistency_output_dir, exist_ok=True)
    with open(aligned_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)
    print("wrote", aligned_path)

    analyzer = StaticAnalyzer.from_artifact(artifact, namespace=NS)
    static_result = analyzer._consume_artifact(artifact)
    static_result["plane_consistency_issues"] = list(static_result.get("plane_consistency_issues") or []) + [{
        "type": "traffic_split_drift",
        "service": "reviews",
        "expected": {"v1": 80, "v2": 20},
        "observed": {"v1": 51, "v2": 49},
        "description": "reviews 流量分割漂移：期望 80/20，观测 51/49",
    }]
    static_result["static_policies"] = build_policies()
    extra_edges = [
        ConfigEdge(edge_id="edge_gw", source="istio-gateway", target="productpage", edge_type="gateway", label="Gateway"),
        ConfigEdge(edge_id="edge_pp_reviews", source="productpage", target="reviews", edge_type="route", weight=100, label="Route"),
        ConfigEdge(edge_id="edge_reviews_ratings", source="reviews", target="ratings", edge_type="route", weight=100, label="Route"),
        ConfigEdge(edge_id="edge_reviews_details", source="reviews", target="details", edge_type="route", weight=100, label="Route"),
    ]
    existing = {(e.source, e.target, e.edge_type) for e in static_result.get("config_edges") or []}
    for edge in extra_edges:
        if (edge.source, edge.target, edge.edge_type) not in existing:
            static_result["config_edges"].append(edge)

    behaviors = build_behaviors()
    checker = ConsistencyChecker(
        static_policies=static_result["static_policies"],
        dynamic_behaviors=behaviors,
        tolerance=0.1,
        artifact=artifact,
    )
    consistency = checker.check()

    gen = ComprehensiveReportGenerator(
        static_result=static_result,
        dynamic_result={
            "dynamic_behaviors": behaviors,
            "summary": {"total_tests": 4, "verified_tests": 1, "failed_tests": 3},
            "statistics": {"verification_rate": 0.25, "by_policy_type": {
                "traffic_split": {"total": 1, "verified": 0, "failed": 1},
                "routing": {"total": 2, "verified": 1, "failed": 1},
                "circuit_breaker": {"total": 1, "verified": 0, "failed": 1},
            }},
        },
        consistency_result=consistency,
        namespace=NS,
    )
    report = gen.generate()
    report.report_id = REPORT_ID
    report.title = "Bookinfo Demo · 三层一致性检验展示"
    report.executed_by = "demo"
    gen._report = report

    os.makedirs(config.visualization_output_dir, exist_ok=True)
    json_path = os.path.join(config.consistency_output_dir, f"{REPORT_ID}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False, default=str)

    html_path = os.path.join(config.visualization_output_dir, f"{REPORT_ID}_report.html")
    gen.generate_html_report(html_path)

    graph_gen = GraphGenerator(
        service_nodes=static_result["service_nodes"],
        config_edges=static_result["config_edges"],
        consistency_result=consistency,
    )
    graph_gen.generate()
    graph_gen.save_to_file(os.path.join(config.visualization_output_dir, f"{REPORT_ID}_graph.json"))

    three = ThreeLayerGraphGenerator.from_static_result(
        static_result, consistency_result=consistency, namespace=NS
    )
    three.generate()
    three_path = os.path.join(config.visualization_output_dir, f"{REPORT_ID}_three_layer_graph.json")
    three.save_to_file(three_path)
    shutil.copyfile(three_path, os.path.join(config.visualization_output_dir, "aligned_three_layer_graph.json"))

    store = get_store(config.database_path)
    payload = report.to_dict()
    store.save_report(payload, html_path=html_path)
    store.save_graph(REPORT_ID, "topology", graph_gen.get_graph_data())
    three_json = three.to_d3_json()
    store.save_graph(REPORT_ID, "three_layer", three_json)
    store.save_graph("latest", "three_layer", three_json)
    store.save_artifact("aligned_semantic", artifact)
    print("sqlite", config.database_path, store.stats())

    records = report.to_dict()["records"]
    print("report", REPORT_ID, "records", len(records))
    print("by layer", report.consistency_check.summary.get("by_layer"))
    print("types", sorted({r["inconsistency_type"] for r in records}))
    print("html", html_path)
    print("json", json_path)


if __name__ == "__main__":
    main()
