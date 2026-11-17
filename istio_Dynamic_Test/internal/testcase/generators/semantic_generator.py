"""从对齐后的语义模型生成动态测试用例。

期望行为只来自 aligned_semantic.json 中 matched / partial_matched 的元组。
没有该产物时直接报错，不回退到 YAML / istio_config.json。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.internal.models.testcase import TestCase, PolicyType
from .base import BaseGenerator

try:
    from istio_config_parser.main_parser import (
        AlignedModelMissingError,
        load_aligned_semantic,
    )
except ImportError:  # pragma: no cover
    AlignedModelMissingError = FileNotFoundError  # type: ignore

    def load_aligned_semantic(path=None):
        raise AlignedModelMissingError("istio_config_parser 不可用，无法加载对齐模型")


_FUNCTION_TO_POLICY = {
    "routing": PolicyType.ROUTING,
    "traffic_shifting": PolicyType.TRAFFIC_SPLIT,
    "traffic_split": PolicyType.TRAFFIC_SPLIT,
    "retry": PolicyType.RETRY,
    "timeout": PolicyType.TIMEOUT,
    "circuit_breaker": PolicyType.CIRCUIT_BREAKER,
    "rate_limit": PolicyType.RATE_LIMIT,
    "fault_injection": PolicyType.FAULT_INJECTION,
}


def _flatten_headers(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for name, spec in raw.items():
        if isinstance(spec, dict):
            val = spec.get("exact") or spec.get("prefix") or spec.get("regex")
            if val is not None:
                out[str(name)] = str(val)
        elif spec is not None:
            out[str(name)] = str(spec)
    return out


def _path_from_predicate(predicate: Dict[str, Any]) -> str:
    if not isinstance(predicate, dict):
        return "/"
    uri = predicate.get("uri") or predicate.get("path") or {}
    if isinstance(uri, dict):
        return uri.get("prefix") or uri.get("exact") or uri.get("regex") or "/"
    if isinstance(uri, str) and uri:
        return uri
    prefix = predicate.get("prefix")
    if prefix:
        return str(prefix)
    return "/"


def _host_from_tuple(tup: Dict[str, Any]) -> str:
    scope = tup.get("scope") or {}
    hosts = scope.get("hosts") or []
    if hosts:
        host = hosts[0]
        if host and host != "*":
            return str(host).split(".")[0]
    return str(scope.get("service") or tup.get("service_name") or "")


def _destination_label(constraint: Dict[str, Any]) -> Optional[str]:
    dests = constraint.get("destinations") or []
    if dests and isinstance(dests[0], dict):
        return dests[0].get("subset") or (dests[0].get("host") or "").split(".")[0]
    weights = constraint.get("weights") or {}
    if len(weights) == 1:
        return next(iter(weights))
    return None


class SemanticGenerator(BaseGenerator):
    """对齐模型 → 测试用例。"""

    def __init__(
        self,
        aligned_path: Optional[str] = None,
        ingress_url: str = "",
        namespace: str = "default",
        artifact: Optional[Dict[str, Any]] = None,
    ):
        self._aligned_path = aligned_path
        self._ingress_url = ingress_url
        self._namespace = namespace
        self._artifact = artifact

    def generate_matrix_dicts(self) -> List[Dict[str, Any]]:
        artifact = self._artifact or load_aligned_semantic(self._aligned_path)
        tuples = artifact.get("expected_tuples") or []
        if self._namespace:
            tuples = [
                t for t in tuples
                if (t.get("namespace") or "default") == self._namespace
            ]
        if not tuples:
            raise AlignedModelMissingError(
                "对齐模型中没有 matched/partial_matched 元组，无法生成动态期望。"
                "请先执行静态分析并确认两侧已对齐。"
            )
        cases: List[Dict[str, Any]] = []
        counter = 1
        for tup in tuples:
            ftype = tup.get("function_type") or (tup.get("action") or {}).get("type") or ""
            policy = _FUNCTION_TO_POLICY.get(ftype)
            if policy is None:
                continue
            built = self._tuple_to_cases(tup, policy, counter)
            svc = str(tup.get("service_name") or (tup.get("scope") or {}).get("service") or "")
            for case in built:
                case.setdefault("target_service", svc)
                case.setdefault("source_service", svc)
            cases.extend(built)
            counter += len(built)
        if not cases:
            raise AlignedModelMissingError(
                "对齐模型未能映射出可执行的动态用例（无 routing/split/retry 等可探测元组）。"
            )
        for idx, case in enumerate(cases, 1):
            case.setdefault("case_id", f"case_{idx:03d}")
        return cases

    def generate(self) -> List[TestCase]:
        return [
            TestCase.from_matrix_dict(raw, self._ingress_url)
            for raw in self.generate_matrix_dicts()
        ]

    def generate_matrix(self) -> Dict[str, Any]:
        test_cases = self.generate_matrix_dicts()
        return {
            "global_settings": {"ingress_url": self._ingress_url},
            "test_cases": test_cases,
            "source": "aligned_semantic",
        }

    def generate_obligation_plan(self, *, reuse: bool = True, profiles=None, resource_ids=None) -> Dict[str, Any]:
        """Opt-in relation-aware planning; does not alter the legacy matrix."""
        from istio_Dynamic_Test.internal.planning.relational import plan_obligations
        artifact = self._artifact or load_aligned_semantic(self._aligned_path)
        model = artifact.get("relational_model")
        if not model:
            raise AlignedModelMissingError("关系模型缺失，请重新运行静态解析；不回退为按策略标签约简。")
        return plan_obligations(model, reuse=reuse, namespace=artifact.get("namespace"), profiles=profiles, resource_ids=resource_ids)

    def _tuple_to_cases(
        self,
        tup: Dict[str, Any],
        policy: PolicyType,
        start_id: int,
    ) -> List[Dict[str, Any]]:
        predicate = tup.get("predicate") or {}
        constraint = tup.get("constraint") or {}
        scope = tup.get("scope") or {}
        host = _host_from_tuple(tup)
        path = _path_from_predicate(predicate)
        if path in ("", "/") and tup.get("namespace") == "meshscope-demo":
            svc = str(tup.get("service_name") or scope.get("service") or host or "").strip()
            if svc and svc not in ("*", "demo-ingress"):
                path = f"/demo/{svc.split('.')[0]}"
        headers = _flatten_headers(predicate.get("headers") if isinstance(predicate, dict) else None)
        source = tup.get("service_name") or scope.get("service") or host
        params: Dict[str, Any] = {"host": host or "*", "path": path or "/"}
        if headers:
            params["headers"] = headers

        cases: List[Dict[str, Any]] = []
        cid = lambda n: f"case_{n:03d}"

        if policy in (PolicyType.ROUTING, PolicyType.TRAFFIC_SPLIT):
            weights = constraint.get("weights") or {}
            numeric_weights = {
                str(k): float(v) for k, v in weights.items() if isinstance(v, (int, float))
            }
            if len(numeric_weights) > 1:
                cases.append({
                    "case_id": cid(start_id),
                    "description": f"流量分配 {source}",
                    "type": "load_test",
                    "request_params": params,
                    "load_params": {"num_requests": 100, "concurrency": 10},
                    "expected_outcome": {
                        "distribution": numeric_weights,
                        "margin_of_error": 0.1,
                    },
                    "source_service": source,
                    "test_strategies": ["traffic_split"],
                })
            else:
                dest = _destination_label(constraint)
                cases.append({
                    "case_id": cid(start_id),
                    "description": f"正向路由 {source}" + (f" -> {dest}" if dest else ""),
                    "type": "single_request",
                    "request_params": params,
                    "expected_outcome": {"destination": dest} if dest else {},
                    "source_service": source,
                    "test_strategies": ["routing"],
                })
            return cases

        if policy == PolicyType.RETRY:
            attempts = constraint.get("attempts")
            params = dict(params)
            params["trigger_condition"] = "controlled_backend_retry"
            cases.append({
                "case_id": cid(start_id),
                "description": f"重试 {source} attempts={attempts}",
                "type": "single_request",
                "request_params": params,
                "expected_outcome": {"retry_attempts": attempts},
                "source_service": source,
                "test_strategies": ["retry"],
                "retry_policy": dict(constraint),
            })
            return cases

        if policy == PolicyType.TIMEOUT:
            params = dict(params)
            params["simulate_slow_response"] = True
            params["timeout_limit"] = constraint.get("timeout_s")
            cases.append({
                "case_id": cid(start_id),
                "description": f"超时 {source} timeout_s={constraint.get('timeout_s')}",
                "type": "single_request",
                "request_params": params,
                "expected_outcome": {"timeout_s": constraint.get("timeout_s")},
                "source_service": source,
                "test_strategies": ["timeout"],
            })
            return cases

        if policy == PolicyType.CIRCUIT_BREAKER:
            pool = constraint.get("connection_pool") or {}
            outlier = constraint.get("outlier_detection") or {}
            if not pool and not outlier:
                return []
            threshold = outlier.get("consecutive_5xx") or outlier.get("consecutive5xxErrors") or outlier.get("consecutive_5xx_errors")
            params = dict(params)
            if outlier:
                params["trigger_condition"] = "simulate_config_fault"
                params["fault_type"] = "abort"
                params["fault_status"] = 503
                params["fault_percentage"] = 100
            cases.append({
                "case_id": cid(start_id),
                "description": f"熔断 {source}",
                "type": "load_test",
                "request_params": params,
                "load_params": {"num_requests": 50, "concurrency": 10},
                "expected_outcome": {"circuit_breaker_threshold": threshold,
                    "connection_pool": constraint.get("connection_pool"),
                    "outlier_detection": outlier},
                "source_service": source,
                "test_strategies": ["circuit_breaker"],
            })
            return cases

        if policy == PolicyType.RATE_LIMIT:
            unit_n = constraint.get("requests_per_unit") or 10
            cases.append({
                "case_id": cid(start_id),
                "description": f"限流基线 {source}",
                "type": "load_test",
                "request_params": params,
                "load_params": {"num_requests": max(5, int(unit_n) // 2 or 5), "concurrency": 1},
                "expected_outcome": {"rate_limit": {"mode": "should_pass_all", "max_429": 1}},
                "source_service": source,
                "test_strategies": ["rate_limit"],
            })
            cases.append({
                "case_id": cid(start_id + 1),
                "description": f"限流高压 {source}",
                "type": "load_test",
                "request_params": params,
                "load_params": {"num_requests": max(24, int(unit_n) * 4), "concurrency": 8},
                "expected_outcome": {"rate_limit": {"mode": "should_see_limits", "min_429": 1}},
                "source_service": source,
                "test_strategies": ["rate_limit"],
            })
            return cases

        if policy == PolicyType.FAULT_INJECTION:
            abort = constraint.get("abort") or {}
            delay = constraint.get("delay") or {}
            params = dict(params)
            if abort:
                params["trigger_condition"] = "simulate_config_fault"
                params["fault_type"] = "abort"
                params["fault_status"] = abort.get("httpStatus") or abort.get("http_status")
                params["fault_percentage"] = (abort.get("percentage") or {}).get("value") if isinstance(abort.get("percentage"), dict) else abort.get("percentage")
                cases.append({
                    "case_id": cid(start_id),
                    "description": f"故障注入 abort {source}",
                    "type": "single_request",
                    "request_params": params,
                    "expected_outcome": {"fault_code": params.get("fault_status")},
                    "source_service": source,
                    "test_strategies": ["fault_injection"],
                })
            if delay:
                delay_params = dict(params)
                delay_params["trigger_condition"] = "simulate_config_fault"
                delay_params["fault_type"] = "delay"
                delay_params["fault_delay"] = delay.get("fixedDelay") or delay.get("fixed_delay")
                cases.append({
                    "case_id": cid(start_id + (1 if abort else 0)),
                    "description": f"故障注入 delay {source}",
                    "type": "single_request",
                    "request_params": delay_params,
                    "expected_outcome": {},
                    "source_service": source,
                    "test_strategies": ["fault_injection"],
                })
            if not cases:
                cases.append({
                    "case_id": cid(start_id),
                    "description": f"故障注入 {source}",
                    "type": "single_request",
                    "request_params": params,
                    "expected_outcome": {},
                    "source_service": source,
                    "test_strategies": ["fault_injection"],
                })
            return cases

        return cases
