"""ConnectionPoolValidator —— 验证连接池限制是否生效。

当前基于 ExecutionResult 与 Envoy 日志做间接验证：
- 高并发下 503/连接失败增多可视为连接池限制的间接证据
- 未来可扩展：Prometheus envoy_cluster_upstream_cx_overflow（需 proxyStatsMatcher 开启）
"""

from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    PolicyType,
    TestCase,
    ValidationDetail,
    ValidationResult,
    ValidationStatus,
)
from istio_Dynamic_Test.internal.telemetry.logs.parser import EnvoyLogParser
from .base import BaseValidator


class ConnectionPoolValidator(BaseValidator):
    """连接池验证器。基于 ExecutionResult 与 Envoy 日志做间接验证。"""

    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        self._parser = log_parser or EnvoyLogParser()

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []

        # 1. 高并发负载下的错误模式（连接池满时易出现 503/连接失败）
        if execution:
            total = execution.total_requests
            error_count = execution.error_count
            has_503 = execution.status_codes.get("503", 0) > 0
            error_rate = error_count / total if total else 0

            # 连接池测试通常：高并发 + 一定错误率
            is_load_test = total >= 50 and PolicyType.CONNECTION_POOL in (test_case.policy_types or [])
            if is_load_test:
                # 有 503 或错误率 > 5% 可视为连接池/熔断在起作用
                indicator = has_503 or error_rate > 0.05
                details.append(ValidationDetail(
                    dimension="连接池/负载",
                    status=ValidationStatus.PASSED if indicator else ValidationStatus.WARNING,
                    message=f"总请求={total}, 错误={error_count}{', 503=' + str(execution.status_codes.get('503', 0)) if has_503 else ''}",
                    expected="高负载下有限流/连接失败迹象",
                    actual=execution.status_codes,
                ))

        # 2. 日志维度：503/错误日志
        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            all_entries = [e for entries in parsed.values() for e in entries]
            conn_errors = [e for e in all_entries if e.status_code in (503, 0) or e.is_error]
            if conn_errors:
                details.append(ValidationDetail(
                    dimension="连接相关错误",
                    status=ValidationStatus.PASSED,
                    message=f"检测到 {len(conn_errors)} 条连接/503 相关日志",
                ))

        if not details:
            details.append(ValidationDetail(
                dimension="连接池",
                status=ValidationStatus.SKIPPED,
                message="无连接池测试数据或连接池指标未暴露（可配置 proxyStatsMatcher 暴露 envoy_cluster_upstream_cx_*）",
            ))

        overall = (
            ValidationStatus.FAILED
            if any(d.status == ValidationStatus.FAILED for d in details)
            else ValidationStatus.WARNING
            if any(d.status == ValidationStatus.WARNING for d in details)
            else details[0].status if details else ValidationStatus.SKIPPED
        )

        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"连接池验证: {overall.value}",
        )
