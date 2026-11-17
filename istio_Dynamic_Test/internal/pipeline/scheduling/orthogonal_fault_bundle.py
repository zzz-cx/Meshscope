# -*- coding: utf-8 -*-
"""
同一合成入口 VS（锁/分片）下，将连续的「path × 故障类」正交行打成 bundle：
一次 patch 多条 http match，再对子用例分别请求与断言。

说明：
- 仅减少 apply/clear 次数；不替代生成器的 _orthogonal_minimize，每条原始用例仍会产出独立 PipelineResult。
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from istio_Dynamic_Test.internal.models.testcase import PolicyType, TestCase, TestSuite, TestType, requires_controlled_stimulus
from istio_Dynamic_Test.pkg.k8s.ingress_shard import synth_ingress_vs_name_for_case
from istio_Dynamic_Test.pkg.k8s.meshscope_naming import resolve_meshscope_svc


def flatten_cases_for_warmup(cases: List[TestCase]) -> List[TestCase]:
    """Collector 预热需要覆盖 bundle 内所有子用例的 host/path。"""
    out: List[TestCase] = []
    for tc in cases:
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            subs = tc.metadata.get("bundle_subcases") or []
            out.extend(subs)
        else:
            out.append(tc)
    return out


def orthogonal_fault_bundle_enabled() -> bool:
    v = (os.getenv("DYNAMIC_TEST_ORTHOGONAL_FAULT_BUNDLE") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _max_bundle_size() -> int:
    try:
        n = int((os.getenv("DYNAMIC_TEST_FAULT_BUNDLE_MAX") or "8").strip() or "8")
    except ValueError:
        n = 8
    return max(2, min(n, 32))


def _resolve_meshscope_ingress(
    tc: TestCase,
    ssh,
    namespace: str,
    vs_ok_cache: Optional[Dict[str, bool]] = None,
) -> Tuple[bool, str, str, str]:
    svc = tc.host or tc.source_service
    path_prefix = (tc.path or "").strip()
    inferred = resolve_meshscope_svc(path_prefix, svc or "")
    ingress_vs = synth_ingress_vs_name_for_case(path_prefix, inferred or (svc or ""))
    if vs_ok_cache is not None and ingress_vs in vs_ok_cache:
        use_ingress_vs = vs_ok_cache[ingress_vs]
    else:
        use_ingress_vs = False
        try:
            out, err = ssh.run_command(
                "kubectl get virtualservice {0} -n {1} 2>&1".format(ingress_vs, namespace)
            )
            combined = (out or "") + (err or "")
            if "NotFound" not in combined and "Error" not in combined:
                use_ingress_vs = True
        except Exception:
            pass
        if vs_ok_cache is not None:
            vs_ok_cache[ingress_vs] = use_ingress_vs
    return use_ingress_vs, ingress_vs, inferred or "", path_prefix


def _bundle_group_key(
    tc: TestCase,
    ssh,
    namespace: str,
    vs_ok_cache: Optional[Dict[str, bool]] = None,
) -> Optional[Tuple[str, str]]:
    """可打包行返回 (vs_name, kind)，否则 None。kind: cfg_abort | cfg_delay | cfg_fto。"""
    if tc.metadata.get("is_orthogonal_fault_bundle"):
        return None
    if requires_controlled_stimulus(tc):
        return None
    if tc.test_type != TestType.SINGLE_REQUEST:
        return None
    policies = tc.policy_types or []
    for p in (
        PolicyType.TRAFFIC_SPLIT,
        PolicyType.RATE_LIMIT,
        PolicyType.CONNECTION_POOL_OUTLIER,
    ):
        if p in policies:
            return None
    if tc.trigger_condition == "connection_pool_outlier_validation":
        return None

    params = tc.fault_params or {}
    if params.get("match_headers"):
        return None

    use_ing, vs_name, inferred, path_prefix = _resolve_meshscope_ingress(
        tc, ssh, namespace, vs_ok_cache
    )
    if not (use_ing and inferred):
        return None
    if not path_prefix.startswith("/s"):
        return None

    trigger = tc.trigger_condition
    if not trigger:
        if params.get("simulate_slow_response") and (
            params.get("response_delay") or params.get("fault_delay")
        ):
            trigger = "__meshscope_delay_for_timeout__"
        else:
            return None

    if trigger == "simulate_config_fault":
        ft = params.get("fault_type", "abort")
        if ft == "abort":
            return (vs_name, "cfg_abort")
        if ft == "delay":
            return (vs_name, "cfg_delay")
        return None
    if trigger == "__meshscope_delay_for_timeout__":
        return (vs_name, "cfg_delay")
    if trigger == "simulate_config_fault_with_timeout":
        return (vs_name, "cfg_fto")
    return None


def _make_bundle_test_case(subcases: List[TestCase]) -> TestCase:
    first = subcases[0]
    ids = ",".join(s.case_id for s in subcases)
    case_id = "orthogonal_bundle[{0}]".format(ids)
    meta: Dict[str, Any] = dict(first.metadata or {})
    meta["is_orthogonal_fault_bundle"] = True
    meta["bundle_subcases"] = subcases
    desc_bits = "; ".join(s.case_id for s in subcases[:3])
    if len(subcases) > 3:
        desc_bits += "..."
    return TestCase(
        case_id=case_id,
        name=case_id,
        description="orthogonal fault bundle: " + desc_bits,
        test_type=TestType.SINGLE_REQUEST,
        policy_types=list(first.policy_types or []),
        target_url=first.target_url,
        host=first.host,
        path=first.path,
        headers=dict(first.headers or {}),
        request_count=first.request_count,
        concurrency=first.concurrency,
        trigger_condition=None,
        fault_params={},
        expected_destination=first.expected_destination,
        expected_distribution=first.expected_distribution,
        expected_success_rate=first.expected_success_rate,
        expected_fault_rate=first.expected_fault_rate,
        expected_fault_code=first.expected_fault_code,
        expected_retry_attempts=first.expected_retry_attempts,
        expected_circuit_breaker_threshold=first.expected_circuit_breaker_threshold,
        margin_of_error=first.margin_of_error,
        test_strategies=list(first.test_strategies or []),
        source_service=first.source_service,
        metadata=meta,
        rate_limit_expect=first.rate_limit_expect,
    )


def apply_orthogonal_fault_bundling(suite: TestSuite, ssh, namespace: str) -> TestSuite:
    """将 suite.cases 中连续、同 VS 同故障族、且 path 前缀互不相同的行合并为 bundle 占位用例。"""
    if not orthogonal_fault_bundle_enabled():
        return suite
    cases = suite.cases
    if len(cases) < 2:
        return suite

    max_b = _max_bundle_size()
    new_cases: List[TestCase] = []
    i = 0
    n = len(cases)
    vs_ok_cache: Dict[str, bool] = {}

    while i < n:
        tc = cases[i]
        sig = _bundle_group_key(tc, ssh, namespace, vs_ok_cache)
        if sig is None:
            new_cases.append(tc)
            i += 1
            continue

        group = [tc]
        paths_seen = {(tc.path or "").strip()}
        j = i + 1
        while j < n and len(group) < max_b:
            t2 = cases[j]
            s2 = _bundle_group_key(t2, ssh, namespace, vs_ok_cache)
            if s2 != sig:
                break
            p2 = (t2.path or "").strip()
            if p2 in paths_seen:
                break
            paths_seen.add(p2)
            group.append(t2)
            j += 1

        if len(group) >= 2:
            new_cases.append(_make_bundle_test_case(group))
            i = j
        else:
            new_cases.append(tc)
            i += 1

    return TestSuite(cases=new_cases, global_settings=dict(suite.global_settings))


def subcase_to_inject_item(tc: TestCase) -> Optional[Dict[str, Any]]:
    """与 DynamicTester._inject_fault 的合成入口分支对齐，生成一条 multi-match 规则。"""
    trigger = tc.trigger_condition
    params = tc.fault_params or {}
    if not trigger:
        if params.get("simulate_slow_response") and (
            params.get("response_delay") or params.get("fault_delay")
        ):
            trigger = "__meshscope_delay_for_timeout__"
        else:
            return None

    path_prefix = (tc.path or "").strip()
    svc = tc.host or tc.source_service
    inferred = resolve_meshscope_svc(path_prefix, svc or "")
    route_host = inferred or ""
    match_path = path_prefix or ""

    if trigger == "simulate_config_fault":
        ft = params.get("fault_type", "abort")
        if ft == "abort":
            return {
                "mode": "abort",
                "route_host": route_host,
                "match_path": match_path,
                "status_code": int(params.get("fault_status", 503)),
                "percentage": int(params.get("fault_percentage", 100)),
            }
        if ft == "delay":
            return {
                "mode": "delay",
                "route_host": route_host,
                "match_path": match_path,
                "delay": str(params.get("fault_delay", "1s")),
                "percentage": int(params.get("fault_percentage", 100)),
            }
        return None
    if trigger == "__meshscope_delay_for_timeout__":
        return {
            "mode": "delay",
            "route_host": route_host,
            "match_path": match_path,
            "delay": str(
                params.get("response_delay", params.get("fault_delay", "3s"))
            ),
            "percentage": 100,
        }
    if trigger == "simulate_config_fault_with_timeout":
        return {
            "mode": "fault_timeout",
            "route_host": route_host,
            "match_path": match_path,
            "status_code": int(params.get("fault_status", 503)),
            "percentage": int(params.get("fault_percentage", 100)),
            "timeout": str(params.get("timeout_limit", "2s")),
        }
    return None
