"""把动态用例收成「预期 / 实际 / 一致性」视图，给 Web 和 API 用。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from istio_Dynamic_Test.internal.models.testcase import PipelineResult, TestCase, ValidationStatus


_POLICY_HINT = {
    "routing": "请求应落到声明的目标服务/版本",
    "traffic_split": "实测分流比例应落在声明权重的容差内",
    "retry": "注入 5xx 后应看到声明的重试次数生效",
    "timeout": "慢响应应在声明超时内失败（如 504/UT）",
    "circuit_breaker": "连续错误或打满连接池后应出现熔断特征",
    "rate_limit": "基线应几乎全通过；高压应出现 429",
    "fault_injection": "应观测到声明的 abort/delay 效果",
}


def serialize_pipeline_results(results: Iterable[PipelineResult]) -> List[Dict[str, Any]]:
    return [serialize_pipeline_result(pr) for pr in results]


def serialize_pipeline_result(pr: PipelineResult) -> Dict[str, Any]:
    tc = pr.test_case
    matrix = dict(tc.metadata or {})
    expected_raw = _expected_raw(tc, matrix)
    actual_raw = _actual_raw(pr)
    status = "skipped"
    summary = ""
    details: List[Dict[str, Any]] = []
    if pr.validation:
        status = pr.validation.overall_status.value
        summary = pr.validation.summary or ""
        for item in pr.validation.details or []:
            details.append({
                "dimension": item.dimension,
                "status": item.status.value if isinstance(item.status, ValidationStatus) else str(item.status),
                "message": item.message or "",
                "expected": _jsonish(item.expected),
                "actual": _jsonish(item.actual),
            })
    return _view(
        case_id=tc.case_id,
        description=tc.description or tc.name,
        policy_types=[p.value for p in (tc.policy_types or [])],
        status=status,
        summary=summary or _default_summary(status),
        request=_request_from_case(tc, matrix),
        expected_raw=expected_raw,
        actual_raw=actual_raw,
        details=details,
    )


def cases_from_matrix(matrix: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in (matrix or {}).get("test_cases") or []:
        if not isinstance(raw, dict):
            continue
        policies = list(raw.get("test_strategies") or [])
        expected_raw = dict(raw.get("expected_outcome") or {})
        out.append(_view(
            case_id=str(raw.get("case_id") or ""),
            description=str(raw.get("description") or raw.get("name") or ""),
            policy_types=policies,
            status="pending",
            summary="尚未打入对应流量",
            request=dict(raw.get("request_params") or {}),
            expected_raw=expected_raw,
            actual_raw={},
            details=[],
            extra={"load_params": raw.get("load_params") or {}},
        ))
    return out


def cases_from_report(
    report: Optional[Dict[str, Any]],
    matrix: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    by_id = {
        str(item.get("case_id")): item
        for item in (matrix or {}).get("test_cases") or []
        if isinstance(item, dict) and item.get("case_id")
    }
    out: List[Dict[str, Any]] = []
    for case in (report or {}).get("cases") or []:
        if not isinstance(case, dict):
            continue
        mid = by_id.get(str(case.get("case_id")) or "") or {}
        validation = case.get("validation") or {}
        execution = case.get("execution") or {}
        expected_raw = dict(mid.get("expected_outcome") or {})
        for detail in validation.get("details") or []:
            if not isinstance(detail, dict):
                continue
            exp = detail.get("expected")
            if isinstance(exp, dict) and exp and all(isinstance(v, (int, float)) for v in exp.values()):
                expected_raw.setdefault("distribution", exp)
            elif exp not in (None, "", {}, []):
                expected_raw.setdefault(detail.get("dimension") or "期望", exp)
        actual_raw = _actual_from_execution(execution)
        for detail in validation.get("details") or []:
            if not isinstance(detail, dict):
                continue
            if detail.get("actual") not in (None, "", {}, []):
                actual_raw.setdefault(detail.get("dimension") or "观测", detail.get("actual"))
        req = dict(mid.get("request_params") or {})
        meta = (execution.get("metadata") or {}) if isinstance(execution, dict) else {}
        if meta.get("request_url"):
            req.setdefault("url", meta.get("request_url"))
        details = []
        for detail in validation.get("details") or []:
            if not isinstance(detail, dict):
                continue
            details.append({
                "dimension": detail.get("dimension") or "",
                "status": detail.get("status") or "",
                "message": detail.get("message") or "",
                "expected": _jsonish(detail.get("expected")),
                "actual": _jsonish(detail.get("actual")),
            })
        out.append(_view(
            case_id=str(case.get("case_id") or ""),
            description=str(case.get("description") or mid.get("description") or ""),
            policy_types=list(case.get("policy_types") or mid.get("test_strategies") or []),
            status=str(validation.get("overall_status") or "skipped"),
            summary=str(validation.get("summary") or ""),
            request=req,
            expected_raw=expected_raw,
            actual_raw=actual_raw,
            details=details,
        ))
    return out


def _view(
    *,
    case_id: str,
    description: str,
    policy_types: List[str],
    status: str,
    summary: str,
    request: Dict[str, Any],
    expected_raw: Dict[str, Any],
    actual_raw: Dict[str, Any],
    details: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    hints = [_POLICY_HINT[p] for p in policy_types if p in _POLICY_HINT]
    payload = {
        "case_id": case_id,
        "description": description,
        "policy_types": policy_types,
        "status": status,
        "summary": summary or _default_summary(status),
        "consistency": _consistency_label(status),
        "hint": hints[0] if hints else "对照声明期望与本次打流观测",
        "request": {k: v for k, v in request.items() if v not in (None, "", {}, [])},
        "expected_rows": _expected_rows(expected_raw, policy_types),
        "actual_rows": _actual_rows(actual_raw, status, summary),
        "details": details,
    }
    if extra:
        payload.update(extra)
    return payload


def _expected_raw(tc: TestCase, matrix: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict((matrix.get("expected_outcome") or {}) if isinstance(matrix, dict) else {})
    if tc.expected_distribution:
        raw["distribution"] = dict(tc.expected_distribution)
    if tc.expected_destination:
        raw["destination"] = tc.expected_destination
    if tc.expected_circuit_breaker_threshold is not None:
        raw.setdefault("circuit_breaker_threshold", tc.expected_circuit_breaker_threshold)
    if tc.expected_retry_attempts is not None:
        raw.setdefault("retry_attempts", tc.expected_retry_attempts)
    if tc.expected_fault_code is not None:
        raw.setdefault("fault_code", tc.expected_fault_code)
    if tc.rate_limit_expect:
        raw["rate_limit"] = dict(tc.rate_limit_expect)
    if tc.margin_of_error:
        raw.setdefault("margin_of_error", tc.margin_of_error)
    return raw


def _actual_raw(pr: PipelineResult) -> Dict[str, Any]:
    if not pr.execution:
        return {}
    return _actual_from_execution({
        "status_codes": pr.execution.status_codes,
        "total_requests": pr.execution.total_requests,
        "success_rate": pr.execution.success_rate,
        "avg_response_time": pr.execution.avg_response_time,
        "error_count": pr.execution.error_count,
        "metadata": pr.execution.metadata or {},
    })


def _actual_from_execution(execution: Dict[str, Any]) -> Dict[str, Any]:
    meta = execution.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    actual: Dict[str, Any] = {}
    if execution.get("status_codes"):
        actual["status_codes"] = execution.get("status_codes")
    if execution.get("total_requests") is not None:
        actual["total_requests"] = execution.get("total_requests")
    if execution.get("success_rate") is not None:
        actual["success_rate"] = execution.get("success_rate")
    if execution.get("avg_response_time") is not None:
        actual["avg_response_time"] = execution.get("avg_response_time")
    if execution.get("error_count") is not None:
        actual["error_count"] = execution.get("error_count")
    for key in ("version_percentages", "version_counts", "landed_services", "observer", "request_url"):
        if meta.get(key) not in (None, "", {}, []):
            actual[key] = meta.get(key)
    return actual


def _expected_rows(raw: Dict[str, Any], policies: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    dist = raw.get("distribution")
    if isinstance(dist, dict) and dist:
        rows.append({"label": "分流权重", "value": _fmt_weights(dist)})
    dest = raw.get("destination")
    if dest:
        rows.append({"label": "目标", "value": str(dest)})
    if raw.get("retry_attempts") is not None:
        rows.append({"label": "重试次数", "value": str(raw.get("retry_attempts"))})
    if raw.get("timeout_s") is not None:
        rows.append({"label": "超时", "value": f"{raw.get('timeout_s')}s"})
    if raw.get("circuit_breaker_threshold") is not None:
        rows.append({"label": "熔断阈值 consecutive_5xx", "value": str(raw.get("circuit_breaker_threshold"))})
    rl = raw.get("rate_limit")
    if isinstance(rl, dict) and rl:
        mode = str(rl.get("mode") or "")
        if mode == "should_pass_all":
            rows.append({"label": "限流", "value": f"基线应几乎全通过（最多 {rl.get('max_429', 1)} 次 429）"})
        elif mode == "should_see_limits":
            rows.append({"label": "限流", "value": f"高压下应出现 429（至少 {rl.get('min_429', 1)} 次）"})
        else:
            rows.append({"label": "限流", "value": _fmt_value(rl)})
    if raw.get("fault_code") is not None:
        rows.append({"label": "故障码", "value": str(raw.get("fault_code"))})
    if raw.get("margin_of_error") is not None and dist:
        margin = raw.get("margin_of_error")
        try:
            pct = float(margin)
            rows.append({"label": "容差", "value": f"±{pct * 100:.0f}pp" if pct <= 1 else f"±{pct:.0f}pp"})
        except (TypeError, ValueError):
            rows.append({"label": "容差", "value": str(margin)})
    if not rows:
        hint = next((_POLICY_HINT[p] for p in policies if p in _POLICY_HINT), "")
        if hint:
            rows.append({"label": "期望", "value": hint})
        else:
            rows.append({"label": "期望", "value": "与声明语义一致"})
    return rows


def _actual_rows(raw: Dict[str, Any], status: str, summary: str) -> List[Dict[str, str]]:
    if status in {"pending"}:
        return [{"label": "观测", "value": "尚未打入对应流量"}]
    if status == "skipped" and not raw:
        return [{"label": "观测", "value": summary or "未执行（安全开关未打开或无法诱发）"}]
    rows: List[Dict[str, str]] = []
    if raw.get("version_percentages"):
        rows.append({"label": "实测分流", "value": _fmt_weights(raw.get("version_percentages"))})
    if raw.get("landed_services"):
        rows.append({"label": "落到的服务", "value": _fmt_counts(raw.get("landed_services"))})
    if raw.get("status_codes"):
        rows.append({"label": "状态码", "value": _fmt_counts(raw.get("status_codes"))})
    if raw.get("total_requests") is not None:
        rows.append({"label": "请求数", "value": str(raw.get("total_requests"))})
    rate = raw.get("success_rate")
    if rate is not None:
        try:
            num = float(rate)
            rows.append({"label": "成功率", "value": f"{num:.1f}%" if num > 1 else f"{num * 100:.1f}%"})
        except (TypeError, ValueError):
            rows.append({"label": "成功率", "value": str(rate)})
    lat = raw.get("avg_response_time")
    if lat is not None:
        try:
            ms = float(lat)
            if ms < 10:
                ms *= 1000
            rows.append({"label": "平均时延", "value": f"{ms:.0f} ms"})
        except (TypeError, ValueError):
            pass
    if raw.get("observer"):
        rows.append({"label": "观测来源", "value": str(raw.get("observer"))})
    if not rows:
        rows.append({"label": "观测", "value": summary or "无运行时数据"})
    return rows


def _request_from_case(tc: TestCase, matrix: Dict[str, Any]) -> Dict[str, Any]:
    params = dict((matrix.get("request_params") or {}) if isinstance(matrix, dict) else {})
    if tc.host:
        params.setdefault("host", tc.host)
    if tc.path:
        params.setdefault("path", tc.path)
    return params


def _consistency_label(status: str) -> str:
    return {
        "passed": "动态一致",
        "failed": "动态不一致",
        "warning": "部分观测 / 证据不足",
        "skipped": "未验证（已跳过）",
        "pending": "尚未打流",
    }.get(status, status or "未判定")


def _default_summary(status: str) -> str:
    return {
        "passed": "预期行为与实际观测一致",
        "failed": "实际观测与预期行为不一致",
        "warning": "打流完成，但熔断/日志等证据不完整",
        "skipped": "未执行，无法做动态一致性判定",
        "pending": "尚未打入对应流量",
    }.get(status, "")


def _fmt_weights(weights: Any) -> str:
    if not isinstance(weights, dict):
        return _fmt_value(weights)
    bits = []
    for key, val in weights.items():
        try:
            num = float(val)
            if num <= 1:
                num *= 100
            bits.append(f"{key} {num:.0f}%")
        except (TypeError, ValueError):
            bits.append(f"{key} {val}")
    return " · ".join(bits) or "—"


def _fmt_counts(counts: Any) -> str:
    if not isinstance(counts, dict):
        return _fmt_value(counts)
    return " · ".join(f"{k}×{v}" for k, v in counts.items()) or "—"


def _fmt_value(val: Any) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, dict):
        if all(isinstance(v, (int, float)) for v in val.values()):
            return _fmt_weights(val) if any(float(v) <= 100 for v in val.values()) else _fmt_counts(val)
        return ", ".join(f"{k}={_fmt_value(v)}" for k, v in val.items() if v not in (None, "", {}))
    if isinstance(val, (list, tuple)):
        return ", ".join(_fmt_value(v) for v in val)
    return str(val)


def _jsonish(val: Any) -> Any:
    if isinstance(val, dict):
        return {str(k): _jsonish(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_jsonish(v) for v in val]
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    return str(val)
