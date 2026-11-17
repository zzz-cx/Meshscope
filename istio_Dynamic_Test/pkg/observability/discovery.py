"""
从 K8s 集群动态获取可观测工具（Zipkin、Ingress、Prometheus、Kiali 等）的访问地址。
支持环境变量覆盖，避免硬编码。
"""
import json
import os
import subprocess
from typing import Optional
from urllib.parse import urlparse, urlunparse


def _get_cluster_host() -> str:
    """获取集群访问 host（用于 NodePort 服务），优先用 env，否则取首节点 IP。"""
    host = os.environ.get("K8S_CLUSTER_HOST")
    if host:
        return host
    raw = _run_kubectl(["get", "nodes", "-o", "jsonpath={.items[0].status.addresses[?(@.type==\"InternalIP\")].address}"])
    return raw or "localhost"


def _run_kubectl(args: list[str], timeout: int = 10) -> Optional[str]:
    """执行 kubectl 命令，返回 stdout 或 None。"""
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_ingress_url(
    path: str = "/productpage",
    namespace: str = "istio-system",
    service_name: str = "istio-ingressgateway",
) -> str:
    """
    从 istio-ingressgateway 获取入口 URL。
    优先使用 LoadBalancer 的 external IP + port 80，否则使用 NodePort。
    """
    env_url = os.environ.get("ISTIO_INGRESS_URL")
    if env_url:
        parsed = urlparse(env_url)
        if parsed.path and parsed.path.strip("/"):
            return env_url  # 已包含 path，直接返回
        # 仅 base URL，追加 path
        path = path if path.startswith("/") else "/" + path
        return urlunparse(parsed._replace(path=path))

    env_host = os.environ.get("ISTIO_INGRESS_HOST")
    env_port = os.environ.get("ISTIO_INGRESS_PORT")

    raw = _run_kubectl(["get", "svc", service_name, "-n", namespace, "-o", "json"])
    if not raw:
        if env_host:
            port = env_port or "80"
            return f"http://{env_host}:{port}{path}"
        return f"http://localhost{path}"  # 默认回退

    try:
        data = json.loads(raw)
        spec = data.get("spec", {})
        status = data.get("status", {})

        # LoadBalancer external IP
        ingress = (status.get("loadBalancer") or {}).get("ingress") or []
        external_ip = None
        if ingress:
            external_ip = ingress[0].get("ip") or ingress[0].get("hostname")

        # 端口：LoadBalancer 用 port 80，否则用 NodePort
        ports = spec.get("ports", [])
        http_port = None
        node_port = None
        for p in ports:
            if p.get("port") == 80 or p.get("name") in ("http2", "http"):
                http_port = p.get("port", 80)
                node_port = p.get("nodePort")
                break

        host = external_ip or env_host or "localhost"
        if external_ip and http_port == 80:
            # LoadBalancer 直接使用 80
            return f"http://{host}{path}"
        if node_port:
            return f"http://{host}:{node_port}{path}"
        if env_port:
            return f"http://{host}:{env_port}{path}"
        return f"http://{host}:{http_port or 80}{path}"
    except (json.JSONDecodeError, KeyError, IndexError):
        if env_host:
            return f"http://{env_host}:{env_port or '80'}{path}"
        return f"http://localhost{path}"


def get_tracing_config(
    namespace: str = "istio-system",
) -> Optional[dict]:
    """
    从集群获取链路追踪服务配置，包含 URL 和后端类型。
    用于 trace_utils 选择正确的 API（Jaeger vs Zipkin）。

    返回: {"url": str, "backend": "jaeger"|"zipkin"} 或 None
    """
    env_url = os.environ.get("ZIPKIN_URL") or os.environ.get("JAEGER_URL")
    if env_url:
        url = env_url.rstrip("/")
        # TRACING_HOST 覆盖 host（用于 port-forward 在远程机器 192.0.2.10 上时）
        host_override = os.environ.get("TRACING_HOST") or os.environ.get("K8S_CLUSTER_HOST")
        if host_override and ("localhost" in url or "127.0.0.1" in url):
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url)
            url = urlunparse(p._replace(netloc=f"{host_override}:{p.port or (16686 if '16686' in url else 9411)}"))
        backend = "jaeger" if "16686" in url else "zipkin"
        return {"url": url, "backend": backend}

    # Jaeger API 在 16686 端口的 /jaeger/api/* 返回 JSON；优先 Jaeger 服务
    for svc_name, backend in [("jaeger-all-in-one", "jaeger"), ("jaeger-query", "jaeger"), ("tracing", "jaeger"), ("zipkin", "zipkin")]:
        raw = _run_kubectl(["get", "svc", svc_name, "-n", namespace, "-o", "json"])
        if not raw:
            continue
        try:
            data = json.loads(raw)
            spec = data.get("spec", {})
            ports = spec.get("ports", [])
            # Jaeger API 在 16686 的 /jaeger/api/* 返回 JSON；Zipkin 在 9411
            target_port = None
            node_port = None
            preferred = (16686, 16685, 9411, 80) if backend == "jaeger" else (9411, 16686, 80)
            for want in preferred:
                for p in ports:
                    pt = p.get("port")
                    port_name = (p.get("name") or "").lower()
                    if pt == want or (backend == "jaeger" and want == 16686 and "query" in port_name):
                        target_port = pt
                        node_port = p.get("nodePort")
                        break
                if target_port:
                    break
            if not target_port and ports:
                target_port = ports[0].get("port")
                node_port = ports[0].get("nodePort")

            if not target_port:
                continue

            svc_type = spec.get("type", "ClusterIP")
            status = data.get("status", {})
            ingress = (status.get("loadBalancer") or {}).get("ingress") or []
            # LoadBalancer: 用 external IP；NodePort/ClusterIP: 用集群 master 主机地址（集群外通过 port-forward 访问）
            if ingress:
                host = ingress[0].get("ip") or ingress[0].get("hostname")
            else:
                # NodePort 或 ClusterIP：用 K8S_CLUSTER_HOST 或首节点 IP，集群外需在 master 上 port-forward
                host = _get_cluster_host()
            port = node_port or target_port
            # Jaeger 端口 16685 时，集群外常用 port-forward 16686:16685，故返回 16686
            if backend == "jaeger" and port == 16685 and not node_port:
                port = 16686
            return {"url": f"http://{host}:{port}", "backend": backend}
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return None


