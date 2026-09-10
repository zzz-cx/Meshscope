"""动态验证安全开关：高压、故障注入、rollout。

关闭后仍会尽量打入路由/分流/限流基线等普通探测；需要诱发异常或打满
连接池的用例会跳过，并说明为什么熔断/超时/重试/限流高压无法验证。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence

from istio_Dynamic_Test.internal.models.testcase import PolicyType, TestCase, TestType


POLICY_NEEDS_FAULT = (
    PolicyType.RETRY,
    PolicyType.TIMEOUT,
    PolicyType.FAULT_INJECTION,
    PolicyType.CONNECTION_POOL_OUTLIER,
)

RATE_LIMIT_HIGH_MODES = {"should_see_limits", "over_limit", "high_load"}


@dataclass(frozen=True)
class DynamicSafetyOptions:
    allow_load_test: bool = True
    allow_fault_injection: bool = False
    allow_rollout: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return asdict(self)


def options_from_mapping(data: Optional[Dict[str, Any]] = None, **overrides: Any) -> DynamicSafetyOptions:
    """从 config / 请求体 / CLI 合成开关。显式传入的 overrides 优先。"""
    src = dict(data or {})
    src.update({k: v for k, v in overrides.items() if v is not None})

    def _flag(key: str, default: bool) -> bool:
        if key in src and src[key] is not None:
            return _as_bool(src[key])
        alt = {
            "allow_load_test": "load_test",
            "allow_fault_injection": "fault_injection",
            "allow_rollout": "rollout",
        }.get(key)
        if alt and alt in src and src[alt] is not None:
            return _as_bool(src[alt])
        return default

    return DynamicSafetyOptions(
        allow_load_test=_flag("allow_load_test", True),
        allow_fault_injection=_flag("allow_fault_injection", False),
        allow_rollout=_flag("allow_rollout", False),
    )


def options_from_config(overrides: Optional[Dict[str, Any]] = None) -> DynamicSafetyOptions:
    values: Dict[str, Any] = {}
    try:
        from consistency_checker.config import get_config
        cfg = get_config()
        values = {
            "allow_load_test": getattr(cfg, "allow_load_test", True),
            "allow_fault_injection": getattr(cfg, "allow_fault_injection", False),
            "allow_rollout": getattr(cfg, "allow_rollout", False),
        }
    except Exception:
        pass
    return options_from_mapping(values, **(overrides or {}))


def warning_lines(options: DynamicSafetyOptions) -> List[str]:
    lines: List[str] = []
    if not options.allow_load_test:
        lines.append(
            "未开启高压测试：限流高压、连接池打满类熔断将跳过。"
            "路由、分流和限流基线仍会打入普通流量。"
        )
    if not options.allow_fault_injection:
        lines.append(
            "未开启故障注入：不会改 VirtualService 打 503/delay。"
            "熔断（outlier）、超时、重试、故障注入策略无法诱发异常，将跳过动态验证。"
        )
    if not options.allow_rollout:
        lines.append(
            "未允许 rollout：不会 patch Deployment / 重启 sidecar 来打开 Envoy access log。"
            "依赖日志标志（如熔断 UO）的判定可能不完整。"
        )
    return lines


def banner_text(options: DynamicSafetyOptions) -> str:
    bits = [
        f"高压测试={'开' if options.allow_load_test else '关'}",
        f"故障注入={'开' if options.allow_fault_injection else '关'}",
        f"允许 rollout={'开' if options.allow_rollout else '关'}",
    ]
    lines = ["  [GUARD] 动态验证开关: " + " · ".join(bits)]
    for warn in warning_lines(options):
        lines.append("  [GUARD] " + warn)
    return "\n".join(lines)


def case_block_reasons(tc: TestCase, options: DynamicSafetyOptions) -> List[str]:
    """返回该用例被安全开关拦住的原因；空列表表示可以执行。"""
    reasons: List[str] = []
    policies = set(tc.policy_types or [])
    strategies = {str(s) for s in (tc.test_strategies or [])}

    needs_fault = _needs_fault_injection(tc, policies, strategies)
    if needs_fault and not options.allow_fault_injection:
        reasons.append(
            "未开启故障注入，无法诱发 5xx/时延；熔断、超时、重试无法做动态验证"
        )

    needs_burst = _needs_load_burst(tc, policies, strategies)
    if needs_burst and not options.allow_load_test:
        reasons.append(
            "未开启高压测试，无法打满限流令牌桶或连接池；限流高压/连接池熔断无法做动态验证"
        )
    return reasons


def _needs_fault_injection(tc: TestCase, policies: set, strategies: set) -> bool:
    if tc.trigger_condition:
        return True
    fp = tc.fault_params or {}
    if fp.get("simulate_slow_response") or fp.get("fault_type") or fp.get("response_delay"):
        return True
    if policies & set(POLICY_NEEDS_FAULT):
        return True
    if strategies & {"retry", "timeout", "fault_injection", "connection_pool_outlier"}:
        return True
    if PolicyType.CIRCUIT_BREAKER in policies and tc.expected_circuit_breaker_threshold:
        return True
    if "circuit_breaker" in strategies and tc.expected_circuit_breaker_threshold:
        return True
    return False


def _needs_load_burst(tc: TestCase, policies: set, strategies: set) -> bool:
    expect = (tc.rate_limit_expect or {})
    if str(expect.get("mode") or "") in RATE_LIMIT_HIGH_MODES:
        return True
    if PolicyType.RATE_LIMIT in policies and tc.test_type == TestType.LOAD_TEST:
        if (tc.request_count or 0) >= 16 or (tc.concurrency or 1) > 1:
            if expect.get("mode") != "should_pass_all":
                return True
    if PolicyType.CIRCUIT_BREAKER in policies or PolicyType.CONNECTION_POOL in policies:
        if tc.test_type == TestType.LOAD_TEST and (tc.concurrency or 1) >= 4:
            return True
    if strategies & {"circuit_breaker", "connection_pool"} and tc.test_type == TestType.LOAD_TEST:
        if (tc.concurrency or 1) >= 4:
            return True
    return False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def summarize_skip_counts(cases: Sequence[TestCase], options: DynamicSafetyOptions) -> Dict[str, int]:
    blocked = [tc for tc in cases if case_block_reasons(tc, options)]
    return {"total": len(cases), "blocked": len(blocked), "runnable": len(cases) - len(blocked)}
