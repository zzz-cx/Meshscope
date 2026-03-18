"""TrafficSplitValidator —— 验证流量分割是否符合预期权重分布。"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def _check_and_log_mismatch(
    total: int, client_count: int, actual_pct: Dict[str, float],
    expected_dist: Dict[str, float], dist_result: Dict[str, Any],
) -> None:
    """验证失败时输出诊断信息，便于排查分布异常。"""
    if total < client_count * 0.8:
        print(f"  [DIAG] 日志数({total})<请求数({client_count})，可能过滤过严或采集不全")
    max_dev = max(
        abs(actual_pct.get(v, 0) - expected_dist.get(v, 0))
        for v in expected_dist
    ) if expected_dist else 0
    if max_dev > 0.15:
        vd = dist_result.get("version_distribution", {})
        print(f"  [DIAG] 分布偏差较大: 实际{vd} (期望{expected_dist})")

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


class TrafficSplitValidator(BaseValidator):

    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        self._parser = log_parser or EnvoyLogParser()

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

        # 解析日志并统计分布
        if collection and collection.envoy_logs:
            parsed = self._parser.parse_logs_batch(collection.envoy_logs)
            svc = test_case.host or "unknown"
            dist_result = self._parser.analyze_distribution(parsed, svc)
            total = dist_result.get("total_requests", 0)
            actual_pct = dist_result.get("version_percentages", {})
            client_count = (execution.total_requests if execution else 0) or test_case.request_count or 0
            # 验证失败时输出诊断信息
            if total > 0 and expected_dist and client_count > 0:
                _check_and_log_mismatch(
                    total, client_count, actual_pct, expected_dist, dist_result,
                )

            margin = self._effective_margin(expected_dist, total, test_case.margin_of_error)

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
            details.append(ValidationDetail(
                dimension="流量分布",
                status=status,
                message=self._summary_msg(version_details, margin),
                expected=expected_dist,
                actual=actual_pct,
                deviation=self._avg_dev(version_details),
                details={"version_details": version_details, "total": total, "margin": margin},
            ))
        else:
            details.append(ValidationDetail(
                dimension="流量分布",
                status=ValidationStatus.SKIPPED,
                message="无日志数据",
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
        """基于二项分布 95% 置信区间的动态容错。"""
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
