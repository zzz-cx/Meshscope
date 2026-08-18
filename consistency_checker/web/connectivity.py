"""探测 Kubernetes、SSH、Prometheus 及其他可观测组件是否可达。"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from consistency_checker.config import GlobalConfig

_HTTP_TIMEOUT = 1.2
_TCP_TIMEOUT = 0.9
_CACHE_TTL = 8.0
_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}

_NAMES = {
    "k8s": "Kubernetes 集群",
    "ssh": "SSH 节点",
    "prometheus": "Prometheus",
    "tracing": "Jaeger / Zipkin",
    "kiali": "Kiali",
    "grafana": "Grafana",
    "ingress": "Ingress 入口",
}


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_TCP_TIMEOUT):
            return True
    except OSError:
        return False


def _http_ok(url: str) -> tuple:
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT, allow_redirects=True)
        ok = resp.status_code < 500
        return ok, f"HTTP {resp.status_code}", url
    except requests.RequestException as exc:
        return False, str(exc.__class__.__name__), url


def _item(item_id: str, name: str, status: str, detail: str, target: str = "") -> Dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "status": status,
        "detail": detail,
        "target": target,
    }


def _probe_kubectl() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            line = (result.stdout or "").strip().splitlines()[:1]
            return _item("k8s", "Kubernetes 集群", "up", line[0] if line else "cluster-info 正常", "kubectl")
        err = (result.stderr or result.stdout or "kubectl 失败").strip().splitlines()[:1]
        return _item("k8s", "Kubernetes 集群", "down", err[0] if err else "无法连接集群", "kubectl")
    except FileNotFoundError:
        return _item("k8s", "Kubernetes 集群", "unknown", "本机未安装 kubectl", "kubectl")
    except subprocess.TimeoutExpired:
        return _item("k8s", "Kubernetes 集群", "down", "cluster-info 超时", "kubectl")


def invalidate_cache() -> None:
    _CACHE["ts"] = 0.0
    _CACHE["data"] = None


def _probe_ssh(cfg: GlobalConfig) -> Dict[str, Any]:
    host = cfg.ssh_host
    port = int(getattr(cfg, "ssh_port", None) or 22)
    if not host:
        return _item("ssh", "SSH 节点", "unknown", "未配置 SSH_HOST", "")
    target = f"{host}:{port}"
    if _tcp_open(host, port):
        return _item("ssh", "SSH 节点", "up", f"{target} 端口可达", target)
    return _item("ssh", "SSH 节点", "down", f"{target} 不可达", target)


def _host_from_cfg(cfg: GlobalConfig) -> Optional[str]:
    return cfg.ssh_host or cfg.k8s_host or os.getenv("K8S_CLUSTER_HOST")


def _candidate_urls(*sources: Optional[str]) -> List[str]:
    urls = []
    for raw in sources:
        cleaned = (raw or "").strip().rstrip("/")
        if cleaned and cleaned not in urls:
            urls.append(cleaned)
    return urls


def _urls_prefer(explicit: List[Optional[str]], fallback: List[Optional[str]]) -> List[str]:
    chosen = _candidate_urls(*explicit)
    return chosen if chosen else _candidate_urls(*fallback)


def _probe_http_service(item_id: str, name: str, urls: List[str]) -> Dict[str, Any]:
    if not urls:
        return _item(item_id, name, "unknown", "未配置地址", "")
    last_err = "不可达"
    last_url = urls[0]
    for url in urls:
        parsed = urlparse(url if "://" in url else "http://" + url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host and not _tcp_open(host, port):
            last_err = f"{host}:{port} 端口关闭"
            last_url = url
            continue
        ok, detail, used = _http_ok(url)
        if ok:
            return _item(item_id, name, "up", detail, used)
        last_err, last_url = detail, used
        probe = url.rstrip("/") + "/-/ready"
        if item_id == "prometheus":
            ok, detail, used = _http_ok(probe)
            if ok:
                return _item(item_id, name, "up", detail, used)
    return _item(item_id, name, "down", last_err, last_url)


def probe_connectivity(cfg: GlobalConfig, force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["data"]

    host = _host_from_cfg(cfg)
    derived_prom = f"http://{host}:31012" if host else ""
    derived_jaeger = f"http://{host}:16686" if host else ""
    derived_kiali = f"http://{host}:20001" if host else ""
    derived_grafana = f"http://{host}:3000" if host else ""
    derived_ingress = cfg.get_ingress_url() if host else ""

    tasks = {
        "k8s": _probe_kubectl,
        "ssh": lambda: _probe_ssh(cfg),
        "prometheus": lambda: _probe_http_service(
            "prometheus",
            _NAMES["prometheus"],
            _urls_prefer([cfg.prometheus_url], [derived_prom]),
        ),
        "tracing": lambda: _probe_http_service(
            "tracing",
            _NAMES["tracing"],
            _urls_prefer([cfg.jaeger_url, cfg.zipkin_url], [derived_jaeger]),
        ),
        "kiali": lambda: _probe_http_service(
            "kiali",
            _NAMES["kiali"],
            _urls_prefer([cfg.kiali_url], [derived_kiali]),
        ),
        "grafana": lambda: _probe_http_service(
            "grafana",
            _NAMES["grafana"],
            _urls_prefer([cfg.grafana_url], [derived_grafana]),
        ),
        "ingress": lambda: _probe_http_service(
            "ingress",
            _NAMES["ingress"],
            _urls_prefer([cfg.ingress_url], [derived_ingress]),
        ),
    }

    order = ("k8s", "ssh", "prometheus", "tracing", "kiali", "grafana", "ingress")
    by_id: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(fn): key for key, fn in tasks.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                by_id[key] = fut.result()
            except Exception as exc:
                by_id[key] = _item(key, _NAMES.get(key, key), "down", str(exc), "")

    items = [
        by_id.get(key, _item(key, _NAMES.get(key, key), "unknown", "未检测", ""))
        for key in order
    ]
    up = sum(1 for x in items if x["status"] == "up")
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "connected_count": up,
        "total": len(items),
        "items": items,
    }
    _CACHE["ts"] = time.time()
    _CACHE["data"] = result
    return result
