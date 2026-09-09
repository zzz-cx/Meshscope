#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实流量实验：部署 N 个 meshscope 服务到指定命名空间。"""


import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import yaml

# 国内节点可直接拉取；若本机已有同内容镜像可改 IfNotPresent
IMAGE = "docker.m.daocloud.io/library/nginx:1.25-alpine"
PORT = 80


def svc_name(i: int) -> str:
    return "meshscope-svc-{0:04d}".format(i)


def path_for(i: int) -> str:
    return "/s{0}/".format(i)


def _deployment(ns: str, i: int, version: str) -> dict:
    name = svc_name(i)
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "{0}-{1}".format(name, version),
            "namespace": ns,
            "labels": {"app": name, "version": version, "meshscope/exp": "real-traffic"},
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name, "version": version}},
            "template": {
                "metadata": {
                    "labels": {"app": name, "version": version, "meshscope/exp": "real-traffic"},
                    "annotations": {
                        # 轻量：仅在需要 sidecar 的命名空间自动注入
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "image": IMAGE,
                            "imagePullPolicy": "IfNotPresent",  # 首次由 kubelet 拉取 DaoCloud
                            "ports": [{"containerPort": PORT, "name": "http"}],
                            "resources": {
                                "requests": {"cpu": "20m", "memory": "32Mi"},
                                "limits": {"cpu": "200m", "memory": "128Mi"},
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/", "port": PORT},
                                "initialDelaySeconds": 2,
                                "periodSeconds": 5,
                            },
                        }
                    ]
                },
            },
        },
    }


def _service(ns: str, i: int) -> dict:
    name = svc_name(i)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"app": name, "meshscope/exp": "real-traffic"},
        },
        "spec": {
            "selector": {"app": name},
            "ports": [{"name": "http", "port": PORT, "targetPort": PORT}],
        },
    }


def _destination_rule(ns: str, i: int) -> dict:
    name = svc_name(i)
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "DestinationRule",
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"meshscope/exp": "real-traffic"},
        },
        "spec": {
            "host": name,
            "subsets": [
                {"name": "v1", "labels": {"version": "v1"}},
                {"name": "v2", "labels": {"version": "v2"}},
            ],
            "trafficPolicy": {
                "connectionPool": {
                    "http": {"http1MaxPendingRequests": 100, "maxRequestsPerConnection": 10}
                }
            },
        },
    }


def _gateway(ns: str) -> dict:
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "Gateway",
        "metadata": {"name": "meshscope-gw", "namespace": ns},
        "spec": {
            "selector": {"istio": "ingressgateway"},
            "servers": [
                {
                    "port": {"number": 80, "name": "http", "protocol": "HTTP"},
                    "hosts": ["*"],
                }
            ],
        },
    }


def _ingress_virtual_service(ns: str, n_services: int) -> dict:
    """入口 VS：精确匹配 /s{i}/ -> 服务（不用 prefix，避免抢走 /s{i}/feat-... 功能路由）。"""
    http_routes = []
    for i in range(1, n_services + 1):
        http_routes.append(
            {
                "match": [
                    {"uri": {"exact": path_for(i)}},
                    {"uri": {"exact": path_for(i).rstrip("/")}},
                ],
                "rewrite": {"uri": "/"},
                "route": [
                    {
                        "destination": {
                            "host": svc_name(i),
                            "port": {"number": PORT},
                            "subset": "v1",
                        }
                    }
                ],
            }
        )
    return {
        "apiVersion": "networking.istio.io/v1beta1",
        "kind": "VirtualService",
        "metadata": {
            "name": "meshscope-ingress",
            "namespace": ns,
            "labels": {"meshscope/exp": "real-traffic"},
        },
        "spec": {
            "hosts": ["*"],
            "gateways": ["meshscope-gw"],
            "http": http_routes,
        },
    }


def build_manifests(ns: str, n_services: int) -> List[dict]:
    docs = [_gateway(ns)]
    for i in range(1, n_services + 1):
        docs.append(_service(ns, i))
        docs.append(_deployment(ns, i, "v1"))
        docs.append(_deployment(ns, i, "v2"))
        docs.append(_destination_rule(ns, i))
    docs.append(_ingress_virtual_service(ns, n_services))
    return docs


def dump_yaml(docs: List[dict]) -> str:
    return "---\n".join(
        yaml.safe_dump(d, default_flow_style=False, allow_unicode=True) for d in docs
    )


def kubectl(args: List[str], stdin: Optional[str] = None, timeout: int = 120) -> str:
    proc = subprocess.run(
        ["kubectl"] + args,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "kubectl {0} failed: {1}".format(" ".join(args), proc.stderr or proc.stdout)
        )
    return proc.stdout


def wait_namespace_gone(ns: str, timeout_sec: int = 300) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        proc = subprocess.run(
            ["kubectl", "get", "ns", ns],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if proc.returncode != 0:
            return
        time.sleep(2)
    raise RuntimeError("timeout waiting ns {0} to terminate".format(ns))


def ensure_namespace(ns: str) -> None:
    proc = subprocess.run(
        ["kubectl", "get", "ns", ns, "-o", "jsonpath={.status.phase}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    phase = (proc.stdout or "").strip()
    if proc.returncode == 0 and phase == "Terminating":
        print("[deploy] waiting ns {0} terminate...".format(ns))
        wait_namespace_gone(ns)
        phase = ""
    if proc.returncode != 0 or not phase:
        kubectl(["create", "ns", ns])
    # sidecar 自动注入
    kubectl(
        [
            "label",
            "namespace",
            ns,
            "istio-injection=enabled",
            "--overwrite",
        ]
    )


def deploy(ns: str, n_services: int, out_file: Optional[Path] = None) -> Path:
    ensure_namespace(ns)
    docs = build_manifests(ns, n_services)
    content = dump_yaml(docs)
    if out_file is None:
        out_file = Path("results") / "manifests" / "services_{0}_{1}.yaml".format(ns, n_services)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(content, encoding="utf-8")
    print("[deploy] applying {0} services to ns={1} ...".format(n_services, ns))
    kubectl(["apply", "-f", "-"], stdin=content, timeout=300)
    return out_file


def wait_ready(ns: str, n_services: int, timeout_sec: int = 600) -> None:
    print("[deploy] waiting deployments ready (timeout={0}s)...".format(timeout_sec))
    deadline = time.time() + timeout_sec
    expected = n_services * 2  # v1+v2
    while time.time() < deadline:
        out = kubectl(
            [
                "get",
                "deploy",
                "-n",
                ns,
                "-l",
                "meshscope/exp=real-traffic",
                "-o",
                "jsonpath={range .items[*]}{.metadata.name}{' '}{.status.readyReplicas}{'\\n'}{end}",
            ]
        )
        ready = 0
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) >= 1:
                ready += 1
        print("  ready deployments: {0}/{1}".format(ready, expected))
        if ready >= expected:
            print("[deploy] all deployments ready")
            return
        time.sleep(10)
    raise RuntimeError("timeout waiting for deployments in ns={0}".format(ns))


def main() -> int:
    parser = argparse.ArgumentParser(description="部署 meshscope 实验服务")
    parser.add_argument("--namespace", default="meshscope-exp")
    parser.add_argument("--services", type=int, default=10)
    parser.add_argument("--wait", action="store_true", default=True)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    out = Path(args.output) if args.output else None
    deploy(args.namespace, args.services, out)
    if not args.no_wait:
        wait_ready(args.namespace, args.services)
    return 0


if __name__ == "__main__":
    sys.exit(main())
