"""
链路追踪数据获取模块

通过 Jaeger 或 Zipkin HTTP API 获取 trace 数据，用于 Istio 动态行为验证与配置一致性检查。
使用 get_observability_config 获取 tracing URL 和 backend 类型，自动选择正确的 API。

Jaeger API:  GET /api/traces?service=xxx&limit=20
Zipkin API:  GET /api/v2/traces?serviceName=xxx&limit=10
"""
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from .observability_config import get_observability_config

logger = logging.getLogger(__name__)


def fetch_traces(
    service: Optional[str] = None,
    limit: int = 20,
    start: Optional[int] = None,
    end: Optional[int] = None,
    min_duration: Optional[str] = None,
    namespace: str = "istio-system",
    tracing_url: Optional[str] = None,
    tracing_backend: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    从 Jaeger 或 Zipkin 获取 trace 数据。

    Args:
        service: 服务名，如 productpage、reviews
        limit: 返回 trace 数量上限
        start: 开始时间戳（微秒）
        end: 结束时间戳（微秒）
        min_duration: 最小耗时，如 "1ms"、"100ms"
        namespace: K8s 命名空间
        tracing_url: 覆盖 URL，不指定则从 get_observability_config 获取
        tracing_backend: 覆盖 backend，不指定则自动推断

    Returns:
        统一格式的 trace 列表，每个 trace 含 trace_id, spans, service_chain 等
    """
    cfg = get_observability_config(namespace=namespace)
    url = tracing_url or cfg.get("tracing_url") or cfg.get("zipkin_url")
    backend = tracing_backend or cfg.get("tracing_backend") or "jaeger"

    if not url:
        logger.warning("未找到 tracing 服务，请设置 JAEGER_URL 或 ZIPKIN_URL 环境变量")
        return []

    url = url.rstrip("/")

    if backend == "jaeger":
        return _fetch_jaeger_traces(url, service, limit, start, end, min_duration)
    return _fetch_zipkin_traces(url, service, limit, start, end, min_duration)


def _fetch_jaeger_traces(
    base_url: str,
    service: Optional[str],
    limit: int,
    start: Optional[int],
    end: Optional[int],
    min_duration: Optional[str],
) -> List[Dict[str, Any]]:
    """Jaeger API: GET /api/traces"""
    params = {"limit": limit}
    if service:
        params["service"] = service
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if min_duration:
        params["minDuration"] = min_duration

    api_url = f"{base_url}/api/traces"
    try:
        r = requests.get(api_url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        raw_traces = data.get("data", [])
        return [_jaeger_trace_to_unified(t) for t in raw_traces]
    except Exception as e:
        logger.error(f"Jaeger API 请求失败: {e}")
        return []


def _fetch_zipkin_traces(
    base_url: str,
    service: Optional[str],
    limit: int,
    start: Optional[int],
    end: Optional[int],
    min_duration: Optional[str],
) -> List[Dict[str, Any]]:
    """Zipkin API: GET /api/v2/traces"""
    params = {"limit": limit}
    if service:
        params["serviceName"] = service
    if start:
        params["startTs"] = start
    if end:
        params["endTs"] = end
    if min_duration:
        params["lookback"] = min_duration

    api_url = f"{base_url}/api/v2/traces"
    try:
        r = requests.get(api_url, params=params, timeout=30)
        r.raise_for_status()
        raw_traces = r.json()
        return [_zipkin_trace_to_unified(t) for t in raw_traces]
    except Exception as e:
        logger.error(f"Zipkin API 请求失败: {e}")
        return []


def _jaeger_trace_to_unified(trace: Dict) -> Dict[str, Any]:
    """将 Jaeger trace 转为统一格式"""
    trace_id = trace.get("traceID", "")
    spans = trace.get("spans", [])
    process_map = {p.get("serviceName", ""): p for p in trace.get("processes", {}).values()}

    unified_spans = []
    for s in spans:
        proc_id = s.get("processID", "p1")
        proc = trace.get("processes", {}).get(proc_id, {})
        service_name = proc.get("serviceName", "")

        tags = {t.get("key"): t.get("value") for t in s.get("tags", []) if t.get("key")}
        version = tags.get("upstream_cluster", "") or tags.get("peer.service", "")
        service_version = _extract_version_from_cluster(version) or tags.get("version", "")

        unified_spans.append({
            "span_id": s.get("spanID"),
            "operation_name": s.get("operationName"),
            "duration": s.get("duration", 0),
            "service": service_name,
            "version": service_version,
            "tags": tags,
        })

    service_chain = _build_service_chain(unified_spans)
    return {
        "trace_id": trace_id,
        "spans": unified_spans,
        "service_chain": service_chain,
        "backend": "jaeger",
    }


def _zipkin_trace_to_unified(trace: List[Dict]) -> Dict[str, Any]:
    """将 Zipkin trace（span 数组）转为统一格式"""
    if not trace:
        return {"trace_id": "", "spans": [], "service_chain": [], "backend": "zipkin"}

    trace_id = trace[0].get("traceId", "")
    unified_spans = []
    for s in trace:
        local = s.get("localEndpoint", {}) or {}
        service_name = local.get("serviceName", "")
        tags = s.get("tags", {}) or {}
        if isinstance(tags, list):
            tags = {t.get("key"): t.get("value") for t in tags if t.get("key")}
        version = tags.get("upstream_cluster", "") or tags.get("peer.service", "")
        service_version = _extract_version_from_cluster(version) or tags.get("version", "")

        unified_spans.append({
            "span_id": s.get("id"),
            "operation_name": s.get("name"),
            "duration": s.get("duration", 0),
            "service": service_name,
            "version": service_version,
            "tags": tags,
        })

    service_chain = _build_service_chain(unified_spans)
    return {
        "trace_id": trace_id,
        "spans": unified_spans,
        "service_chain": service_chain,
        "backend": "zipkin",
    }


def _extract_version_from_cluster(cluster: str) -> Optional[str]:
    """
    从 Envoy upstream_cluster 提取 subset 版本。
    格式: outbound|80|v2|reviews.default.svc.cluster.local
    """
    if not cluster:
        return None
    parts = cluster.split("|")
    if len(parts) >= 3:
        return parts[2]
    return None


def _build_service_chain(spans: List[Dict]) -> List[Dict[str, str]]:
    """构建服务调用链，含 service 和 version"""
    seen = set()
    chain = []
    for s in spans:
        svc = s.get("service", "")
        ver = s.get("version", "")
        key = (svc, ver) if ver else svc
        if key not in seen and svc:
            seen.add(key)
            chain.append({"service": svc, "version": ver or None})
    return chain


def get_service_chain_from_traces(
    service: str = "productpage",
    limit: int = 10,
    namespace: str = "istio-system",
) -> List[Dict[str, str]]:
    """
    获取某服务的典型调用链（用于路由验证）。
    返回格式: [{"service": "productpage", "version": None}, {"service": "reviews", "version": "v2"}, ...]
    """
    traces = fetch_traces(service=service, limit=limit, namespace=namespace)
    if not traces:
        return []

    chains = [t["service_chain"] for t in traces if t.get("service_chain")]
    if not chains:
        return []

    def chain_len(c):
        return sum(1 for n in c if n.get("service"))

    largest = max(chains, key=chain_len)
    return largest


def verify_routing_from_traces(
    expected: Dict[str, str],
    service: str = "productpage",
    limit: int = 20,
    namespace: str = "istio-system",
) -> Dict[str, Any]:
    """
    根据 trace 验证路由是否符合预期。

    Args:
        expected: 期望的路由，如 {"reviews": "v2", "ratings": "v1"}
        service: 入口服务
        limit: trace 数量
        namespace: 命名空间

    Returns:
        {
            "matched": bool,
            "expected": {...},
            "actual": {"reviews": "v2", ...},  # 从 trace 提取的实际版本
            "mismatches": [{"service": "reviews", "expected": "v2", "actual": "v1"}],
            "sample_traces": int,
        }
    """
    traces = fetch_traces(service=service, limit=limit, namespace=namespace)
    actual = {}
    for t in traces:
        for node in t.get("service_chain", []):
            svc = node.get("service", "").split(".")[0]
            ver = node.get("version")
            if svc and (svc not in actual or ver):
                actual[svc] = ver

    mismatches = []
    for svc, exp_ver in expected.items():
        act_ver = actual.get(svc)
        if exp_ver != act_ver:
            mismatches.append({
                "service": svc,
                "expected": exp_ver,
                "actual": act_ver,
            })

    return {
        "matched": len(mismatches) == 0,
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
        "sample_traces": len(traces),
    }


def get_services_list(namespace: str = "istio-system") -> List[str]:
    """
    获取 trace 中出现的所有服务列表。
    Jaeger: GET /api/services
    Zipkin: GET /api/v2/services
    """
    cfg = get_observability_config(namespace=namespace)
    url = cfg.get("tracing_url") or cfg.get("zipkin_url")
    backend = cfg.get("tracing_backend") or "jaeger"

    if not url:
        return []

    url = url.rstrip("/")
    try:
        if backend == "jaeger":
            r = requests.get(f"{url}/api/services", timeout=10)
        else:
            r = requests.get(f"{url}/api/v2/services", timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("data", data) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning(f"获取服务列表失败: {e}")
        return []
