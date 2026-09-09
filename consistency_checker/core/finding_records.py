"""把对齐产物、跨资源冲突和运行时观测整理成检验记录。

每条记录对应一次被检出的不一致，并带上所处层次与
Sdecl（声明式控制面）、Sdp（数据面 Envoy）、Srt（运行时实测）摘要。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from consistency_checker.models.data_models import (
    DynamicBehavior,
    InconsistencyAnnotation,
    PolicyType,
    SeverityLevel,
    StaticPolicy,
)

LAYER_NAMES = {
    "layer1": "第一层 · 控制面 / 数据面全局",
    "layer2": "第二层 · 服务关系",
    "layer3": "第三层 · 配置资源",
}

LAYER_CATALOG = [
    {
        "id": "layer1",
        "name": LAYER_NAMES["layer1"],
        "what": (
            "比较同一功能在声明式配置 Sdecl 与 Envoy 数据面 Sdp 上是否对齐。"
            "不看运行时流量，只看控制面 YAML 与 sidecar dump 投影出的语义元组。"
        ),
        "checks": [
            {
                "type": "control_only",
                "name": "仅控制面",
                "desc": "YAML 声明了策略，Envoy dump 中没有对应语义（Pilot 未下发或 sidecar 未同步）。",
            },
            {
                "type": "data_only",
                "name": "仅数据面",
                "desc": "Envoy 存在规则，控制面未声明（残留配置或手工注入）。",
            },
            {
                "type": "mismatched",
                "name": "平面语义不匹配",
                "desc": "两侧都有配置，但 predicate / action / constraint 不一致。",
            },
            {
                "type": "partial_matched",
                "name": "部分匹配",
                "desc": "功能存在于两侧，部分字段对齐、部分超出容差 τ。",
            },
            {
                "type": "timeout_mismatch",
                "name": "超时不一致",
                "desc": "控制面与数据面的 timeout 约束不同。",
            },
        ],
    },
    {
        "id": "layer2",
        "name": LAYER_NAMES["layer2"],
        "what": (
            "在服务 / subset 关系上核对路由、流量分割、重试、超时、熔断是否按 Sdecl 生效。"
            "Srt 来自动态测试的实测行为；流量分割可同时对比期望权重与观测权重。"
        ),
        "checks": [
            {
                "type": "behavior_deviation",
                "name": "运行时行为偏差",
                "desc": "动态测试未通过：实测 Srt 与声明 Sdecl（及数据面 Sdp）不一致。",
            },
            {
                "type": "traffic_split_drift",
                "name": "流量分割漂移",
                "desc": "期望 subset 权重与运行时观测权重超出容差。",
            },
            {
                "type": "scope_mismatch",
                "name": "作用范围未覆盖",
                "desc": "策略声明的 subset 未被测试覆盖，无法确认运行时是否生效。",
            },
            {
                "type": "policy_not_verified",
                "name": "策略未被验证",
                "desc": "存在声明式策略，但没有对应的动态测试用例。",
            },
        ],
    },
    {
        "id": "layer3",
        "name": LAYER_NAMES["layer3"],
        "what": (
            "检查 VS / DR / Gateway / EnvoyFilter 等资源之间的引用是否闭合。"
            "单资源合法、组合后语义破裂的问题落在这一层（例如 VS 引用了不存在的 subset）。"
        ),
        "checks": [
            {
                "type": "missing_subset",
                "name": "缺失 subset",
                "desc": "VirtualService 引用的 subset 在 DestinationRule 中未定义。",
            },
            {
                "type": "gateway_unmatched",
                "name": "Gateway 未匹配",
                "desc": "VirtualService 绑定的 Gateway 在集群中不存在。",
            },
            {
                "type": "gateway_selector_empty",
                "name": "Gateway selector 为空",
                "desc": "Gateway 未设置 selector，无法绑定 ingress workload。",
            },
            {
                "type": "gateway_selector_conflict",
                "name": "Gateway selector 冲突",
                "desc": "多个 Gateway 使用相同 selector，入口选择不确定。",
            },
            {
                "type": "route_priority_conflict",
                "name": "路由优先级冲突",
                "desc": "同一 VirtualService 中两条 HTTP 规则匹配条件相同。",
            },
            {
                "type": "policy_conflict",
                "name": "策略冲突",
                "desc": "同一服务上存在多条互相覆盖的流量分配策略。",
            },
        ],
    },
]

_POLICY_TO_FUNCTION = {
    PolicyType.ROUTING: "routing",
    PolicyType.TRAFFIC_SPLIT: "traffic_shifting",
    PolicyType.RETRY: "retry",
    PolicyType.TIMEOUT: "timeout",
    PolicyType.CIRCUIT_BREAKER: "circuit_breaker",
    PolicyType.RATE_LIMIT: "rate_limit",
    PolicyType.FAULT_INJECTION: "fault_injection",
}

_FUNCTION_ALIASES = {
    "traffic_split": "traffic_shifting",
    "traffic_shifting": "traffic_shifting",
}

_CONFLICT_LAYER3 = {
    "missing_subset",
    "gateway_unmatched",
    "gateway_selector_empty",
    "gateway_selector_conflict",
    "route_priority_conflict",
}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_tuple(tuples: Any) -> Optional[Dict[str, Any]]:
    if not tuples:
        return None
    if isinstance(tuples, list):
        return tuples[0] if tuples and isinstance(tuples[0], dict) else None
    return tuples if isinstance(tuples, dict) else None


def _compact(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        out = {k: _compact(v) for k, v in obj.items() if v not in (None, "", [], {})}
        return out or {}
    if isinstance(obj, list):
        return [_compact(v) for v in obj if v not in (None, "", [], {})]
    return obj


def _fmt_match(predicate: Dict[str, Any]) -> str:
    if not predicate:
        return "match=*"
    uri = predicate.get("uri") or predicate.get("prefix") or predicate.get("path")
    if isinstance(uri, dict):
        kind = next(iter(uri), "")
        return f"match {kind}={uri.get(kind)}"
    if uri:
        return f"match uri={uri}"
    headers = predicate.get("headers")
    if headers:
        return f"match headers={headers}"
    method = predicate.get("method")
    if method:
        return f"match method={method}"
    return f"match={predicate}"


def _fmt_destinations(constraint: Dict[str, Any]) -> str:
    dests = constraint.get("destinations") or []
    if dests:
        parts = []
        for dest in dests:
            if not isinstance(dest, dict):
                continue
            name = dest.get("subset") or dest.get("host") or "?"
            weight = dest.get("weight")
            parts.append(f"{name} {weight}%" if weight is not None else str(name))
        if parts:
            return " → " + " / ".join(parts)
    weights = constraint.get("weights")
    if isinstance(weights, dict) and weights:
        return " → " + " / ".join(f"{k} {v}%" for k, v in weights.items())
    return ""


def human_summary(tup: Optional[Dict[str, Any]]) -> str:
    if not tup:
        return ""
    ftype = tup.get("function_type") or ""
    pred = tup.get("predicate") or {}
    action = tup.get("action") or {}
    cons = tup.get("constraint") or {}
    bits = [_fmt_match(pred)] if pred else []
    dest = _fmt_destinations(cons)
    if dest:
        bits.append(dest.strip())
    action_type = action.get("type")
    if action_type and action_type not in ("route", "observe"):
        bits.append(f"action={action_type}")
    for key in ("timeout", "timeout_seconds", "attempts", "retry_on", "max_connections",
                "consecutive_errors", "abort_percent", "delay"):
        if cons.get(key) is not None:
            bits.append(f"{key}={cons[key]}")
    if not bits:
        bits.append(ftype or "semantic tuple")
    return " · ".join(str(b) for b in bits if b)


def summarize_tuple(tup: Optional[Dict[str, Any]], plane: str = "") -> Optional[Dict[str, Any]]:
    if not tup:
        return None
    pred = tup.get("predicate") if isinstance(tup.get("predicate"), dict) else {}
    action = tup.get("action") if isinstance(tup.get("action"), dict) else {}
    scope = tup.get("scope") if isinstance(tup.get("scope"), dict) else {}
    constraint = tup.get("constraint") if isinstance(tup.get("constraint"), dict) else {}
    return {
        "tuple_id": tup.get("tuple_id"),
        "function_type": tup.get("function_type") or "",
        "plane": tup.get("plane") or plane,
        "predicate": _compact(pred) or {},
        "action": _compact(action) or {},
        "scope": _compact(scope) or {},
        "constraint": _compact(constraint) or {},
        "source_resources": list(tup.get("source_resources") or []),
        "summary": human_summary(tup),
    }


def summarize_runtime(behavior: Optional[DynamicBehavior]) -> Optional[Dict[str, Any]]:
    if behavior is None:
        return None
    ftype = behavior.policy_type.value if isinstance(behavior.policy_type, PolicyType) else str(behavior.policy_type)
    expected = behavior.expected_behavior or {}
    actual = behavior.actual_behavior or {}
    verified = bool(behavior.is_verified)
    status = "通过" if verified else "未通过"
    summary = (
        f"用例 {behavior.test_case_id} {status} · "
        f"期望 { _compact(expected) or '{}' } · "
        f"实测 { _compact(actual) or '{}' }"
    )
    subset = (
        (behavior.test_params or {}).get("subset")
        or (behavior.test_params or {}).get("version")
    )
    return {
        "tuple_id": f"runtime.{behavior.test_case_id}",
        "function_type": ftype,
        "plane": "runtime",
        "predicate": _compact(behavior.test_params) or {},
        "action": {"type": "observe"},
        "scope": _compact({
            "service": behavior.target_service,
            "source": behavior.source_service,
            "subsets": [subset] if subset else [],
        }) or {},
        "constraint": _compact(actual) or {},
        "summary": summary,
        "test_case_id": behavior.test_case_id,
        "verified": verified,
        "expected": _compact(expected) or {},
        "actual": _compact(actual) or {},
    }


def sdecl_from_policy(policy: StaticPolicy) -> Dict[str, Any]:
    rules = policy.rules or {}
    tup = {
        "tuple_id": policy.config_name or policy.policy_id,
        "function_type": _POLICY_TO_FUNCTION.get(policy.policy_type, policy.policy_type.value),
        "plane": "control_plane",
        "predicate": rules.get("predicate") or policy.match_conditions or {},
        "action": rules.get("action") or {"type": policy.policy_type.value},
        "scope": {
            "service": policy.target_service,
            "namespace": policy.namespace,
            "subsets": list(policy.applies_to or []),
        },
        "constraint": rules.get("constraint") or {},
    }
    return summarize_tuple(tup, plane="control_plane") or tup


def _meta(raw: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(raw, dict):
        return None, None, None
    kind = raw.get("kind")
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    name = meta.get("name")
    ns = meta.get("namespace")
    if kind and name:
        return str(kind), str(name), str(ns) if ns else None
    for key in ("virtual_service", "destination_rule", "envoy_filter", "gateway", "service_entry"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            return _meta(nested)
    return None, None, None


def resource_from_pair(pair: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    for key in ("control_plane", "data_plane"):
        model = pair.get(key) or {}
        raw = model.get("raw_config") if isinstance(model, dict) else None
        kind, name, ns = _meta(raw)
        if kind or name:
            return kind, name, ns or pair.get("namespace")
    for tup in (pair.get("control_tuples") or []) + (pair.get("data_tuples") or []):
        if not isinstance(tup, dict):
            continue
        for ref in tup.get("source_resources") or []:
            if isinstance(ref, str) and "/" in ref:
                kind, name = ref.split("/", 1)
                return kind, name, pair.get("namespace")
            if isinstance(ref, dict):
                kind, name, ns = _meta(ref)
                if kind or name:
                    return kind, name, ns
    ftype = pair.get("function_type") or ""
    kind_guess = {
        "routing": "VirtualService",
        "traffic_shifting": "VirtualService",
        "traffic_split": "VirtualService",
        "retry": "VirtualService",
        "timeout": "VirtualService",
        "circuit_breaker": "DestinationRule",
        "load_balancing": "DestinationRule",
        "fault_injection": "VirtualService",
        "rate_limit": "EnvoyFilter",
        "tls": "PeerAuthentication",
    }.get(str(ftype))
    return kind_guess, None, pair.get("namespace")


def resource_from_conflict(conflict: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    ns = conflict.get("namespace")
    if conflict.get("virtualservice"):
        return "VirtualService", str(conflict["virtualservice"]), ns
    if conflict.get("gateway"):
        return "Gateway", str(conflict["gateway"]), ns
    gateways = conflict.get("gateways")
    if isinstance(gateways, list) and gateways:
        return "Gateway", ", ".join(str(g) for g in gateways), ns
    return None, None, ns


def subsets_from_tuple(tup: Optional[Dict[str, Any]]) -> List[str]:
    if not tup:
        return []
    scope = tup.get("scope") or {}
    found = []
    for item in _as_list(scope.get("subsets")):
        if item:
            found.append(str(item))
    cons = tup.get("constraint") or {}
    for dest in cons.get("destinations") or []:
        if isinstance(dest, dict) and dest.get("subset"):
            found.append(str(dest["subset"]))
    weights = cons.get("weights")
    if isinstance(weights, dict):
        found.extend(str(k) for k in weights.keys() if k)
    return sorted(set(found))


def subsets_from_pair(pair: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    for tup in (pair.get("control_tuples") or []) + (pair.get("data_tuples") or []):
        if isinstance(tup, dict):
            found.extend(subsets_from_tuple(tup))
    return sorted(set(found))


def _severity(value: Any, default: SeverityLevel = SeverityLevel.MEDIUM) -> SeverityLevel:
    if isinstance(value, SeverityLevel):
        return value
    text = str(value or "").lower()
    mapping = {
        "critical": SeverityLevel.CRITICAL,
        "high": SeverityLevel.HIGH,
        "medium": SeverityLevel.MEDIUM,
        "low": SeverityLevel.LOW,
        "info": SeverityLevel.INFO,
    }
    return mapping.get(text, default)


def build_finding(
    *,
    finding_id: str,
    inconsistency_type: str,
    severity: Any,
    description: str,
    layer: str,
    affected_services: Optional[Iterable[str]] = None,
    affected_subsets: Optional[Iterable[str]] = None,
    affected_policies: Optional[Iterable[str]] = None,
    resource_kind: Optional[str] = None,
    resource_name: Optional[str] = None,
    resource_namespace: Optional[str] = None,
    function_type: Optional[str] = None,
    alignment_status: Optional[str] = None,
    s_decl: Optional[Dict[str, Any]] = None,
    s_dp: Optional[Dict[str, Any]] = None,
    s_rt: Optional[Dict[str, Any]] = None,
    root_cause: Optional[str] = None,
    suggestions: Optional[Iterable[str]] = None,
    static_expectation: Optional[Dict[str, Any]] = None,
    dynamic_observation: Optional[Dict[str, Any]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> InconsistencyAnnotation:
    services = [s for s in (affected_services or []) if s]
    subsets = [s for s in (affected_subsets or []) if s]
    return InconsistencyAnnotation(
        inconsistency_id=finding_id,
        inconsistency_type=inconsistency_type,
        severity=_severity(severity),
        description=description,
        affected_policies=list(affected_policies or []),
        affected_services=services,
        affected_subsets=subsets,
        layer=layer,
        layer_name=LAYER_NAMES.get(layer, layer),
        resource_kind=resource_kind,
        resource_name=resource_name,
        resource_namespace=resource_namespace,
        function_type=function_type,
        alignment_status=alignment_status,
        s_decl=s_decl,
        s_dp=s_dp,
        s_rt=s_rt,
        static_expectation=static_expectation or {},
        dynamic_observation=dynamic_observation or {},
        details=details or {},
        root_cause=root_cause,
        suggestions=list(suggestions or []),
        impact_scope=services + subsets,
    )


def index_pairs(artifact: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for pair in artifact.get("pairs") or []:
        if not isinstance(pair, dict):
            continue
        svc = pair.get("service_name") or ""
        ftype = _FUNCTION_ALIASES.get(pair.get("function_type") or "", pair.get("function_type") or "")
        if svc and ftype:
            indexed[f"{svc}|{ftype}"] = pair
            indexed[f"{svc}|{pair.get('function_type')}"] = pair
    return indexed


def lookup_pair(
    pairs: Dict[str, Dict[str, Any]],
    service: str,
    function_type: Optional[str] = None,
    policy_type: Optional[PolicyType] = None,
) -> Optional[Dict[str, Any]]:
    candidates = []
    if function_type:
        candidates.append(_FUNCTION_ALIASES.get(function_type, function_type))
        candidates.append(function_type)
    if policy_type:
        mapped = _POLICY_TO_FUNCTION.get(policy_type)
        if mapped:
            candidates.append(mapped)
        candidates.append(policy_type.value)
    for ftype in candidates:
        hit = pairs.get(f"{service}|{ftype}")
        if hit:
            return hit
    return None


def matching_behaviors(
    behaviors: List[DynamicBehavior],
    service: str,
    function_type: Optional[str] = None,
    policy_type: Optional[PolicyType] = None,
) -> List[DynamicBehavior]:
    wanted = set()
    if function_type:
        wanted.add(_FUNCTION_ALIASES.get(function_type, function_type))
    if policy_type:
        wanted.add(_POLICY_TO_FUNCTION.get(policy_type, policy_type.value))
        wanted.add(policy_type.value)
    hits = []
    for behavior in behaviors:
        if behavior.target_service != service:
            continue
        btype = behavior.policy_type.value if isinstance(behavior.policy_type, PolicyType) else str(behavior.policy_type)
        mapped = _POLICY_TO_FUNCTION.get(behavior.policy_type, btype) if isinstance(behavior.policy_type, PolicyType) else btype
        if not wanted or btype in wanted or mapped in wanted:
            hits.append(behavior)
    return hits


def _alignment_type(status: str, diffs: List[Dict[str, Any]]) -> str:
    if status in {"control_only", "data_only", "mismatched", "partial_matched"}:
        if status == "mismatched":
            kinds = {str(d.get("kind") or "") for d in diffs}
            if "timeout" in kinds or any("timeout" in str(d.get("description") or "").lower() for d in diffs):
                return "timeout_mismatch"
        return status
    if diffs:
        kind = str(diffs[0].get("kind") or "mismatch")
        return f"alignment_{kind}"
    return "mismatched"


def _alignment_severity(status: str, diffs: List[Dict[str, Any]]) -> SeverityLevel:
    if status in {"mismatched", "control_only", "data_only"}:
        return SeverityLevel.HIGH
    if any(d.get("kind") == "discrete" for d in diffs):
        return SeverityLevel.HIGH
    return SeverityLevel.MEDIUM


def collect_alignment_findings(
    artifact: Dict[str, Any],
    behaviors: Optional[List[DynamicBehavior]] = None,
) -> List[InconsistencyAnnotation]:
    findings: List[InconsistencyAnnotation] = []
    behaviors = behaviors or []
    for idx, pair in enumerate(artifact.get("pairs") or [], start=1):
        if not isinstance(pair, dict):
            continue
        status = str(pair.get("alignment_status") or "")
        if status in {"matched", ""}:
            continue
        diffs = [d for d in (pair.get("differences") or []) if isinstance(d, dict)]
        svc = pair.get("service_name") or ""
        ftype = pair.get("function_type") or ""
        ns = pair.get("namespace")
        kind, name, rns = resource_from_pair(pair)
        s_decl = summarize_tuple(_first_tuple(pair.get("control_tuples")), plane="control_plane")
        s_dp = summarize_tuple(_first_tuple(pair.get("data_tuples")), plane="data_plane")
        runtime = matching_behaviors(behaviors, svc, function_type=ftype)
        failed = [b for b in runtime if not b.is_verified]
        s_rt = summarize_runtime(failed[0] if failed else (runtime[0] if runtime else None))
        itype = _alignment_type(status, diffs)
        desc = diffs[0].get("description") if diffs else ""
        if not desc:
            desc = f"服务 {svc} 的 {ftype} 对齐状态为 {status}"
        findings.append(build_finding(
            finding_id=f"inc_align_{idx}_{svc}_{ftype}",
            inconsistency_type=itype,
            severity=_alignment_severity(status, diffs),
            description=desc,
            layer="layer1",
            affected_services=[svc] if svc else [],
            affected_subsets=subsets_from_pair(pair),
            resource_kind=kind,
            resource_name=name,
            resource_namespace=rns or ns,
            function_type=ftype,
            alignment_status=status,
            s_decl=s_decl,
            s_dp=s_dp,
            s_rt=s_rt,
            root_cause=f"控制面 Sdecl 与数据面 Sdp 对齐状态为 {status}",
            suggestions=[
                "对照 Sdecl 与 Sdp 的 predicate / action / constraint",
                "确认 istiod 已将最新配置下发到 sidecar",
            ],
            static_expectation={"alignment_status": status, "control": diffs[0].get("control") if diffs else None},
            dynamic_observation={"data": diffs[0].get("data") if diffs else None},
            details={"differences": diffs, "pair_key": f"{ns}.{svc}.{ftype}"},
        ))
    return findings


def collect_conflict_findings(artifact: Dict[str, Any]) -> List[InconsistencyAnnotation]:
    findings: List[InconsistencyAnnotation] = []
    for idx, conflict in enumerate(artifact.get("conflicts") or [], start=1):
        if not isinstance(conflict, dict):
            continue
        ctype = str(conflict.get("type") or "config_conflict")
        kind, name, ns = resource_from_conflict(conflict)
        svc = conflict.get("service") or ""
        subset = conflict.get("missing_subset")
        subsets = [str(subset)] if subset else list(conflict.get("available_subsets") or [])
        if ctype in _CONFLICT_LAYER3:
            layer = "layer3"
        else:
            layer = "layer3"
        findings.append(build_finding(
            finding_id=f"inc_conflict_{idx}_{ctype}",
            inconsistency_type=ctype,
            severity=conflict.get("severity") or "high",
            description=conflict.get("description") or f"配置冲突 {ctype}",
            layer=layer,
            affected_services=[svc] if svc else [],
            affected_subsets=subsets,
            resource_kind=kind,
            resource_name=name,
            resource_namespace=ns,
            function_type="routing" if "route" in ctype or ctype == "missing_subset" else None,
            s_decl=summarize_tuple({
                "tuple_id": f"decl.{kind}.{name}",
                "function_type": "routing",
                "plane": "control_plane",
                "predicate": {},
                "action": {"type": ctype},
                "scope": {"service": svc, "namespace": ns, "subsets": subsets},
                "constraint": {k: v for k, v in conflict.items() if k not in {"description", "type", "severity"}},
            }, plane="control_plane"),
            root_cause="跨资源引用或选择器组合后语义破裂",
            suggestions=[
                "核对 VirtualService 引用的 Gateway / subset 是否真实存在",
                "合并重复匹配条件或冲突的 Gateway selector",
            ],
            details=conflict,
        ))
    return findings


def attach_tuples(
    finding: InconsistencyAnnotation,
    *,
    pair: Optional[Dict[str, Any]] = None,
    policy: Optional[StaticPolicy] = None,
    behavior: Optional[DynamicBehavior] = None,
) -> InconsistencyAnnotation:
    if pair:
        if finding.s_decl is None:
            finding.s_decl = summarize_tuple(_first_tuple(pair.get("control_tuples")), plane="control_plane")
        if finding.s_dp is None:
            finding.s_dp = summarize_tuple(_first_tuple(pair.get("data_tuples")), plane="data_plane")
        if not finding.resource_kind and not finding.resource_name:
            kind, name, ns = resource_from_pair(pair)
            finding.resource_kind = kind
            finding.resource_name = name
            finding.resource_namespace = ns or finding.resource_namespace
        if not finding.affected_subsets:
            finding.affected_subsets = subsets_from_pair(pair)
        finding.function_type = finding.function_type or pair.get("function_type")
        finding.alignment_status = finding.alignment_status or pair.get("alignment_status")
        finding.resource_namespace = finding.resource_namespace or pair.get("namespace")
    if policy and finding.s_decl is None:
        finding.s_decl = sdecl_from_policy(policy)
        finding.function_type = finding.function_type or _POLICY_TO_FUNCTION.get(policy.policy_type, policy.policy_type.value)
        if not finding.resource_name:
            finding.resource_name = policy.config_name
            finding.resource_kind = finding.resource_kind or policy.config_type
        if not finding.affected_subsets:
            finding.affected_subsets = list(policy.applies_to or [])
    if behavior and finding.s_rt is None:
        finding.s_rt = summarize_runtime(behavior)
        subset = (behavior.test_params or {}).get("subset") or (behavior.test_params or {}).get("version")
        if subset and subset not in finding.affected_subsets:
            finding.affected_subsets.append(str(subset))
    finding.layer_name = finding.layer_name or LAYER_NAMES.get(finding.layer, finding.layer)
    return finding


def checks_performed() -> List[Dict[str, Any]]:
    rows = []
    for layer in LAYER_CATALOG:
        for check in layer["checks"]:
            rows.append({
                "layer": layer["id"],
                "layer_name": layer["name"],
                "type": check["type"],
                "name": check["name"],
                "description": check["desc"],
            })
    return rows
