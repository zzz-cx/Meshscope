"""把已采集的 aligned_semantic.json 写成前端可打开的集群报告。"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from consistency_checker.config import get_config
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.storage import get_store
from consistency_checker.visualizer.report_generator import ComprehensiveReportGenerator
from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator
from istio_config_parser.main_parser import load_aligned_semantic


def main() -> None:
    artifact = load_aligned_semantic()
    graph = artifact.get("graph_data") or {}
    namespaces = (graph.get("metadata") or {}).get("namespaces") or []
    app_ns = [n for n in namespaces if n not in {"kube-system", "istio-system", "metallb-system"}]
    namespace = ",".join(app_ns) or (artifact.get("namespace") or "cluster")

    analyzer = StaticAnalyzer.from_artifact(artifact, namespace=None)
    static_result = analyzer._consume_artifact(artifact)
    checker = ConsistencyChecker(
        static_policies=static_result.get("static_policies") or [],
        dynamic_behaviors=[],
        tolerance=get_config().traffic_split_tolerance,
        artifact=artifact,
    )
    result = checker.check()
    generator = ComprehensiveReportGenerator(
        static_result=static_result,
        dynamic_result={"dynamic_behaviors": [], "summary": {}, "statistics": {}},
        consistency_result=result,
        namespace=namespace,
    )
    report = generator.generate()
    report.report_id = "report_cluster_live"
    report.title = "集群实况 · " + (namespace or "all")
    report.timestamp = datetime.now()
    report.executive_summary = (
        "来自集群已采集快照 aligned_semantic.json"
        + (f"（{artifact.get('generated_at')}）" if artifact.get("generated_at") else "")
        + "。当前只含控制面/数据面对齐与跨资源冲突，不含动态测试观测。"
    )
    payload = report.to_dict()
    payload["source"] = "cluster_snapshot"
    payload["generated_at"] = artifact.get("generated_at")

    cfg = get_config()
    store = get_store(cfg.database_path)
    store.save_report(payload)
    store.save_artifact("aligned_semantic", artifact, report_id=report.report_id)

    graph_gen = ThreeLayerGraphGenerator.from_static_result(
        static_result, consistency_result=result, namespace=namespace
    )
    graph_gen.generate()
    store.save_graph(report.report_id, "three_layer", graph_gen.to_d3_json())
    print(
        "saved",
        report.report_id,
        "findings",
        len(payload.get("records") or []),
        "namespace",
        namespace,
    )


if __name__ == "__main__":
    main()
