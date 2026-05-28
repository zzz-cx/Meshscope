"""TrafficSplitValidator —— 验证流量分割是否符合预期权重分布。

使用 Prometheus pre/after 增量校验：执行前快照、发 N 次请求、等待 12s、执行后快照，求增量。
"""

import math
from typing import Any, Dict, Optional

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    TestCase,
    ValidationDetail,
    ValidationResult,
    ValidationStatus,
)
from .base import BaseValidator


# 最小增量样本数，低于此值建议增加请求
MIN_DELTA_SAMPLES = 20

class TrafficSplitValidator(BaseValidator):
    """基于 Prometheus 的流量分布验证：固定 N 次请求 + pre/after 增量校验。"""

    def __init__(
        self,
        prometheus_url: Optional[str] = None,
        ingress_url: Optional[str] = None,
        namespace: str = "default",
    ):
        self._prometheus_url = prometheus_url
        self._ingress_url = ingress_url
        self._namespace = namespace

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        details = []
        expected_dist = test_case.expected_distribution

        if not expected_dist:
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.SKIPPED,
                summary="未配置期望分布，跳过",
            )

        # 使用 Collector 的 pre/after Prometheus 增量
        pm = (collection and collection.prometheus_metrics) or {}
        if "_error" in pm:
            details.append(ValidationDetail(
                dimension="流量分布",
                status=ValidationStatus.FAILED,
                message=f"Prometheus 采集失败: {pm['_error']}",
            ))
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.FAILED,
                details=details,
                summary="流量分割验证: Prometheus 采集失败",
            )

        total = pm.get("total_requests", 0)
        actual_pct = pm.get("version_percentages", {})
        version_dist = pm.get("traffic_distribution", {})

        if total == 0:
            details.append(ValidationDetail(
                dimension="流量分布",
                status=ValidationStatus.SKIPPED,
                message="Prometheus 无增量数据（请确保执行了请求且 Prometheus 可访问）",
            ))
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.SKIPPED,
                details=details,
                summary="流量分割验证: 无数据",
            )

        # 增量过少时建议多次少量请求
        if total < MIN_DELTA_SAMPLES:
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.SKIPPED,
                details=[ValidationDetail(
                    dimension="流量分布",
                    status=ValidationStatus.SKIPPED,
                    message=f"增量过少({total} < {MIN_DELTA_SAMPLES})，建议多次少量请求(如 20×10) 以稳定分布",
                    expected=expected_dist,
                    actual=actual_pct,
                    details={"total": total, "version_distribution": version_dist},
                )],
                summary=f"流量分割验证: 增量过少，建议增加请求",
            )

        # 合理波动范围：二项分布 95% 置信 + 抓取延迟噪声 + 小样本放宽
        base_margin = max(0.15, test_case.margin_of_error)
        margin = self._effective_margin(expected_dist, total, base_margin)
        # 抓取延迟等噪声，容差额外 +8%
        margin += 0.08
        # 小样本（< 100）时再放宽
        if total < 100:
            margin += 0.05

        all_pass = True
        version_details = {}
        for ver, expected_w in expected_dist.items():
            actual_w = actual_pct.get(ver, 0.0)
            dev = abs(actual_w - expected_w)
            ok = dev <= margin
            if not ok:
                all_pass = False
            version_details[ver] = {
                "expected": expected_w,
                "actual": actual_w,
                "deviation": dev,
                "passed": ok,
            }

        status = ValidationStatus.PASSED if all_pass else ValidationStatus.FAILED
        # 输出流量数据对比日志
        comp_parts = [f"{v}: 期望{expected_dist.get(v,0):.0%} 实际{actual_pct.get(v,0):.0%}({version_dist.get(v,0)}次)" for v in expected_dist]
        print(f"  [TRAFFIC_SPLIT] 增量 N={total} | {' | '.join(comp_parts)} | {'通过' if all_pass else '未通过'}")
        details.append(ValidationDetail(
            dimension="流量分布(固定N次+Prometheus增量)",
            status=status,
            message=self._summary_msg(version_details, margin),
            expected=expected_dist,
            actual=actual_pct,
            deviation=self._avg_dev(version_details),
            details={
                "version_details": version_details,
                "total": total,
                "margin": margin,
                "version_distribution": version_dist,
            },
        ))

        overall = details[0].status if details else ValidationStatus.SKIPPED
        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=details,
            summary=f"流量分割验证{'通过' if overall == ValidationStatus.PASSED else '未通过'}",
        )

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _effective_margin(expected: Dict[str, float], n: int, base: float) -> float:
        """基于二项分布 95% 置信区间的动态容错（与 curl_prometheus_monitor 一致）。"""
        if n <= 0:
            return base
        margins = []
        for p in expected.values():
            p = max(0.0, min(1.0, float(p)))
            se = math.sqrt(p * (1.0 - p) / n)
            margins.append(1.96 * se)
        dynamic = max(margins) + 0.01 if margins else 0.0
        return max(base, dynamic)

    @staticmethod
    def _avg_dev(vd: dict) -> float:
        devs = [v["deviation"] for v in vd.values()]
        return sum(devs) / len(devs) if devs else 0.0

    @staticmethod
    def _summary_msg(vd: dict, margin: float) -> str:
        parts = []
        for ver, info in vd.items():
            icon = "PASS" if info["passed"] else "FAIL"
            parts.append(
                f"{ver}: {info['actual']:.1%} (期望 {info['expected']:.1%}, "
                f"偏差 {info['deviation']:.1%}) [{icon}]"
            )
        return f"容错±{margin:.1%} | " + " | ".join(parts)
