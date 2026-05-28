"""gRPC 目标地址与方法解析。"""

from typing import Tuple
from urllib.parse import urlparse

from istio_Dynamic_Test.internal.models.testcase import TestCase


def resolve_grpc_method(test_case: TestCase) -> str:
    """完整方法名，如 grpc.health.v1.Health/Check。"""
    if test_case.grpc_method:
        return test_case.grpc_method.strip()

    meta = test_case.metadata or {}
    params = meta.get("request_params") or meta
    for key in ("grpc_method", "method", "grpc_service_method"):
        if params.get(key):
            return str(params[key]).strip()

    path = (test_case.path or "").strip().lstrip("/")
    if path and "/" in path and "." in path.split("/", 1)[0]:
        return path

    return "grpc.health.v1.Health/Check"


def _split_host_port(raw: str, default_port: int) -> Tuple[str, int]:
    raw = (raw or "").strip()
    if not raw:
        return "localhost", default_port
    if raw.startswith("["):
        end = raw.find("]")
        if end > 0:
            host = raw[1:end]
            rest = raw[end + 1 :]
            port = int(rest.lstrip(":")) if rest.startswith(":") else default_port
            return host, port
    if ":" in raw:
        host, port_s = raw.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return raw, default_port
    return raw, default_port


def resolve_grpc_endpoint(test_case: TestCase) -> Tuple[str, int, str, str]:
    """
    解析 gRPC 连接端点。

    Returns:
        (host, port, authority, full_method)
    """
    method = resolve_grpc_method(test_case)
    authority = (
        test_case.host
        or test_case.headers.get(":authority")
        or test_case.headers.get("host")
        or ""
    ).strip()

    meta = test_case.metadata or {}
    if meta.get("grpc_target"):
        host, port = _split_host_port(str(meta["grpc_target"]), 80)
        return host, test_case.grpc_port or port, authority or host, method

    target = (test_case.target_url or "").strip()
    if target.startswith("http://") or target.startswith("https://"):
        parsed = urlparse(target)
        host = parsed.hostname or authority or "localhost"
        default_port = 443 if parsed.scheme == "https" else 80
        port = test_case.grpc_port or parsed.port or default_port
        return host, port, authority or host, method

    if target and "://" not in target:
        host, port = _split_host_port(target, test_case.grpc_port or 80)
        return host, test_case.grpc_port or port, authority or host, method

    if authority:
        return authority, test_case.grpc_port or 80, authority, method

    return "localhost", test_case.grpc_port or 80, authority or "localhost", method
