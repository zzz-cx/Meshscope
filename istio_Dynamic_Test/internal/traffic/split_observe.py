"""从真实 HTTP 响应观察分流结果。

部分 demo 服务（http-echo）响应体带 ``reviews-v1``，可以直接统计。
多数真实服务没有这个信号，``version_signal_usable`` 为 False 时必须
改用 Prometheus / Envoy / Jaeger。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

_VERSION_RE = re.compile(r"(?:^|[-_./])(v\d+)\b", re.IGNORECASE)
_SERVICE_RE = re.compile(r"^([a-z0-9][a-z0-9-]*)-v\d+\b", re.IGNORECASE)
_WORKLOAD_VER = re.compile(r"-v(\d+)$", re.IGNORECASE)

_VERSION_HEADER_KEYS = (
    "x-app-version",
    "x-version",
    "x-service-version",
    "x-subset",
    "x-istio-version",
    "x-canary",
)


def normalize_percent_weights(raw: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """把 70/30 或 0.7/0.3 都归一成 0–100 的百分比。"""
    if not raw:
        return {}
    vals: Dict[str, float] = {}
    for key, val in raw.items():
        try:
            vals[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    total = sum(vals.values())
    if total <= 0:
        return {}
    if total <= 1.5:
        return {k: v / total * 100.0 for k, v in vals.items()}
    return {k: v / total * 100.0 for k, v in vals.items()}


def infer_subset(body: str, expected: Optional[Iterable[str]] = None) -> str:
    text = (body or "").strip()
    if not text:
        return "unknown"
    wanted = [str(v) for v in (expected or []) if v]
    wanted = sorted(wanted, key=len, reverse=True)
    lower = text.lower()
    for ver in wanted:
        token = str(ver).lower()
        if re.search(rf"(?:^|[-_./]){re.escape(token)}(?:$|[^a-z0-9])", lower):
            return str(ver)
    match = _VERSION_RE.search(text)
    return match.group(1).lower() if match else "unknown"


def infer_service(body: str) -> Optional[str]:
    match = _SERVICE_RE.match((body or "").strip())
    return match.group(1) if match else None


def counts_to_percent(counts: Dict[str, int], expected_keys: Optional[Iterable[str]] = None) -> Tuple[Dict[str, float], int]:
    keys = [str(k) for k in (expected_keys or counts.keys())]
    usable = {k: int(counts.get(k, 0) or 0) for k in keys}
    # 未声明的版本也计入分母，避免把未知流量藏掉
    extra = {k: int(v) for k, v in counts.items() if k not in usable and k != "unknown"}
    usable.update(extra)
    total = sum(usable.values())
    if total <= 0:
        return {k: 0.0 for k in keys}, 0
    return {k: usable.get(k, 0) / total * 100.0 for k in usable}, total


def infer_subset_from_headers(headers: Optional[Mapping], expected: Optional[Iterable[str]] = None) -> str:
    if not headers:
        return "unknown"
    getter = getattr(headers, "get", None)
    for key in _VERSION_HEADER_KEYS:
        val = ""
        if getter:
            val = getter(key) or getter(key.title()) or getter(key.lower()) or ""
        if val:
            found = infer_subset(str(val), expected)
            if found != "unknown":
                return found
    items = []
    try:
        items = list(headers.items())
    except Exception:
        items = []
    for _, val in items:
        found = infer_subset(str(val or ""), expected)
        if found != "unknown":
            return found
    return "unknown"


def infer_subset_from_response(
    body: str,
    headers: Optional[Mapping] = None,
    expected: Optional[Iterable[str]] = None,
) -> str:
    from_body = infer_subset(body, expected)
    if from_body != "unknown":
        return from_body
    return infer_subset_from_headers(headers, expected)


def version_from_workload(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "unknown"
    match = _WORKLOAD_VER.search(text)
    if match:
        return "v" + match.group(1)
    return infer_subset(text)


def version_signal_usable(
    counts: Optional[Dict[str, Any]],
    expected: Optional[Iterable[str]] = None,
    min_ratio: float = 0.5,
) -> bool:
    """响应体/指标里能否认出期望 subset。unknown 占多数则不可用。"""
    data = {str(k): int(v or 0) for k, v in (counts or {}).items()}
    wanted = [str(k) for k in (expected or []) if k]
    if not wanted:
        wanted = [k for k in data if k != "unknown"]
    hit = sum(data.get(k, 0) for k in wanted)
    if hit <= 0:
        return False
    total = sum(max(0, n) for n in data.values())
    if total <= 0:
        return False
    return (hit / total) >= min_ratio


def short_service_name(*candidates: Optional[str]) -> str:
    for raw in candidates:
        text = (raw or "").strip()
        if not text or text == "*":
            continue
        return text.split(".")[0]
    return ""
