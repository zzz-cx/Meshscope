#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成入口 VirtualService 分片（与 generate_scale_stack / FaultInjector 对齐）。"""

import os
import re
from typing import Optional

_INGRESS_SHARD_FALLBACK = "meshscope-synth-shard-fallback"


def ingress_shard_count() -> int:
    try:
        n = int((os.getenv("MESHSCOPE_INGRESS_SHARDS") or "1").strip() or "1")
    except ValueError:
        n = 1
    return max(1, min(n, 99))


def service_index_from_path(path: str) -> Optional[int]:
    p = (path or "").strip()
    m = re.match(r"^/s(\d+)(/|$)", p)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def meshscope_svc_index_from_name(name: str) -> Optional[int]:
    """meshscope-svc-0003[.ns...] -> 3；无法解析则 None。"""
    h = (name or "").strip().split(".svc.cluster.local", 1)[0].split(".", 1)[0]
    m = re.match(r"^meshscope-svc-(\d{4})$", h)
    if not m:
        m = re.match(r"^meshscope-svc-(\d+)$", h)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def synth_ingress_vs_name_for_case(path: str, route_host_or_svc: str) -> str:
    """结合 path 与目标服务名解析应 patch 的分片入口 VS（单分片时为 meshscope-synth-ingress）。"""
    if ingress_shard_count() <= 1:
        return "meshscope-synth-ingress"
    idx = service_index_from_path(path)
    if idx is None:
        idx = meshscope_svc_index_from_name(route_host_or_svc)
    return synth_shard_vs_name(idx)


def synth_shard_vs_name(service_index: Optional[int]) -> str:
    """
    分片入口 VS 资源名。
    - shards==1: 沿用历史名 meshscope-synth-ingress
    - shards>1:  meshscope-synth-shard-{idx:02d}；无法从 path 推断时写 shard-00；
                 全局兜底路由在集群里由 meshscope-synth-shard-fallback 承载（字典序最后）。
    """
    shards = ingress_shard_count()
    if shards <= 1:
        return "meshscope-synth-ingress"
    if service_index is None:
        return "meshscope-synth-shard-00"
    return f"meshscope-synth-shard-{service_index % shards:02d}"


def synth_fallback_vs_name() -> str:
    """仅含兜底路由的 VS（多分片模式下必须字典序晚于各分片 VS）。"""
    return _INGRESS_SHARD_FALLBACK


def synth_ingress_vs_name_for_path(path: str) -> str:
    return synth_ingress_vs_name_for_case(path, "")


def synth_ingress_lock_key_for_path_and_host(path: str, route_host_or_svc: str) -> str:
    return f"vs:{synth_ingress_vs_name_for_case(path, route_host_or_svc)}"


def synth_ingress_lock_key_for_path(path: str) -> str:
    return synth_ingress_lock_key_for_path_and_host(path, "")


def is_synth_ingress_vs_resource_name(name: str) -> bool:
    n = (name or "").strip()
    if n == "meshscope-synth-ingress":
        return True
    if n == _INGRESS_SHARD_FALLBACK:
        return True
    return n.startswith("meshscope-synth-shard-") and len(n) > len("meshscope-synth-shard-")
