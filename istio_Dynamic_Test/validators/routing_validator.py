"""RoutingValidator —— 验证请求是否路由到正确的目标版本。"""

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
from .base import BaseValidator


class RoutingValidator(BaseValidator):

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []

        # 1. HTTP 状态码验证
        if execution:
            http_ok = any(
                code.startswith("2")
                for code in execution.status_codes
            )
            details.append(ValidationDetail(
                dimension="HTTP状态码",
                status=ValidationStatus.PASSED if http_ok else ValidationStatus.FAILED,
                message=f"status_codes={execution.status_codes}",
                expected="2xx",
                actual=list(execution.status_codes.keys()),
            ))

        # 2. 日志目标版本验证
        expected_dest = test_case.expected_destination
        if expected_dest and collection and collection.envoy_logs:
            target_pods = [
                pod for pod in collection.envoy_logs
                if f"-{expected_dest}-" in pod or pod.endswith(f"-{expected_dest}")
            ]
            found = len(target_pods) > 0
            details.append(ValidationDetail(
                dimension="路由目标",
                status=ValidationStatus.PASSED if found else ValidationStatus.FAILED,
                message=f"目标版本 {expected_dest} {'已命中' if found else '未命中'}",
                expected=expected_dest,
                actual=target_pods or list(collection.envoy_logs.keys()),
            ))

        overall = self._overall(details)
        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"路由验证{'通过' if overall == ValidationStatus.PASSED else '未通过'}",
        )

    @staticmethod
    def _overall(details):
        if any(d.status == ValidationStatus.PASSED for d in details):
            return ValidationStatus.PASSED
        if any(d.status == ValidationStatus.WARNING for d in details):
            return ValidationStatus.WARNING
        if details:
            return ValidationStatus.FAILED
        return ValidationStatus.SKIPPED
