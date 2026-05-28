"""RetryValidator —— 验证重试策略是否正确生效。

论文级验证逻辑：
1. backend 请求数 > client 请求数 → 上游重试导致本服务收到多次请求
2. 同一 request_id 有多条 5xx 记录 → 本服务对上游的重试（如 fault 注入后）
"""

from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    TestCase,
    ValidationDetail,
    ValidationResult,
    ValidationStatus,
)
from istio_Dynamic_Test.internal.telemetry.logs.parser import EnvoyLogParser
from .base import BaseValidator


class RetryValidator(BaseValidator):

    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        self._parser = log_parser or EnvoyLogParser()

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []
        indicators = []

        client_count = (execution.total_requests if execution else 0) or test_case.request_count or 1
        svc = test_case.host or test_case.source_service or ""

        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            evidence = self._parser.detect_retry_evidence(
                parsed, client_request_count=client_count, service_name=svc
            )
            indicators = evidence.get("indicators", [])

            # 辅助：响应时间分布（P95/P50 > 3 暗示重试延迟）
            all_entries = [e for entries in parsed.values() for e in entries]
            times = sorted(e.request_time for e in all_entries if e.request_time > 0)
            if times and len(times) > 5:
                p50 = times[len(times) // 2]
                p95 = times[min(int(len(times) * 0.95), len(times) - 1)]
                ratio = p95 / p50 if p50 > 0 else 1
                if ratio > 3:
                    indicators.append(f"P95/P50={ratio:.1f}(重试延迟)")

            # 辅助：部分失败后成功（错误率 10%~80%）
            errors = [e for e in all_entries if e.is_error]
            successes = [e for e in all_entries if e.is_success]
            if errors and successes:
                err_rate = len(errors) / len(all_entries)
                if 0.1 < err_rate < 0.8:
                    indicators.append(f"部分错误后成功(错误率{err_rate:.1%})")

            detected = evidence.get("retry_detected", False) or len(indicators) > 0
            details.append(ValidationDetail(
                dimension="重试行为",
                status=ValidationStatus.PASSED if detected else ValidationStatus.WARNING,
                message=f"重试指标: {', '.join(indicators)}" if indicators else "未检测到明确重试特征",
                expected=f"重试{test_case.expected_retry_attempts}次" if test_case.expected_retry_attempts else "backend>client 或 同一request_id多次5xx",
                actual={
                    "retry_detected": evidence.get("retry_detected"),
                    "client_requests": client_count,
                    "backend_inbound": evidence.get("total_inbound_entries"),
                    "retry_request_count": evidence.get("retry_request_count"),
                },
            ))

        if execution:
            details.append(ValidationDetail(
                dimension="HTTP状态码",
                status=ValidationStatus.PASSED if execution.success_rate > 0 else ValidationStatus.FAILED,
                message=f"成功率={execution.success_rate:.1f}%",
                actual=execution.status_codes,
            ))

        # 严格模式：任一 FAILED 则整体 FAILED
        overall = (
            ValidationStatus.FAILED
            if any(d.status == ValidationStatus.FAILED for d in details)
            else ValidationStatus.WARNING
            if any(d.status == ValidationStatus.WARNING for d in details)
            else ValidationStatus.PASSED
        )
        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"重试验证: {overall.value}",
        )
