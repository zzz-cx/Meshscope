"""论文语义元组 S = ⟨predicate, action, scope, constraint⟩。

FunctionModel 是平面上的功能聚合；对外比较、动态期望、三层图标注
都投影到本元组，避免三套模型并行。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from istio_config_parser.models.function_models import (
    AnyFunctionModel,
    CircuitBreakerFunctionModel,
    FaultInjectionFunctionModel,
    FunctionType,
    LoadBalancingFunctionModel,
    RateLimitFunctionModel,
    RetryFunctionModel,
    RoutingFunctionModel,
    TimeoutFunctionModel,
    TrafficShiftingFunctionModel,
    _is_unlimited_threshold,
)


def parse_duration_seconds(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    try:
        if text.endswith("ms"):
            return float(text[:-2]) / 1000.0
        if text.endswith("s"):
            return float(text[:-1])
        if text.endswith("m"):
            return float(text[:-1]) * 60.0
        if text.endswith("h"):
            return float(text[:-1]) * 3600.0
        return float(text)
    except ValueError:
        return None


def normalize_host(host: Optional[str]) -> str:
    if not host:
        return ""
    name = host.strip()
    if ".svc.cluster.local" in name:
        name = name.split(".svc.cluster.local", 1)[0]
    if "." in name:
        name = name.split(".", 1)[0]
    return name


def _clean(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [_clean(v) for v in obj if v not in (None, "", [], {})]
    return obj


@dataclass
class SemanticTuple:
    """S = ⟨predicate, action, scope, constraint⟩"""

    tuple_id: str
    function_type: str
    predicate: Dict[str, Any] = field(default_factory=dict)
    action: Dict[str, Any] = field(default_factory=dict)
    scope: Dict[str, Any] = field(default_factory=dict)
    constraint: Dict[str, Any] = field(default_factory=dict)
    plane: str = ""
    source_resources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["predicate"] = _clean(self.predicate) or {}
        data["action"] = _clean(self.action) or {}
        data["scope"] = _clean(self.scope) or {}
        data["constraint"] = _clean(self.constraint) or {}
        return data


def function_model_to_tuples(model: AnyFunctionModel) -> List[SemanticTuple]:
    ns = getattr(model, "namespace", "default") or "default"
    svc = normalize_host(getattr(model, "service_name", ""))
    plane = getattr(model, "plane_type", None)
    plane_val = plane.value if hasattr(plane, "value") else str(plane or "")
    ftype = model.function_type.value if hasattr(model.function_type, "value") else str(model.function_type)
    base_scope = {"namespace": ns, "service": svc}
    tuples: List[SemanticTuple] = []

    if isinstance(model, RoutingFunctionModel):
        for idx, route in enumerate(model.routes or []):
            dests = route.get("destinations") or []
            subsets = [d.get("subset") for d in dests if d.get("subset")]
            tuples.append(SemanticTuple(
                tuple_id=f"{ns}.{svc}.routing.{idx}",
                function_type=FunctionType.ROUTING.value,
                predicate=_clean(route.get("match") or {}) or {},
                action={"type": "route"},
                scope={**base_scope, "hosts": list(model.hosts or []), "gateways": list(model.gateways or []), "subsets": subsets},
                constraint={
                    "destinations": dests,
                    "weights": {normalize_host(d.get("subset") or d.get("host")): d.get("weight", 100) for d in dests},
                    "priority": route.get("priority", idx),
                },
                plane=plane_val,
            ))
        if not model.routes:
            tuples.append(SemanticTuple(
                tuple_id=f"{ns}.{svc}.routing.0",
                function_type=FunctionType.ROUTING.value,
                action={"type": "route"},
                scope={**base_scope, "hosts": list(model.hosts or []), "gateways": list(model.gateways or [])},
                plane=plane_val,
            ))
        return tuples

    if isinstance(model, TrafficShiftingFunctionModel):
        dests = [d.to_dict() if hasattr(d, "to_dict") else d for d in (model.destinations or [])]
        subsets = [s.get("name") for s in (model.subsets or []) if isinstance(s, dict)]
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.traffic_shifting",
            function_type=FunctionType.TRAFFIC_SHIFTING.value,
            action={"type": "traffic_shifting"},
            scope={**base_scope, "gateways": list(model.gateways or []), "subsets": subsets},
            constraint={
                "destinations": dests,
                "weights": {normalize_host(d.get("subset") or d.get("host")): d.get("weight", 0) for d in dests},
            },
            plane=plane_val,
        ))
        return tuples

    if isinstance(model, RetryFunctionModel):
        policy = model.retry_policy.to_dict() if model.retry_policy else {}
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.retry",
            function_type=FunctionType.RETRY.value,
            action={"type": "retry"},
            scope=base_scope,
            constraint={
                "attempts": policy.get("attempts"),
                "per_try_timeout_s": parse_duration_seconds(policy.get("per_try_timeout")),
                "retry_on": policy.get("retry_on"),
            },
            plane=plane_val,
        ))
        return tuples

    if isinstance(model, TimeoutFunctionModel):
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.timeout",
            function_type=FunctionType.TIMEOUT.value,
            action={"type": "timeout"},
            scope=base_scope,
            constraint={
                "timeout_s": parse_duration_seconds(model.timeout),
                "idle_timeout_s": parse_duration_seconds(model.idle_timeout),
            },
            plane=plane_val,
        ))
        return tuples

    if isinstance(model, CircuitBreakerFunctionModel):
        if not model.has_declared_policy():
            return tuples
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.circuit_breaker",
            function_type=FunctionType.CIRCUIT_BREAKER.value,
            action={"type": "circuit_breaker"},
            scope=base_scope,
            constraint={
                "connection_pool": model.connection_pool.to_dict() if model.connection_pool else None,
                "outlier_detection": model.outlier_detection.to_dict() if model.outlier_detection else None,
            },
            plane=plane_val,
        ))
        return tuples

    if isinstance(model, RateLimitFunctionModel):
        for idx, rule in enumerate(model.rules or []):
            match = rule.match_conditions.to_dict() if getattr(rule, "match_conditions", None) else {}
            tuples.append(SemanticTuple(
                tuple_id=f"{ns}.{svc}.rate_limit.{idx}",
                function_type=FunctionType.RATE_LIMIT.value,
                predicate=_clean(match) or {},
                action={"type": "rate_limit", "rate_limit_type": model.rate_limit_type},
                scope=base_scope,
                constraint={
                    "requests_per_unit": rule.requests_per_unit,
                    "unit": rule.unit,
                },
                plane=plane_val,
            ))
        if not model.rules:
            tuples.append(SemanticTuple(
                tuple_id=f"{ns}.{svc}.rate_limit.0",
                function_type=FunctionType.RATE_LIMIT.value,
                action={"type": "rate_limit", "rate_limit_type": model.rate_limit_type},
                scope=base_scope,
                plane=plane_val,
            ))
        return tuples

    if isinstance(model, FaultInjectionFunctionModel):
        match = model.match_conditions.to_dict() if model.match_conditions else {}
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.fault_injection",
            function_type=FunctionType.FAULT_INJECTION.value,
            predicate=_clean(match) or {},
            action={"type": "fault_injection"},
            scope=base_scope,
            constraint={"delay": model.delay, "abort": model.abort},
            plane=plane_val,
        ))
        return tuples

    if isinstance(model, LoadBalancingFunctionModel):
        tuples.append(SemanticTuple(
            tuple_id=f"{ns}.{svc}.load_balancing",
            function_type=FunctionType.LOAD_BALANCING.value,
            action={"type": "load_balancing", "algorithm": model.algorithm},
            scope={**base_scope, "subsets": [s.get("name") for s in (model.subsets or []) if isinstance(s, dict)]},
            constraint={"algorithm": model.algorithm, "consistent_hash": model.consistent_hash},
            plane=plane_val,
        ))
        return tuples

    tuples.append(SemanticTuple(
        tuple_id=f"{ns}.{svc}.{ftype}",
        function_type=ftype,
        action={"type": ftype},
        scope=base_scope,
        plane=plane_val,
    ))
    return tuples


def _numeric_pairs(obj: Any, prefix: str = "") -> List[Tuple[str, float]]:
    pairs = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                pairs.append((path, float(val)))
            else:
                pairs.extend(_numeric_pairs(val, path))
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            pairs.extend(_numeric_pairs(val, f"{prefix}[{idx}]"))
    return pairs


def compare_tuples(
    control: SemanticTuple,
    data: SemanticTuple,
    tau: float = 0.1,
    timeout_abs: float = 0.0,
) -> List[Dict[str, Any]]:
    diffs: List[Dict[str, Any]] = []
    if _clean(control.predicate) != _clean(data.predicate):
        diffs.append({
            "kind": "discrete",
            "field": "predicate",
            "control": control.predicate,
            "data": data.predicate,
            "description": "匹配条件不一致",
        })
    if (control.action or {}).get("type") != (data.action or {}).get("type"):
        diffs.append({
            "kind": "discrete",
            "field": "action.type",
            "control": control.action,
            "data": data.action,
            "description": "动作类型不一致",
        })
    c_scope = {
        "service": normalize_host(control.scope.get("service")),
        "namespace": control.scope.get("namespace"),
        "subsets": sorted(control.scope.get("subsets") or []),
    }
    d_scope = {
        "service": normalize_host(data.scope.get("service")),
        "namespace": data.scope.get("namespace"),
        "subsets": sorted(data.scope.get("subsets") or []),
    }
    if c_scope != d_scope:
        diffs.append({
            "kind": "discrete",
            "field": "scope",
            "control": c_scope,
            "data": d_scope,
            "description": "作用对象不一致",
        })

    c_nums = dict(_numeric_pairs(control.constraint))
    d_nums = dict(_numeric_pairs(data.constraint))
    keys = set(c_nums) | set(d_nums)
    for key in sorted(keys):
        cv, dv = c_nums.get(key), d_nums.get(key)
        if cv is None or dv is None:
            present = cv if cv is not None else dv
            # Envoy uint32 默认无限（4294967295）不是声明意图，缺一侧时忽略
            if present is not None and _is_unlimited_threshold(present):
                continue
            # Istio 未声明 port 时 Envoy 仍会从 cluster 名填端口，不算声明不一致
            if str(key).endswith(".port"):
                continue
            diffs.append({
                "kind": "constraint",
                "field": key,
                "control": cv,
                "data": dv,
                "description": f"数值约束 {key} 缺一侧",
            })
            continue
        denom = max(abs(cv), 1.0)
        abs_delta = abs(cv - dv)
        if "timeout" in str(key).lower() and timeout_abs > 0 and abs_delta <= timeout_abs:
            continue
        # kube Service 端口 80 与容器 targetPort（9080/8080）是同一条 Istio 规则的重复投影
        if str(key).endswith(".port"):
            ports = {int(cv), int(dv)}
            if 80 in ports and ports - {80}:
                continue
        if abs_delta / denom > tau:
            diffs.append({
                "kind": "constraint",
                "field": key,
                "control": cv,
                "data": dv,
                "tau": tau,
                "description": f"数值约束 {key} 超出容差 {tau}",
            })
    return diffs
