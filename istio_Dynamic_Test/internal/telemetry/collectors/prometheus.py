"""PrometheusCollector —— 委托 utils.prometheus_utils 统一查询。"""

import json
import os
from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import CollectionResult, TestCase
from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import query_traffic_distribution
from .base import BaseCollector


class PrometheusCollector(BaseCollector):
    """Prometheus 指标采集器（与 CompositeCollector 共用查询逻辑）。"""

    def __init__(
        self,
        prometheus_url: str,
        namespace: str = "default",
        result_dir: str = "results/prometheus",
    ):
        self._prometheus_url = prometheus_url
        self._namespace = namespace
        self._result_dir = result_dir
        os.makedirs(result_dir, exist_ok=True)

    def collect(self, test_case: TestCase) -> CollectionResult:
        svc = test_case.host or test_case.source_service or "unknown"
        metrics = {}
        if test_case.expected_distribution:
            versions = list(test_case.expected_distribution.keys())
            dist = query_traffic_distribution(
                self._prometheus_url, svc, versions, self._namespace
            )
            metrics["traffic_distribution"] = dist
            prefix = f"{test_case.case_id}_{svc}"
            path = os.path.join(self._result_dir, f"{prefix}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dist, f, ensure_ascii=False, indent=2)
        return CollectionResult(
            case_id=test_case.case_id,
            prometheus_metrics=metrics,
        )
