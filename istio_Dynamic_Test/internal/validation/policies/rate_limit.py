"""RateLimitValidator —— 验证限流是否按预期发生。

依据：
- HTTP 429（及 execution 层统计）
- Envoy access log 中 429 条数（行为侧佐证）
- Prometheus：istio_requests_total{response_code="429"}；可选 envoy_*ratelimit*over_limit
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


class RateLimitValidator(BaseValidator):
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
        expect = test_case.rate_limit_expect

        if not execution:
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.SKIPPED,
                summary="限流验证：无执行结果",
            )

        total = execution.total_requests or 0
        codes = execution.status_codes or {}
        c429 = int(codes.get("429", 0) or 0)
        c503 = int(codes.get("503", 0) or 0)

        if not expect:
            details.append(self._heuristic_detail(total, c429, c503))
            if total >= 40 and c429 < 1 and c503 >= 1:
                details.append(self._coupling_hint(c429, c503))
        else:
            mode = (expect.get("mode") or "").strip()
            eps_a = int(expect.get("epsilon_abs", 3))
            eps_r = float(expect.get("epsilon_ratio", 0.2))
            allow_503 = bool(expect.get("allow_503_as_throttle"))

            if mode == "should_pass_all":
                max429 = int(expect.get("max_429", eps_a))
                ok = c429 <= max429
                details.append(
                    ValidationDetail(
                        dimension="HTTP 429（低压/配额内）",
                        status=ValidationStatus.PASSED if ok else ValidationStatus.FAILED,
                        message=f"429={c429}, 允许 max_429={max429}",
                        expected=max429,
                        actual=c429,
                    )
                )

            elif mode == "should_see_limits":
                min429 = int(expect.get("min_429", 1))
                ok_429 = c429 >= min429
                ok_503 = allow_503 and c503 >= min429
                ok = ok_429 or ok_503
                msg = f"429={c429}, 503={c503}, 期望至少 min_429={min429}"
                if allow_503 and ok_503 and not ok_429:
                    msg += "（已启用 allow_503_as_throttle：把 503 视作限流/背压，需结合日志 response_flags 甄别）"
                dim = "HTTP 429（应出现限流）"
                details.append(
                    ValidationDetail(
                        dimension=dim,
                        status=ValidationStatus.PASSED if ok else ValidationStatus.FAILED,
                        message=msg,
                        expected=min429,
                        actual=c429 if ok_429 else (c503 if ok_503 else max(c429, c503)),
                    )
                )
                if not ok and c503 > 0 and not ok_429:
                    details.append(self._coupling_hint(c429, c503))

            elif mode == "proportion":
                budget = int(expect.get("allowed_budget", 0))
                expected_denied = max(0, total - budget)
                denied_metric = c429
                if allow_503 and not expect.get("proportion_429_only"):
                    denied_metric = c429 + c503
                dev = abs(denied_metric - expected_denied)
                tol = eps_a + eps_r * max(total, 1)
                ok = dev <= tol
                msg = (
                    f"total={total}, allowed_budget={budget}, "
                    f"统计拒绝数={denied_metric}（429={c429}, 503={c503}）, "
                    f"期望约 {expected_denied}, 容差≤{tol:.1f}"
                )
                if allow_503 and not expect.get("proportion_429_only"):
                    msg += "；含 503 时需自行确认非误判（连接池/熔断）"
                details.append(
                    ValidationDetail(
                        dimension="429 数量（比例/配额）",
                        status=ValidationStatus.PASSED if ok else ValidationStatus.FAILED,
                        message=msg,
                        expected=expected_denied,
                        actual=denied_metric,
                        deviation=float(dev),
                    )
                )

            else:
                details.append(
                    ValidationDetail(
                        dimension="rate_limit 期望配置",
                        status=ValidationStatus.WARNING,
                        message=f"未知 mode={mode!r}，仅记录 429={c429}",
                        actual=c429,
                    )
                )

        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            log429 = sum(1 for rows in parsed.values() for e in rows if e.status_code == 429)
            if log429 > 0 or c429 > 0:
                loose_match = abs(log429 - c429) <= max(int(c429 * 0.35), 8) or (
                    (log429 > 0) == (c429 > 0)
                )
                details.append(
                    ValidationDetail(
                        dimension="Envoy access log 429",
                        status=ValidationStatus.PASSED if loose_match else ValidationStatus.WARNING,
                        message=f"执行统计 429={c429}, 日志解析 429={log429}",
                        actual={"exec_429": c429, "log_429": log429},
                    )
                )

        if self._prometheus_url:
            try:
                from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import (
                    query_429_count,
                    query_ratelimit_over_limit,
                )

                dest = test_case.host or test_case.source_service or ""
                pm429 = query_429_count(self._prometheus_url, dest, self._namespace)
                pm_rl = query_ratelimit_over_limit(self._prometheus_url, dest, self._namespace)
                if c429:
                    diff_ok = abs(pm429 - c429) <= max(int(c429 * 0.35), 8)
                else:
                    diff_ok = True
                msg = f"执行 429={c429}, Prometheus(istio) 429={pm429}"
                if pm_rl:
                    msg += f", ratelimit_over_limit={pm_rl}"
                prom_status = ValidationStatus.PASSED
                if not diff_ok and c429:
                    prom_status = ValidationStatus.WARNING
                details.append(
                    ValidationDetail(
                        dimension="Prometheus",
                        status=prom_status,
                        message=msg,
                        details={"prometheus_429": pm429, "over_limit": pm_rl},
                    )
                )
            except Exception:
                pass

        overall = self._rollup(details)
        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"限流验证: {overall.value}",
            metrics={"429": c429, "503": c503, "total": total},
        )

    @staticmethod
    def _coupling_hint(c429: int, c503: int) -> ValidationDetail:
        return ValidationDetail(
            dimension="限流 vs 连接池/熔断耦合",
            status=ValidationStatus.WARNING,
            message=(
                f"429={c429} 但 503={c503} 较多。常见于 DestinationRule 连接池过小、"
                "熔断或异常点检测先于「本地限流」拒绝（Envoy 常表现为 503+UO，而非 429）。"
                "单独验证限流时可：① 放宽/暂时去掉目标服务的 connectionPool、outlierDetection；"
                "② 或仅在无 aggressive DR 的服务上挂 EnvoyFilter LocalRateLimit；"
                "③ 期望里按需设 allow_503_as_throttle（需配合日志/Prometheus 甄别）。"
            ),
            actual={"429": c429, "503": c503},
        )

    def _heuristic_detail(self, total: int, c429: int, c503: int) -> ValidationDetail:
        if total <= 0:
            return ValidationDetail(
                dimension="限流（无期望配置）",
                status=ValidationStatus.SKIPPED,
                message="无请求数据",
            )
        if total >= 40:
            ok = c429 >= 1
            msg = (
                f"未配置 expected_outcome.rate_limit；"
                f"total={total} 时通常应观察到限流(429)，实际 429={c429}, 503={c503}"
            )
            if not ok and c503 >= 1:
                msg += "。若仅见 503，多半与连接池/熔断抢先拒绝有关，见上一维「耦合」说明（本启发式仍判 WARNING）。"
            return ValidationDetail(
                dimension="限流（启发式：高压）",
                status=ValidationStatus.PASSED if ok else ValidationStatus.WARNING,
                message=msg,
            )
        ok = c429 <= 1
        return ValidationDetail(
            dimension="限流（启发式：低压）",
            status=ValidationStatus.PASSED if ok else ValidationStatus.WARNING,
            message=(
                f"未配置 expected_outcome.rate_limit；"
                f"total={total} 时期望无或极少 429，实际 {c429}（503={c503}）"
            ),
        )

    @staticmethod
    def _rollup(details):
        if not details:
            return ValidationStatus.SKIPPED
        if any(d.status == ValidationStatus.FAILED for d in details):
            return ValidationStatus.FAILED
        if any(d.status == ValidationStatus.WARNING for d in details):
            return ValidationStatus.WARNING
        if all(d.status == ValidationStatus.SKIPPED for d in details):
            return ValidationStatus.SKIPPED
        return ValidationStatus.PASSED
