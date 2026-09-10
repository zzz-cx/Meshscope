"""RoutingValidator —— 验证请求是否路由到正确的目标版本。"""

from typing import Optional

from istio_Dynamic_Test.internal.models.protocol import Protocol
from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    PolicyType,
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

        # 1. 执行层状态验证（HTTP 状态码 / gRPC status）
        if execution:
            codes = execution.status_codes or {}
            is_grpc = test_case.protocol == Protocol.GRPC
            if is_grpc:
                ok_count = sum(
                    c for k, c in codes.items()
                    if str(k) in ("0", "OK", "Ok")
                )
                transport_ok = ok_count > 0
                expect_msg = "gRPC OK (status=0)"
            elif PolicyType.RATE_LIMIT in (test_case.policy_types or []):
                rl_expect = test_case.rate_limit_expect or {}
                allow_503_backpressure = bool(rl_expect.get("allow_503_as_throttle"))
                http_ok = any(
                    k.startswith("2") for k in codes
                ) or int(codes.get("429", 0) or 0) > 0
                if allow_503_backpressure:
                    http_ok = http_ok or int(codes.get("503", 0) or 0) > 0
                expect_msg = "2xx 或 429(限流)"
                if allow_503_backpressure:
                    expect_msg += " 或 503(背压，与 pool/CB 耦合时)"
                transport_ok = http_ok
            elif not is_grpc:
                transport_ok = any(k.startswith("2") for k in codes)
                expect_msg = "2xx"
            details.append(ValidationDetail(
                dimension="gRPC状态" if is_grpc else "HTTP状态码",
                status=ValidationStatus.PASSED if transport_ok else ValidationStatus.FAILED,
                message=f"status_codes={execution.status_codes}",
                expected=expect_msg,
                actual=list(codes.keys()),
            ))

        # 1b. gRPC Envoy 日志指标（采集层）
        if test_case.protocol == Protocol.GRPC and collection and collection.metadata.get("grpc_metrics"):
            gm = collection.metadata["grpc_metrics"]
            total = gm.get("total_grpc_requests", 0)
            dist = gm.get("grpc_status_distribution", {})
            ok_logs = int(dist.get("0", 0) or 0)
            log_ok = total > 0 and ok_logs > 0
            details.append(ValidationDetail(
                dimension="gRPC日志指标",
                status=ValidationStatus.PASSED if log_ok else ValidationStatus.WARNING,
                message=f"envoy grpc_status 分布={dist}, total={total}",
                expected="grpc_status=0 有记录",
                actual=dist,
            ))

        # 2. 日志目标版本验证
        expected_dest = test_case.expected_destination
        if expected_dest and collection and collection.envoy_logs:
            # 匹配 subset（如 v1）: "-v1-" in "productpage-v1-xxx"；匹配 service（如 productpage）: "productpage-v1-xxx".startswith("productpage-")
            target_pods = [
                pod for pod in collection.envoy_logs
                if f"-{expected_dest}-" in pod
                or pod.endswith(f"-{expected_dest}")
                or pod.startswith(f"{expected_dest}-")
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
        """严格模式：所有维度都通过才算通过，任一 FAILED 则整体 FAILED。"""
        if not details:
            return ValidationStatus.SKIPPED
        if any(d.status == ValidationStatus.FAILED for d in details):
            return ValidationStatus.FAILED
        if any(d.status == ValidationStatus.WARNING for d in details):
            return ValidationStatus.WARNING
        return ValidationStatus.PASSED
