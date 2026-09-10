"""TrafficSplitValidator —— 按观察链核对分流权重和落到的服务。

顺序：HTTP 响应体/头 → Prometheus 增量 → Envoy access log → Jaeger。
没有可用信号就失败，不再把「无增量」标成通过。
"""

import math
from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    TestCase,
    ValidationDetail,
    ValidationStatus,
    ValidationResult,
)
from istio_Dynamic_Test.internal.traffic.split_observe import (
    counts_to_percent,
    normalize_percent_weights,
    version_signal_usable,
)
from .base import BaseValidator


MIN_SAMPLES = 20

_SOURCE_LABEL = {
    "http_body": "入口HTTP响应体/头",
    "prometheus": "Prometheus istio_requests_total",
    "envoy_access_log": "Envoy access log",
    "jaeger": "Jaeger/Zipkin traces",
}


class TrafficSplitValidator(BaseValidator):
    """分流验证：body 可用用 body，否则用可观测工具。"""

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
        expected = normalize_percent_weights(test_case.expected_distribution)
        if not expected:
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.SKIPPED,
                summary="未配置期望分布，跳过",
            )

        observed = self._observe(execution, collection, expected)
        counts = observed.get("counts") or {}
        actual = observed.get("percentages") or {}
        total = int(observed.get("total") or 0)
        source = observed.get("source") or "none"
        landed = observed.get("landed_services") or {}
        tried = observed.get("tried") or []

        if total == 0:
            exec_codes = (execution.status_codes if execution else {}) or {}
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.FAILED,
                details=[ValidationDetail(
                    dimension="流量分布",
                    status=ValidationStatus.FAILED,
                    message=(
                        "真实入口已打流，但响应体无法识别 subset，"
                        f"且可观测回退也没有版本增量（tried={tried or ['http_body']}，"
                        f"status_codes={exec_codes}）。"
                    ),
                    expected=expected,
                    actual={},
                    details={"tried": tried, "source": source},
                )],
                summary="流量分割验证未通过: 无可用的 subset 观察信号",
            )

        if total < MIN_SAMPLES:
            return ValidationResult(
                case_id=test_case.case_id,
                overall_status=ValidationStatus.FAILED,
                details=[ValidationDetail(
                    dimension="流量分布",
                    status=ValidationStatus.FAILED,
                    message=f"可统计样本过少({total} < {MIN_SAMPLES})，来源 {source}",
                    expected=expected,
                    actual=actual,
                    details={
                        "total": total,
                        "version_distribution": counts,
                        "source": source,
                        "tried": tried,
                    },
                )],
                summary="流量分割验证未通过: 样本不足",
            )

        base_margin = float(test_case.margin_of_error or 0.1)
        margin_pp = base_margin * 100.0 if base_margin <= 1.0 else base_margin
        margin_pp = max(margin_pp, self._binomial_margin_pp(expected, total))
        if total < 100:
            margin_pp += 5.0

        all_pass = True
        version_details = {}
        for ver, expected_w in expected.items():
            actual_w = float(actual.get(ver, 0.0) or 0.0)
            dev = abs(actual_w - expected_w)
            ok = dev <= margin_pp
            if not ok:
                all_pass = False
            version_details[ver] = {
                "expected": expected_w,
                "actual": actual_w,
                "deviation": dev,
                "passed": ok,
            }

        expected_svc = (test_case.host or test_case.source_service or "").split(".")[0]
        landed_ok = True
        landed_msg = ""
        if expected_svc and expected_svc not in {"*", ""} and landed:
            top_svc = max(landed.items(), key=lambda kv: kv[1])[0]
            if top_svc != expected_svc:
                landed_ok = False
                landed_msg = f"落到的服务 {top_svc} 与期望 {expected_svc} 不一致"
            else:
                landed_msg = f"落到的服务 {top_svc} 与期望一致"

        status = ValidationStatus.PASSED if all_pass and landed_ok else ValidationStatus.FAILED
        src_label = _SOURCE_LABEL.get(source, source)
        parts = [
            f"{v}: 期望{expected.get(v, 0):.0f}% 实际{actual.get(v, 0):.0f}%({counts.get(v, 0)}次)"
            for v in expected
        ]
        print(f"  [TRAFFIC_SPLIT] {source} N={total} | {' | '.join(parts)} | {'通过' if status == ValidationStatus.PASSED else '未通过'}")
        details = [ValidationDetail(
            dimension=f"流量分布({src_label})",
            status=status,
            message=self._summary_msg(version_details, margin_pp, landed_msg),
            expected=expected,
            actual=actual,
            deviation=self._avg_dev(version_details),
            details={
                "version_details": version_details,
                "total": total,
                "margin": margin_pp,
                "version_distribution": counts,
                "weights": actual,
                "landed_services": landed,
                "source": source,
                "tried": tried,
                "entry_url": ((execution.metadata if execution else {}) or {}).get("entry_url"),
            },
        )]
        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=status,
            details=details,
            summary=f"流量分割验证{'通过' if status == ValidationStatus.PASSED else '未通过'}({src_label})",
            metrics={"weights": actual, "counts": counts, "landed_services": landed, "source": source},
        )

    def _observe(
        self,
        execution: Optional[ExecutionResult],
        collection: Optional[CollectionResult],
        expected: Dict[str, float],
    ) -> Dict[str, Any]:
        meta = (execution.metadata if execution else {}) or {}
        coll_meta = (collection.metadata if collection else {}) or {}
        tried: List[str] = []

        body_counts = {k: int(v) for k, v in (meta.get("version_counts") or {}).items()}
        if meta.get("body_usable") and version_signal_usable(body_counts, expected.keys()):
            percents, total = counts_to_percent(body_counts, expected.keys())
            return {
                "counts": body_counts,
                "percentages": percents,
                "total": total,
                "source": "http_body",
                "landed_services": meta.get("landed_services") or {},
                "tried": ["http_body"],
            }
        if body_counts:
            tried.append("http_body")

        pm = (collection.prometheus_metrics if collection else {}) or {}
        pm_counts = {k: int(v or 0) for k, v in (pm.get("traffic_distribution") or {}).items() if k != "_error"}
        tried.extend(coll_meta.get("tried") or [])
        if pm_counts and "_error" not in pm and version_signal_usable(pm_counts, expected.keys()):
            percents, total = counts_to_percent(pm_counts, expected.keys())
            return {
                "counts": pm_counts,
                "percentages": percents,
                "total": total,
                "source": "prometheus",
                "landed_services": meta.get("landed_services") or {},
                "tried": tried or ["prometheus"],
            }

        for key, source in (
            ("envoy_distribution", "envoy_access_log"),
            ("jaeger_distribution", "jaeger"),
        ):
            dist = coll_meta.get(key) or {}
            counts = {k: int(v or 0) for k, v in (dist.get("version_distribution") or {}).items()}
            if version_signal_usable(counts, expected.keys()):
                percents, total = counts_to_percent(counts, expected.keys())
                return {
                    "counts": counts,
                    "percentages": percents,
                    "total": total,
                    "source": source,
                    "landed_services": meta.get("landed_services") or {},
                    "tried": tried or [source],
                }

        return {
            "counts": {},
            "percentages": {},
            "total": 0,
            "source": "none",
            "landed_services": {},
            "tried": tried or ["http_body"],
        }

    @staticmethod
    def _binomial_margin_pp(expected: Dict[str, float], n: int) -> float:
        if n <= 0:
            return 15.0
        margins = []
        for p100 in expected.values():
            p = max(0.0, min(1.0, float(p100) / 100.0))
            se = math.sqrt(p * (1.0 - p) / n)
            margins.append(1.96 * se * 100.0)
        return max(margins) + 1.0 if margins else 15.0

    @staticmethod
    def _avg_dev(vd: dict) -> float:
        devs = [v["deviation"] for v in vd.values()]
        return sum(devs) / len(devs) if devs else 0.0

    @staticmethod
    def _summary_msg(vd: dict, margin: float, landed_msg: str) -> str:
        parts = []
        for ver, info in vd.items():
            icon = "PASS" if info["passed"] else "FAIL"
            parts.append(
                f"{ver}: {info['actual']:.1f}% (期望 {info['expected']:.1f}%, "
                f"偏差 {info['deviation']:.1f}pp) [{icon}]"
            )
        extra = f" | {landed_msg}" if landed_msg else ""
        return f"容错±{margin:.1f}pp | " + " | ".join(parts) + extra
