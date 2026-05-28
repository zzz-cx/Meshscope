#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全并行调度（最小可用版）

目标：
- 对 TestCase 打标签（locks），描述其执行期间需要独占写的共享资源
- 通过 LockManager 确保锁集合有交集的用例不会并发执行

说明：
- “正交用例生成”不等于“执行时互不干扰”。本调度器的并行性以资源互斥为准。
- 入口 VS 写锁：单资源 `meshscope-synth-ingress` 或按 `MESHSCOPE_INGRESS_SHARDS` 分片为
  `meshscope-synth-shard-XX`（与 generate_scale_stack / FaultInjector 一致）。
"""

import re
import threading
from contextlib import contextmanager
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, TypeVar

from istio_Dynamic_Test.internal.models.testcase import PolicyType, TestCase
from istio_Dynamic_Test.pkg.k8s.ingress_shard import synth_ingress_lock_key_for_path_and_host
from istio_Dynamic_Test.pkg.k8s.meshscope_naming import meshscope_svc_short_name

T = TypeVar("T")


def _ingress_vs_lock_key(tc: TestCase) -> str:
    path = getattr(tc, "path", None) or ""
    host = (getattr(tc, "host", None) or "").strip()
    src = (getattr(tc, "source_service", None) or "").strip()
    route_hint = host if host and host != "*" else src
    return synth_ingress_lock_key_for_path_and_host(path, route_hint)


class LockManager:
    """基于字符串 key 的多锁管理器（固定顺序获取，避免死锁）。"""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._locks = {}  # type: Dict[str, threading.Lock]

    def _get_lock(self, key: str) -> threading.Lock:
        with self._mu:
            lk = self._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._locks[key] = lk
            return lk

    @contextmanager
    def acquire_all(self, keys: Sequence[str]) -> Iterable[None]:
        ordered = sorted({k for k in keys if k})
        acquired = []  # type: List[threading.Lock]
        try:
            for k in ordered:
                lk = self._get_lock(k)
                lk.acquire()
                acquired.append(lk)
            yield
        finally:
            for lk in reversed(acquired):
                try:
                    lk.release()
                except Exception:
                    pass


def tag_case_locks(tc: TestCase) -> List[str]:
    """
    给用例打“资源锁标签”。

    设计原则（保守优先）：
    - 只要可能写入口 VS，就锁对应分片（或单入口时的 meshscope-synth-ingress）
    - connection_pool_outlier_validation 会写入口 VS（注入/恢复），phase1/phase2 都需串行化入口写
      （我们已在 FaultInjector 内部做了入口写锁，但这里仍做调度级锁，避免其它写操作穿插造成混乱）
    """
    if tc.metadata.get("is_orthogonal_fault_bundle"):
        subs = tc.metadata.get("bundle_subcases") or []
        acc: List[str] = []
        for s in subs:
            acc.extend(tag_case_locks(s))
        return sorted(set(acc))

    locks = []  # type: List[str]

    trigger = (tc.trigger_condition or "").strip()
    strategies = set(tc.test_strategies or [])
    policies = set(tc.policy_types or [])

    # 1) 强制入口 VS 写锁：任何明确的故障/注入/熔断/连接池/超时触发都可能写入口 VS
    if trigger in (
        "simulate_503_error",
        "simulate_config_fault",
        "simulate_config_fault_with_timeout",
        "__meshscope_delay_for_timeout__",
        "connection_pool_outlier_validation",
    ):
        locks.append(_ingress_vs_lock_key(tc))

    if (
        PolicyType.FAULT_INJECTION in policies
        or PolicyType.CIRCUIT_BREAKER in policies
        or PolicyType.CONNECTION_POOL in policies
        or PolicyType.CONNECTION_POOL_OUTLIER in policies
        or PolicyType.TIMEOUT in policies
        or PolicyType.RETRY in policies
    ):
        # 这类验证常通过 FaultInjector 落到入口 VS（单入口模型）
        locks.append(_ingress_vs_lock_key(tc))

    if any(s in strategies for s in ("fault_injection", "circuit_breaker", "connection_pool", "connection_pool_outlier", "timeout", "retry")):
        locks.append(_ingress_vs_lock_key(tc))

    # 2) 可选：deployment 写锁（目前 warmup 在 suite 开始时统一做，这里先不强制）
    # 若未来把 accesslog patch/rollout 也并行化，可在此添加：
    #   locks.append(f"deploy:{svc}-v1")
    svc = meshscope_svc_short_name(tc.host or tc.source_service)
    if svc:
        locks.append("svc:" + svc)

    # 去重
    return sorted(set(locks))


def run_safely_in_parallel(
    *,
    cases: Sequence[TestCase],
    run_case: Callable[[TestCase], T],
    max_workers: int,
    lock_manager: LockManager,
    tagger: Callable[[TestCase], List[str]] = tag_case_locks,
) -> List[T]:
    """
    以线程池并行执行用例，但对每个用例按 locks 做互斥保护。
    返回结果顺序按完成顺序（非输入顺序）。
    """
    if max_workers <= 1:
        return [run_case(tc) for tc in cases]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _wrapped(tc: TestCase) -> T:
        locks = tagger(tc)
        with lock_manager.acquire_all(locks):
            return run_case(tc)

    out = []  # type: List[T]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_wrapped, tc) for tc in cases]
        for fut in as_completed(futs):
            out.append(fut.result())
    return out

