"""CircuitBreakerValidator —— 验证熔断策略是否正确触发。"""

from __future__ import annotations

from typing import Optional

from istio_Dynamic_Test.models.test_case import (
    CollectionResult,
    ExecutionResult,
    TestCase,
    ValidationDetail,
    ValidationResult,
    ValidationStatus,
)
from istio_Dynamic_Test.utils.log_parser import EnvoyLogParser
from .base import BaseValidator


class CircuitBreakerValidator(BaseValidator):

    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        self._parser = log_parser or EnvoyLogParser()

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []

        # 1. HTTP 维度：检查是否有 503 错误
        if execution:
            has_503 = execution.status_codes.get("503", 0) > 0
            error_rate = execution.error_count / execution.total_requests if execution.total_requests else 0
            details.append(ValidationDetail(
                dimension="HTTP错误率",
                status=ValidationStatus.PASSED if has_503 and error_rate > 0.1 else ValidationStatus.WARNING,
                message=f"503数量={execution.status_codes.get('503', 0)}, 错误率={error_rate:.1%}",
                expected="503 errors present",
                actual=execution.status_codes,
            ))

        # 2. 日志维度：分析错误聚集模式
        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            all_entries = [e for entries in parsed.values() for e in entries]
            all_entries.sort(key=lambda e: e.timestamp)

            cb_errors = [e for e in all_entries if e.status_code == 503]
            indicators = []

            # 连续错误检测
            consecutive = max_consecutive = 0
            for e in all_entries:
                if e.is_error:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0
            if max_consecutive >= 5:
                indicators.append(f"连续错误{max_consecutive}次")

            # 快速失败检测
            if cb_errors:
                times = [e.request_time for e in cb_errors if e.request_time > 0]
                if times and (sum(times) / len(times)) < 0.1:
                    indicators.append("快速失败模式")

            detected = len(indicators) > 0
            details.append(ValidationDetail(
                dimension="熔断行为",
                status=ValidationStatus.PASSED if detected else ValidationStatus.WARNING,
                message=f"熔断指标: {', '.join(indicators)}" if indicators else "未检测到明确熔断特征",
                expected="circuit breaker triggered",
                actual={"503_count": len(cb_errors), "max_consecutive": max_consecutive},
            ))

        overall = (
            ValidationStatus.PASSED
            if any(d.status == ValidationStatus.PASSED for d in details)
            else ValidationStatus.WARNING
            if any(d.status == ValidationStatus.WARNING for d in details)
            else ValidationStatus.FAILED
        )

        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"熔断验证: {overall.value}",
        )
