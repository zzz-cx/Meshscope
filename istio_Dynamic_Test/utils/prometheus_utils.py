import requests
from typing import Any, Dict, List

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
