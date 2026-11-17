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


def _version_from_prom_metric(metric: Dict[str, Any]) -> str:
    from istio_Dynamic_Test.internal.traffic.split_observe import version_from_workload

    for key in (
        "destination_canonical_revision",
        "destination_version",
        "destination_subset",
    ):
        val = str((metric or {}).get(key) or "").strip()
        if val and val.lower() != "unknown":
            return val
    return version_from_workload(
        str((metric or {}).get("destination_workload") or "")
    )


def _traffic_distribution_queries(service: str, namespace: str) -> List[str]:
    svc = (service or "").split(".")[0]
    ns = namespace or "default"
    if not svc or svc == "*":
        return []
    fqdn = f"{svc}.{ns}.svc.cluster.local"
    selectors = [
        f'destination_service="{fqdn}",reporter="destination"',
        f'destination_canonical_service="{svc}",destination_service_namespace="{ns}",reporter="destination"',
        f'destination_service=~"{svc}\\\\..*",reporter="destination"',
        f'destination_workload=~"{svc}-v.*",destination_service_namespace="{ns}",reporter="destination"',
    ]
    groupings = [
        "destination_canonical_revision",
        "destination_version",
        "destination_workload",
        "destination_canonical_revision,destination_version,destination_workload",
    ]
    return [f"sum(istio_requests_total{{{sel}}}) by ({grp})" for sel in selectors for grp in groupings]


def _parse_distribution_result(result: List[Dict[str, Any]]) -> Dict[str, int]:
    by_ver: Dict[str, int] = {}
    for item in result or []:
        ver = _version_from_prom_metric(item.get("metric") or {})
        val = int(float(item.get("value", [0, 0])[1]))
        by_ver[ver] = by_ver.get(ver, 0) + val
    return by_ver


def query_traffic_distribution(
    prometheus_url: str,
    service: str,
    versions: List[str],
    namespace: str = "default",
    promql: Optional[str] = None,
) -> Dict[str, int]:
    """
    查询目标服务各版本的请求总数（用于流量分布验证）。
    返回 {version: count}，如 {"v1": 100, "v2": 400}。

    Istio 1.5+ 常用 destination_canonical_revision；旧指标用 destination_version。
    传入 promql 时固定该查询，保证打流前后快照可比。
    """
    data, _ = query_traffic_distribution_ex(
        prometheus_url, service, versions, namespace, promql=promql
    )
    return data


def query_traffic_distribution_ex(
    prometheus_url: str,
    service: str,
    versions: List[str],
    namespace: str = "default",
    promql: Optional[str] = None,
) -> tuple:
    """返回 (counts, used_promql)。"""
    from istio_Dynamic_Test.internal.traffic.split_observe import version_signal_usable

    client = PrometheusClient(prometheus_url)
    queries = [promql] if promql else _traffic_distribution_queries(service, namespace)
    best: Dict[str, int] = {}
    used = promql or (queries[0] if queries else "")
    for q in queries:
        if not q:
            continue
        try:
            by_ver = _parse_distribution_result(client.query(q))
        except Exception:
            continue
        if version_signal_usable(by_ver, versions):
            return by_ver, q
        if by_ver and not best:
            best = by_ver
            used = q
    return best, used


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def query(self, promql: str) -> List[Dict[str, Any]]:
        """
        执行即时 PromQL 查询，返回结果列表。
        """
        url = f"{self.base_url}/api/v1/query"
        resp = requests.get(url, params={"query": promql}, timeout=8)
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
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "success":
            return data["data"]["result"]
        else:
            raise RuntimeError(f"Prometheus 区间查询失败: {data}")
