"""TimeoutValidator —— 验证超时策略是否生效。

验证思路（与我们手工排障/验证一致）：
1) 行为侧：Executor 的 HTTP 状态码中应出现 504（Gateway Timeout）或明显超时迹象；
2) 可观测侧（可选）：Prometheus 的 istio_requests_total 中出现 response_flags="UT"（Upstream Timeout），
   且可伴随 destination reporter 的 response_flags="DC"（Downstream Connection termination）。

注意：
- 在真实环境中，超时/UT 是否落到 metrics 里会受抓取周期影响，因此这里以“出现即通过”为主，
  不以严格等值对齐作为失败条件，避免误报。
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
from .base import BaseValidator


class TimeoutValidator(BaseValidator):
    def __init__(self, prometheus_url: Optional[str] = None, namespace: str = "default"):
        self._prometheus_url = prometheus_url
        self._namespace = namespace

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []

        # 1) 行为侧：504 是否出现
        if execution:
            total = execution.total_requests or test_case.request_count or 1
            cnt_504 = int(execution.status_codes.get("504", 0) or 0)
            rate_504 = cnt_504 / total if total else 0.0
            ok = cnt_504 > 0
            details.append(
                ValidationDetail(
                    dimension="HTTP超时(504)",
                    status=ValidationStatus.PASSED if ok else ValidationStatus.WARNING,
                    message=f"504={cnt_504}/{total} ({rate_504:.1%})",
                    expected="出现部分 504（超时生效）",
                    actual=execution.status_codes,
                    details={"total": total, "cnt_504": cnt_504, "rate_504": rate_504},
                )
            )

        # 2) 可观测侧：Prometheus response_flags=UT / DC（可选）
        if self._prometheus_url:
            dest_service = test_case.host or test_case.source_service or ""
            try:
                from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import (
                    query_response_flags_ut,
                    query_response_flags_dc,
                )

                pm_ut = query_response_flags_ut(
                    self._prometheus_url,
                    destination_service=dest_service,
                    namespace=self._namespace,
                )
                pm_dc = query_response_flags_dc(
                    self._prometheus_url,
                    destination_service=dest_service,
                    namespace=self._namespace,
                )
                # 有 UT 即强证据；DC 作为伴随现象给提示
                status = ValidationStatus.PASSED if pm_ut > 0 else ValidationStatus.WARNING
                msg = f"Prometheus UT={pm_ut}"
                if pm_dc > 0:
                    msg += f", DC={pm_dc}"
                details.append(
                    ValidationDetail(
                        dimension="Prometheus(response_flags)",
                        status=status,
                        message=msg,
                        expected='response_flags="UT" 出现（可选 DC 伴随）',
                        actual={"UT": pm_ut, "DC": pm_dc},
                    )
                )
            except Exception:
                # Prometheus 不可用或指标未暴露时，不应让整体验证失败
                details.append(
                    ValidationDetail(
                        dimension="Prometheus(response_flags)",
                        status=ValidationStatus.SKIPPED,
                        message="Prometheus 不可用或指标未暴露，跳过",
                    )
                )

        overall = (
            ValidationStatus.FAILED
            if any(d.status == ValidationStatus.FAILED for d in details)
            else ValidationStatus.WARNING
            if any(d.status == ValidationStatus.WARNING for d in details)
            else ValidationStatus.PASSED
            if any(d.status == ValidationStatus.PASSED for d in details)
            else ValidationStatus.SKIPPED
        )

        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"超时验证: {overall.value}",
        )

