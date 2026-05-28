"""CompositeCollector —— 根据用例类型选择 Envoy 日志或 Prometheus 采集。

- traffic_split: 使用 Prometheus 指标验证流量分布（前后快照求增量）
- 其他: 使用 Envoy access log
"""

from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.internal.models.testcase import CollectionResult, TestCase
from istio_Dynamic_Test.internal.models.testcase import PolicyType
from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import query_traffic_distribution
from istio_Dynamic_Test.internal.telemetry.collectors.base import BaseCollector
from istio_Dynamic_Test.internal.telemetry.collectors.envoy import EnvoyCollector


class CompositeCollector(BaseCollector):
    """组合采集器：traffic_split 用 Prometheus，其余用 Envoy 日志。"""

    def __init__(
        self,
        envoy_collector: Optional[EnvoyCollector] = None,
        prometheus_url: Optional[str] = None,
        namespace: str = "default",
        ssh_client=None,
    ):
        self._envoy = envoy_collector or EnvoyCollector(
            ssh_client=ssh_client, namespace=namespace
        )
        self._prometheus_url = prometheus_url
        self._namespace = namespace

    def collect(
        self,
        test_case: TestCase,
        pre_snapshot: Optional[dict] = None,
        pre_prometheus: Optional[Dict[str, int]] = None,
    ) -> CollectionResult:
        # traffic_split 且配置了 Prometheus：用 Prometheus 验证
        if (
            PolicyType.TRAFFIC_SPLIT in test_case.policy_types
            and test_case.expected_distribution
            and self._prometheus_url
        ):
            return self._collect_prometheus(test_case, pre_prometheus)
        # 其他：用 Envoy 日志
        return self._envoy.collect(test_case, pre_snapshot=pre_snapshot)

    def _collect_prometheus(
        self,
        test_case: TestCase,
        pre_prometheus: Optional[Dict[str, int]],
    ) -> CollectionResult:
        svc = test_case.host or test_case.source_service or "unknown"
        versions = list(test_case.expected_distribution.keys())

        try:
            after = query_traffic_distribution(
                self._prometheus_url, svc, versions, self._namespace
            )
        except Exception as e:
            return CollectionResult(
                case_id=test_case.case_id,
                prometheus_metrics={"_error": str(e)},
            )

        # 计算增量（若无 pre 则用 after 作为本次观测值）
        if pre_prometheus:
            delta = {
                v: after.get(v, 0) - pre_prometheus.get(v, 0)
                for v in set(versions) | set(after.keys())
            }
        else:
            delta = after

        total = sum(delta.get(v, 0) for v in versions)
        version_percentages = (
            {v: delta[v] / total for v in versions if total > 0}
            if total > 0
            else {}
        )

        return CollectionResult(
            case_id=test_case.case_id,
            prometheus_metrics={
                "traffic_distribution": delta,
                "version_percentages": version_percentages,
                "total_requests": total,
            },
        )

    def snapshot_log_lines(self, test_case: TestCase) -> dict:
        """Envoy 日志快照（非 traffic_split 时使用）。"""
        return self._envoy.snapshot_log_lines(test_case)

    def warmup_for_suite(self, cases: List[TestCase]) -> None:
        """预热（仅 Envoy，Prometheus 无需预热）。"""
        self._envoy.warmup_for_suite(cases)

    def snapshot_prometheus(self, test_case: TestCase) -> Optional[Dict[str, int]]:
        """获取 Prometheus 流量快照（traffic_split 执行前调用）。"""
        if (
            not self._prometheus_url
            or not test_case.expected_distribution
        ):
            return None
        svc = test_case.host or test_case.source_service or "unknown"
        versions = list(test_case.expected_distribution.keys())
        try:
            return query_traffic_distribution(
                self._prometheus_url, svc, versions, self._namespace
            )
        except Exception:
            return None
