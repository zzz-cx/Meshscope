"""从对齐模型生成并执行动态验证，供 CLI / Web / 完整流水线共用。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.internal.models.testcase import PipelineResult, TestSuite
from istio_Dynamic_Test.internal.pipeline.guards import (
    DynamicSafetyOptions,
    options_from_config,
)
from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator


def _ssh_from_config(cfg: Any) -> Optional[dict]:
    host = getattr(cfg, "ssh_host", None)
    if not host:
        return None
    return {
        "hostname": host,
        "username": getattr(cfg, "ssh_user", None),
        "password": getattr(cfg, "ssh_password", None),
        "port": getattr(cfg, "ssh_port", None) or 22,
    }


def run_aligned_dynamic_tests(
    namespace: str,
    ingress_url: str = "",
    options: Optional[DynamicSafetyOptions] = None,
    matrix_file: Optional[str] = None,
    prometheus_url: Optional[str] = None,
    jaeger_url: Optional[str] = None,
    zipkin_url: Optional[str] = None,
    ssh_config: Optional[dict] = None,
) -> List[PipelineResult]:
    """生成矩阵、写入 test_matrix_file，再跑 DynamicTester。"""
    from consistency_checker.config import get_config
    from istio_Dynamic_Test.internal.pipeline.cli import DynamicTester
    from istio_Dynamic_Test.internal.traffic.entry import resolve_ingress_base

    cfg = get_config()
    options = options or options_from_config()
    url = resolve_ingress_base(ingress_url or cfg.get_ingress_url() or cfg.ingress_url or "")
    generator = SemanticGenerator(ingress_url=url, namespace=namespace)
    matrix = generator.generate_matrix()
    out_path = matrix_file or cfg.test_matrix_file
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2, ensure_ascii=False)

    suite = TestSuite.from_matrix_file(out_path)
    tester = DynamicTester(
        ssh_config=ssh_config or _ssh_from_config(cfg),
        namespace=namespace,
        prometheus_url=prometheus_url if prometheus_url is not None else cfg.prometheus_url,
        ingress_url=url,
        jaeger_url=jaeger_url if jaeger_url is not None else cfg.jaeger_url,
        zipkin_url=zipkin_url if zipkin_url is not None else getattr(cfg, "zipkin_url", None),
        safety=options,
    )
    return tester.run(suite)
