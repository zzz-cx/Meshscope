"""ConnectionPoolOutlierValidator —— 验证连接池与熔断参数是否符合 DestinationRule 配置。

验证项：
1. consecutiveErrors：503 数量 >= 配置值（熔断已触发）
2. baseEjectionTime：等待后恢复请求返回 200
3. connectionPool：maxConnections、http1MaxPendingRequests 在报告中输出
"""

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


class ConnectionPoolOutlierValidator(BaseValidator):
    """连接池与熔断参数验证器。"""

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []
        metadata = (execution.metadata or {}) if execution else {}

        expected_consecutive = metadata.get("expected_consecutive_errors", 5)
        expected_ejection = metadata.get("expected_base_ejection_time", "60s")
        phase1_503 = metadata.get("phase1_503_count", 0)
        phase2_200 = metadata.get("phase2_200_count", 0)
        phase2_total = metadata.get("phase2_total", 0)
        conn_limits = metadata.get("connection_limits", {})

        # 1. 熔断触发：503 数量应 >= consecutiveErrors
        cb_ok = phase1_503 >= expected_consecutive
        details.append(ValidationDetail(
            dimension="熔断触发(consecutiveErrors)",
            status=ValidationStatus.PASSED if cb_ok else ValidationStatus.FAILED,
            message=f"期望 >= {expected_consecutive} 次 503 触发熔断，实际 phase1 503={phase1_503}",
            expected=f"phase1_503_count >= {expected_consecutive}",
            actual={"phase1_503_count": phase1_503, "expected_consecutive_errors": expected_consecutive},
        ))

        # 2. 熔断恢复：baseEjectionTime 后应有 200
        recovery_ok = phase2_total > 0 and phase2_200 > 0
        details.append(ValidationDetail(
            dimension="熔断恢复(baseEjectionTime)",
            status=ValidationStatus.PASSED if recovery_ok else ValidationStatus.FAILED,
            message=f"等待 {expected_ejection} 后恢复验证：phase2 200={phase2_200}/{phase2_total}",
            expected=f"phase2 有 200 响应（baseEjectionTime={expected_ejection} 后恢复）",
            actual={"phase2_200_count": phase2_200, "phase2_total": phase2_total},
        ))

        # 3. 连接池参数（报告用）
        tcp_max = conn_limits.get("tcp", conn_limits.get("max_connections"))
        http_pending = conn_limits.get("http_pending", conn_limits.get("http1_max_pending_requests"))
        details.append(ValidationDetail(
            dimension="连接池参数(connectionPool)",
            status=ValidationStatus.PASSED,
            message=f"maxConnections={tcp_max}, http1MaxPendingRequests={http_pending}",
            expected="参数与 DestinationRule 一致",
            actual=conn_limits,
        ))

        overall = (
            ValidationStatus.FAILED
            if any(d.status == ValidationStatus.FAILED for d in details)
            else ValidationStatus.PASSED
        )

        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"连接池与熔断参数验证: consecutiveErrors 触发={'通过' if cb_ok else '未通过'}, baseEjectionTime 恢复={'通过' if recovery_ok else '未通过'}",
        )
