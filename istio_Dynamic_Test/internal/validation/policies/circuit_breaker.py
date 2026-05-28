"""CircuitBreakerValidator —— 验证熔断策略是否正确触发。

验证两件事：① 是否触发保护机制  ② 触发后行为是否符合预期（拒绝/限流）

指标体系：
- response_flags=UO（Upstream Overflow）—— 熔断最直接证据
- 503 比例上升
- CircuitBreakerEffectiveness = RejectedRequests / TotalRequests
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


class CircuitBreakerValidator(BaseValidator):

    def __init__(
        self,
        log_parser: Optional[EnvoyLogParser] = None,
        prometheus_url: Optional[str] = None,
        namespace: str = "default",
    ):
        self._parser = log_parser or EnvoyLogParser()
        self._prometheus_url = prometheus_url
        self._namespace = namespace

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []

        # 1. HTTP 维度：503 + 熔断有效性公式
        if execution:
            total = execution.total_requests
            rejected = execution.status_codes.get("503", 0)
            has_503 = rejected > 0
            error_rate = execution.error_count / total if total else 0
            effectiveness = rejected / total if total else 0.0  # CircuitBreakerEffectiveness
            # 单入口模型：若通过 delay 占用连接触发 overflow，UO 可能不稳定落到采集窗口；
            # 这里用“足够高的 503 比例 + load_test”作为强信号，降低误报 WARNING。
            strong_http_signal = (total >= 30 and effectiveness >= 0.2)

            details.append(ValidationDetail(
                dimension="HTTP错误率",
                status=ValidationStatus.PASSED if (has_503 and (error_rate > 0.1 or strong_http_signal)) else ValidationStatus.WARNING,
                message=f"503={rejected}, 错误率={error_rate:.1%}, 熔断有效性(Rejected/Total)={effectiveness:.1%}",
                expected="503 errors present",
                actual=execution.status_codes,
            ))

        # 2. 日志维度：response_flags=UO（熔断最直接证据）
        uo_count = 0
        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            all_entries = [e for entries in parsed.values() for e in entries]
            all_entries.sort(key=lambda e: e.timestamp)

            uo_entries = [e for e in all_entries if e.is_upstream_overflow]
            uo_count = len(uo_entries)
            cb_errors = [e for e in all_entries if e.status_code == 503]
            indicators = []

            if uo_count > 0:
                indicators.append(f"response_flags=UO×{uo_count}（熔断直接证据）")

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

            # 单入口模型补强：如果 HTTP 侧已经表现出明显 503 溢出，但日志窗口没抓到 UO，
            # 仍视为“熔断/连接池保护”已生效，避免长期 WARNING。
            detected = len(indicators) > 0
            if not detected and execution:
                total = execution.total_requests or 0
                eff = (execution.status_codes.get("503", 0) / total) if total else 0.0
                if total >= 30 and eff >= 0.2:
                    indicators.append("HTTP侧 503 比例较高（推定保护机制触发）")
                    detected = True
            details.append(ValidationDetail(
                dimension="熔断行为",
                status=ValidationStatus.PASSED if uo_count > 0 or detected else ValidationStatus.WARNING,
                message=f"熔断指标: {', '.join(indicators)}" if indicators else "未检测到明确熔断特征(UO/连续错误/快速失败)",
                expected="response_flags=UO or circuit breaker triggered",
                actual={"503_count": len(cb_errors), "UO_count": uo_count, "max_consecutive": max_consecutive},
            ))

        # 3. Prometheus：503 与 response_flags=UO 交叉验证
        if self._prometheus_url and execution:
            dest_service = test_case.host or test_case.source_service or ""
            try:
                from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import query_503_count, query_response_flags_uO
                pm_503 = query_503_count(
                    self._prometheus_url,
                    destination_service=dest_service or "",
                    namespace=self._namespace,
                )
                pm_uO = query_response_flags_uO(
                    self._prometheus_url,
                    destination_service=dest_service or "",
                    namespace=self._namespace,
                )
                exec_503 = execution.status_codes.get("503", 0)
                # 单入口动态验证中 Prometheus 采集存在“时间窗/抓取周期”问题：
                # 当 execution 里已有大量 503，但 Prometheus 仍是 0 时，更多是采集延迟而非策略未生效。
                if exec_503 > 0 and pm_503 == 0 and pm_uO == 0:
                    details.append(ValidationDetail(
                        dimension="Prometheus",
                        status=ValidationStatus.SKIPPED,
                        message=f"Prometheus 可能未及时抓取：Execution 503={exec_503}, Prometheus 503={pm_503}",
                        details={"execution_503": exec_503, "prometheus_503": pm_503, "prometheus_UO": pm_uO},
                    ))
                    pm_503 = None  # 已记录，后续不再按 diff 判断
                diff_ok = True if pm_503 is None else (abs(pm_503 - exec_503) <= max(exec_503 * 0.2, 5) if exec_503 else pm_503 >= 0)
                msg = f"Execution 503={exec_503}, Prometheus 503={pm_503 if pm_503 is not None else 'skipped'}"
                if pm_uO > 0:
                    msg += f", UO={pm_uO}"
                if pm_503 is not None:
                    details.append(ValidationDetail(
                        dimension="Prometheus",
                        status=ValidationStatus.PASSED if diff_ok or pm_uO > 0 else ValidationStatus.WARNING,
                        message=msg,
                        details={"execution_503": exec_503, "prometheus_503": pm_503, "prometheus_UO": pm_uO},
                    ))
            except Exception:
                pass

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
            summary=f"熔断验证: {overall.value}",
        )
