"""定位真实流量入口。

ingress_url 必须是网关 origin（scheme://host:port），不能带 /productpage 这类业务路径。
用例 path（如 /demo/reviews）再拼上去。
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from istio_Dynamic_Test.internal.models.testcase import TestCase
from istio_Dynamic_Test.internal.traffic.protocols.http.url import compose_request_url


def normalize_ingress_base(url: Optional[str]) -> str:
    """去掉 path/query，避免 /productpage 和 /demo/reviews 拼成错误地址。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "http://" + raw)
    if not parsed.netloc:
        return raw.rstrip("/")
    scheme = parsed.scheme or "http"
    return f"{scheme}://{parsed.netloc}"


def discover_ingress_base(
    namespace: str = "istio-system",
    service_name: str = "istio-ingressgateway",
) -> str:
    """从 istio-ingressgateway 解析入口 origin。优先 NodePort，便于从节点 IP 访问。"""
    env_url = os.environ.get("ISTIO_INGRESS_URL")
    if env_url:
        return normalize_ingress_base(env_url)
    try:
        result = subprocess.run(
            ["kubectl", "get", "svc", service_name, "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        data = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return ""
    spec = data.get("spec") or {}
    status = data.get("status") or {}
    ingress = ((status.get("loadBalancer") or {}).get("ingress") or [])
    external_ip = ""
    if ingress:
        external_ip = ingress[0].get("ip") or ingress[0].get("hostname") or ""
    node_ip = os.environ.get("K8S_CLUSTER_HOST") or external_ip or _first_node_ip()
    node_port = None
    http_port = None
    for port in spec.get("ports") or []:
        if port.get("port") == 80 or port.get("name") in ("http2", "http"):
            http_port = port.get("port")
            node_port = port.get("nodePort")
            break
    host = node_ip or "127.0.0.1"
    if node_port:
        return f"http://{host}:{int(node_port)}"
    if external_ip and http_port in (80, None):
        return f"http://{external_ip}"
    if http_port:
        return f"http://{host}:{int(http_port)}"
    return ""


def resolve_ingress_base(configured: Optional[str] = None) -> str:
    """配置优先，否则从集群发现。始终返回不带业务 path 的 origin。"""
    base = normalize_ingress_base(configured)
    if base:
        return base
    return discover_ingress_base()


def resolve_traffic_entry(
    test_case: TestCase,
    ingress_url: Optional[str] = None,
) -> Tuple[str, Dict[str, str], str]:
    """返回 (url, headers, reason)。"""
    configured = test_case.target_url or ingress_url or ""
    base = resolve_ingress_base(configured)
    path = test_case.path or "/"
    url = compose_request_url(base, path)
    headers = _headers_for(test_case)
    if not base:
        return url, headers, "missing_entry"
    parsed = urlparse(base)
    if path in ("", "/") and (test_case.host or "") not in ("", "*"):
        return url, headers, "ingress_host_match"
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url, headers, "ingress"
    return url, headers, "raw_url"


def _first_node_ip() -> str:
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "nodes",
                "-o",
                'jsonpath={.items[0].status.addresses[?(@.type=="InternalIP")].address}',
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _headers_for(test_case: TestCase) -> Dict[str, str]:
    headers = dict(test_case.headers or {})
    host = test_case.host
    if host == "*" and test_case.source_service:
        host = test_case.source_service
    if host and host != "*" and "Host" not in headers and "host" not in headers:
        headers["Host"] = host.split(".")[0]
    if "User-Agent" not in headers and "user-agent" not in headers:
        headers["User-Agent"] = "meshscope-split/1.0"
    return headers