def get_zipkin_url(
    namespace: str = "istio-system",
    service_names: tuple = ("zipkin", "jaeger-query", "tracing"),
) -> Optional[str]:
    """
    从集群获取 Zipkin/Jaeger 追踪服务 URL。
    按 service_names 顺序查找，找到第一个即返回。
    兼容旧接口，新代码建议使用 get_tracing_config() 以区分 Jaeger/Zipkin。
    """
    cfg = get_tracing_config(namespace)
    return cfg["url"] if cfg else None


def get_prometheus_url(namespace: str = "istio-system") -> Optional[str]:
    """从集群获取 Prometheus URL。"""
    env_url = os.environ.get("PROMETHEUS_URL")
    if env_url:
        return env_url.rstrip("/")

    raw = _run_kubectl(["get", "svc", "prometheus", "-n", namespace, "-o", "json"])
    if not raw:
        return None
    try:
        data = json.loads(raw)
        spec = data.get("spec", {})
        status = data.get("status", {})
        ports = spec.get("ports", [])
        p = next((x for x in ports if x.get("port") == 9090), ports[0] if ports else None)
        if not p:
            return None
        node_port = p.get("nodePort") or p.get("port")
        ingress = (status.get("loadBalancer") or {}).get("ingress") or []
        host = ingress[0].get("ip") or ingress[0].get("hostname") if ingress else _get_cluster_host()
        return f"http://{host}:{node_port}"
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


def get_kiali_url(namespace: str = "istio-system") -> Optional[str]:
    """从集群获取 Kiali URL。"""
    env_url = os.environ.get("KIALI_URL")
    if env_url:
        return env_url.rstrip("/")

    raw = _run_kubectl(["get", "svc", "kiali", "-n", namespace, "-o", "json"])
    if not raw:
        return None
    try:
        data = json.loads(raw)
        spec = data.get("spec", {})
        status = data.get("status", {})
        ports = spec.get("ports", [])
        p = next((x for x in ports if x.get("port") == 20001), ports[0] if ports else None)
        if not p:
            return None
        node_port = p.get("nodePort") or p.get("port")
        ingress = (status.get("loadBalancer") or {}).get("ingress") or []
        host = ingress[0].get("ip") or ingress[0].get("hostname") if ingress else _get_cluster_host()
        return f"http://{host}:{node_port}"
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


def get_observability_config(
    ingress_path: str = "/productpage",
    namespace: str = "istio-system",
) -> dict:
    """
    获取所有可观测工具 URL 的配置字典。
    用于 trace_utils、trace_fetcher、prometheus_utils 等模块。

    返回:
        zipkin_url: 链路追踪 URL（兼容旧名，实际可能是 Jaeger）
        tracing_url: 同上，语义更清晰
        tracing_config: {"url": str, "backend": "jaeger"|"zipkin"}，用于 trace_fetcher 选择 API
        tracing_backend: "jaeger" | "zipkin"，用于选择 Jaeger API 或 Zipkin API
        ingress_url, prometheus_url, kiali_url: 其他可观测入口
    """
    tracing_cfg = get_tracing_config(namespace)
    zipkin_url = tracing_cfg["url"] if tracing_cfg else None
    return {
        "zipkin_url": zipkin_url,
        "tracing_url": zipkin_url,
        "tracing_config": tracing_cfg,
        "tracing_backend": tracing_cfg["backend"] if tracing_cfg else None,
        "ingress_url": get_ingress_url(path=ingress_path),
        "prometheus_url": get_prometheus_url(namespace),
        "kiali_url": get_kiali_url(namespace),
    }
