"""FaultInjectionValidator —— 验证故障注入是否正确生效。"""

from typing import Optional

from istio_Dynamic_Test.internal.models.protocol import Protocol
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


class FaultInjectionValidator(BaseValidator):

    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        self._parser = log_parser or EnvoyLogParser()

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []
        expected_code = test_case.expected_fault_code
        expected_rate = test_case.expected_fault_rate

        # 1. 执行层（HTTP 状态码 / gRPC status）
        if execution:
            if expected_code is not None:
                key = str(expected_code)
                fault_count = execution.status_codes.get(key, 0)
                if test_case.protocol == Protocol.GRPC and fault_count == 0:
                    from istio_Dynamic_Test.internal.traffic.protocols.grpc.status import grpc_name_to_code
                    fault_count = execution.status_codes.get(grpc_name_to_code(key), 0)
                has_fault = fault_count > 0
            else:
                fault_count = execution.error_count
                has_fault = fault_count > 0

            actual_rate = fault_count / execution.total_requests if execution.total_requests else 0

            if expected_rate is not None:
                dev = abs(actual_rate - expected_rate)
                ok = dev <= 0.1
            else:
                ok = has_fault

            details.append(ValidationDetail(
                dimension="故障注入效果",
                status=ValidationStatus.PASSED if ok else ValidationStatus.FAILED,
                message=f"故障率={actual_rate:.1%}" + (f" (期望{expected_rate:.1%})" if expected_rate else ""),
                expected=expected_rate,
                actual=actual_rate,
                deviation=abs(actual_rate - (expected_rate or 0)),
            ))

        # 2. 日志维度
        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            all_entries = [e for entries in parsed.values() for e in entries]
            if expected_code is not None and test_case.protocol == Protocol.GRPC:
                fault_entries = [
                    e for e in all_entries
                    if e.grpc_status is not None and int(e.grpc_status) == int(expected_code)
                ]
            elif expected_code:
                fault_entries = [e for e in all_entries if e.status_code == expected_code]
            else:
                fault_entries = [e for e in all_entries if e.is_error]
            details.append(ValidationDetail(
                dimension="日志故障记录",
                status=ValidationStatus.PASSED if fault_entries else ValidationStatus.WARNING,
                message=f"日志中检测到 {len(fault_entries)} 条故障请求",
                actual=len(fault_entries),
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
            summary=f"故障注入验证: {overall.value}",
        )
