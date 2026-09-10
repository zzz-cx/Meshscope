"""Meshscope 合成入口命名辅助（path ↔ meshscope-svc-XXXX）。"""

import re
from typing import Optional

from istio_Dynamic_Test.pkg.k8s.ingress_shard import service_index_from_path


def meshscope_svc_from_path(path: str) -> str:
    """/s3/... -> meshscope-svc-0003；无法推断则返回空字符串。"""
    idx = service_index_from_path(path)
    if idx is None:
        return ""
    return f"meshscope-svc-{idx:04d}"


def meshscope_svc_short_name(name: str) -> str:
    """从 host/FQDN 提取 meshscope-svc-XXXX 短名。"""
    n = (name or "").strip()
    if not n:
        return ""
    if ".svc.cluster.local" in n:
        n = n.split(".svc.cluster.local", 1)[0]
    if "." in n:
        n = n.split(".", 1)[0]
    m = re.match(r"^(meshscope-svc-\d{4})$", n)
    return m.group(1) if m else ""


def meshscope_svc_index_from_short(name: str) -> Optional[int]:
    short = meshscope_svc_short_name(name)
    if not short:
        return None
    m = re.match(r"^meshscope-svc-(\d{4})$", short)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def path_for_meshscope_svc(svc: str) -> str:
    """meshscope-svc-0003 -> /s3/"""
    m = re.match(r"^meshscope-svc-(\d{4})$", svc or "")
    if not m:
        return ""
    return f"/s{int(m.group(1))}/"


def resolve_meshscope_svc(path: str, host_or_svc: str) -> str:
    """优先从 path 推断，否则从 host/服务名推断。"""
    return meshscope_svc_from_path(path) or meshscope_svc_short_name(host_or_svc)
