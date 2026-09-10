import requests
from typing import Any, Dict, List, Optional


def query_response_flags_uO(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """
    查询 response_flags=UO（Upstream Overflow）请求数，熔断触发的直接证据。
    需 Istio 配置 access log 或 metrics 暴露 response_flags。
    """
    q = 'sum(istio_requests_total{response_flags="UO"})'
    if destination_service:
        svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
        q = f'sum(istio_requests_total{{response_flags="UO",destination_service="{svc_fqdn}"}})'
    try:
        client = PrometheusClient(prometheus_url)
        result = client.query(q)
        if result and len(result) > 0:
            return int(float(result[0].get("value", [0, 0])[1]))
    except Exception:
        pass
    return 0


def query_response_flags_ut(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """查询 response_flags=UT（Upstream Timeout）请求数。"""
    q = 'sum(istio_requests_total{response_flags="UT"})'
    if destination_service:
        svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
        q = f'sum(istio_requests_total{{response_flags="UT",destination_service="{svc_fqdn}"}})'
    try:
        client = PrometheusClient(prometheus_url)
        result = client.query(q)
        if result and len(result) > 0:
            return int(float(result[0].get("value", [0, 0])[1]))
    except Exception:
        pass
    return 0


def query_response_flags_dc(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """查询 response_flags=DC（Downstream Connection Termination）请求数。"""
    q = 'sum(istio_requests_total{response_flags="DC"})'
    if destination_service:
        svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
        q = f'sum(istio_requests_total{{response_flags="DC",destination_service="{svc_fqdn}"}})'
    try:
        client = PrometheusClient(prometheus_url)
        result = client.query(q)
        if result and len(result) > 0:
            return int(float(result[0].get("value", [0, 0])[1]))
    except Exception:
        pass
    return 0


def query_503_count(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """
    查询 503 请求总数（用于熔断验证）。
    若 destination_service 为空则查全集群 503；否则限定目标服务。
    """
    q = 'sum(istio_requests_total{response_code="503"})'
    if destination_service:
        svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
        q = f'sum(istio_requests_total{{response_code="503",destination_service="{svc_fqdn}"}})'
    try:
        client = PrometheusClient(prometheus_url)
        result = client.query(q)
        if result and len(result) > 0:
            return int(float(result[0].get("value", [0, 0])[1]))
    except Exception:
        pass
    return 0


def query_429_count(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """
    查询 429（Too Many Requests）计数，用于限流验证。
    destination_service 传短名（如 productpage），内部拼 FQDN。
    """
    q = 'sum(istio_requests_total{response_code="429"})'
    if destination_service:
        svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
        q = (
            f'sum(istio_requests_total{{response_code="429",destination_service="{svc_fqdn}"}})'
        )
    try:
        client = PrometheusClient(prometheus_url)
        result = client.query(q)
        if result and len(result) > 0:
            return int(float(result[0].get("value", [0, 0])[1]))
    except Exception:
        pass
    return 0


def query_ratelimit_over_limit(
    prometheus_url: str,
    destination_service: str = "",
    namespace: str = "default",
) -> int:
    """
    尝试查询 Envoy ratelimit over_limit 类指标（集群/版本差异大，失败则返回 0）。
    常见候选：envoy_http_ratelimit_over_limit、envoy_ratelimit_over_limit、
    istio_global_rate_limit_over_limit（视导出器而定）。
    """
    candidates = [
        "envoy_http_ratelimit_over_limit",
        "envoy_ratelimit_over_limit",
    ]
    try:
        client = PrometheusClient(prometheus_url)
        for metric in candidates:
            try:
                if destination_service:
                    svc_fqdn = f"{destination_service}.{namespace}.svc.cluster.local"
                    q = f'sum({metric}{{destination_service="{svc_fqdn}"}})'
                else:
                    q = f"sum({metric})"
                result = client.query(q)
                if result and len(result) > 0:
                    v = int(float(result[0].get("value", [0, 0])[1]))
                    if v > 0:
                        return v
            except Exception:
                continue
        for metric in candidates:
            try:
                result = client.query(f"sum({metric})")
                if result and len(result) > 0:
                    return int(float(result[0].get("value", [0, 0])[1]))
            except Exception:
                continue
    except Exception:
        pass
    return 0


def query_traffic_distribution(
    prometheus_url: str,
    service: str,
    versions: List[str],
    namespace: str = "default",
) -> Dict[str, int]:
    """
    查询目标服务各版本的请求总数（用于流量分布验证）。
    返回 {version: count}，如 {"v1": 100, "v2": 400}。
    """
    svc_fqdn = f"{service}.{namespace}.svc.cluster.local"
    q = (
        'sum(istio_requests_total{destination_service="%s"}) by (destination_version)'
        % svc_fqdn
    )
    client = PrometheusClient(prometheus_url)
    result = client.query(q)
    by_ver: Dict[str, int] = {}
    for item in result:
        ver = item.get("metric", {}).get("destination_version", "unknown")
        val = int(float(item.get("value", [0, 0])[1]))
        by_ver[ver] = by_ver.get(ver, 0) + val
    return by_ver


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def query(self, promql: str) -> List[Dict[str, Any]]:
        """
        执行即时 PromQL 查询，返回结果列表。
        """
        url = f"{self.base_url}/api/v1/query"
        resp = requests.get(url, params={"query": promql})
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "success":
            return data["data"]["result"]
        else:
            raise RuntimeError(f"Prometheus 查询失败: {data}")

    def query_range(self, promql: str, start: str, end: str, step: str = "30s") -> List[Dict[str, Any]]:
        """
        执行区间 PromQL 查询，返回时间序列结果。
        start/end: ISO8601 格式时间字符串或 unix 时间戳
        step: 步长，默认30s
        """
        url = f"{self.base_url}/api/v1/query_range"
        params = {
            "query": promql,
            "start": start,
            "end": end,
            "step": step
        }
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "success":
            return data["data"]["result"]
        else:
            raise RuntimeError(f"Prometheus 区间查询失败: {data}")
