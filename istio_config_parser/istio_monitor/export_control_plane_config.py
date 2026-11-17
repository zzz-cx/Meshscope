#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
控制平面配置导出模块
从 Kubernetes 集群导出 Istio 控制平面配置（VirtualService、DestinationRule、Gateway 等）

支持：
- 本地 kubeconfig
- 远程集群（k8s_host + k8s_token）

用法示例:
  # 使用默认 kubeconfig
  python export_control_plane_config.py

  # 指定远程集群
  python export_control_plane_config.py --k8s-host 192.168.1.100 --k8s-token <token>

  # 指定输出目录
  python export_control_plane_config.py -o ./istio_control_config
"""
import os
import sys
import json
import shutil
import argparse
import datetime
import logging
import hashlib
import subprocess
from typing import Dict, Any, Optional, List

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 修复 Windows 控制台中文乱码
try:
    from istio_config_parser.utils.console_encoding import fix_console_encoding
    fix_console_encoding()
except ImportError:
    pass

try:
    from kubernetes import client, config
except ImportError:
    client = None
    config = None

import yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Istio 自定义资源列表
ISTIO_RESOURCES = [
    ("networking.istio.io", "v1alpha3", "virtualservices"),
    ("networking.istio.io", "v1alpha3", "destinationrules"),
    ("networking.istio.io", "v1alpha3", "gateways"),
    ("security.istio.io", "v1beta1", "authorizationpolicies"),
    ("networking.istio.io", "v1alpha3", "serviceentries"),
    ("networking.istio.io", "v1alpha3", "sidecars"),
    ("networking.istio.io", "v1alpha3", "workloadentries"),
    ("networking.istio.io", "v1alpha3", "workloadgroups"),
    ("networking.istio.io", "v1alpha3", "envoyfilters"),
]


def _calculate_hash(data: Any) -> str:
    """计算数据哈希"""
    if isinstance(data, (dict, list)):
        data_str = json.dumps(data, sort_keys=True, default=str)
    else:
        data_str = str(data)
    return hashlib.md5(data_str.encode('utf-8')).hexdigest()


def _reset_directory(path: str) -> None:
    """清空并重建目录"""
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


_KUBECTL_KINDS = [
    ("virtualservices", "virtualservice"),
    ("destinationrules", "destinationrule"),
    ("gateways", "gateway"),
    ("authorizationpolicies", "authorizationpolicy"),
    ("serviceentries", "serviceentry"),
    ("sidecars", "sidecar"),
    ("workloadentries", "workloadentry"),
    ("workloadgroups", "workloadgroup"),
    ("envoyfilters", "envoyfilter"),
    ("services", "svc"),
]


def _kubectl_json(args: List[str], timeout: int = 30) -> Optional[Dict[str, Any]]:
    try:
        result = subprocess.run(
            ["kubectl", *args, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip().splitlines()[:1]
            logger.warning("kubectl %s 失败: %s", " ".join(args), err[0] if err else "unknown")
            return None
        return json.loads(result.stdout)
    except FileNotFoundError:
        logger.error("未找到 kubectl，无法导出控制面")
        return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.error("kubectl 导出失败: %s", exc)
        return None


def _live_namespaces() -> set:
    """kubectl get ns 能列到的命名空间。已删 ns 里残留的对象不算现网。"""
    data = _kubectl_json(["get", "ns"])
    names = set()
    for item in (data or {}).get("items") or []:
        name = (item.get("metadata") or {}).get("name")
        if name:
            names.add(name)
    return names


_SKIP_GRAPH_SERVICES = {("default", "kubernetes")}


def live_workload_index() -> Dict[str, Any]:
    """现网工作负载：仅统计 kubectl get ns 仍存在的命名空间里的 Service / Pod。

    已删除 Namespace 上残留的对象、以及 default/kubernetes 都不进入图。
    """
    live_ns = _live_namespaces()
    services = set()
    svc_data = _kubectl_json(["get", "svc", "-A"])
    svc_ok = svc_data is not None
    for item in ((svc_data or {}).get("items") or []):
        meta = item.get("metadata") or {}
        ns = meta.get("namespace") or "default"
        name = meta.get("name")
        if not name or ns not in live_ns:
            continue
        if (ns, name) in _SKIP_GRAPH_SERVICES:
            continue
        services.add((ns, name))

    pods_by_service: Dict[tuple, List[Dict[str, Any]]] = {}
    pod_data = _kubectl_json(["get", "pods", "-A"]) or {}
    for item in (pod_data.get("items") or []):
        meta = item.get("metadata") or {}
        ns = meta.get("namespace") or "default"
        if ns not in live_ns:
            continue
        if meta.get("deletionTimestamp"):
            continue
        phase = ((item.get("status") or {}).get("phase") or "")
        if phase in ("Succeeded", "Failed"):
            continue
        labels = meta.get("labels") or {}
        app = labels.get("app") or labels.get("k8s-app") or ""
        if not app or (ns, app) not in services:
            continue
        pods_by_service.setdefault((ns, app), []).append({
            "name": meta.get("name") or "",
            "version": labels.get("version") or "",
            "app": app,
        })

    return {
        "ok": bool(live_ns) and svc_ok,
        "namespaces": live_ns,
        "services": services,
        "pods_by_service": pods_by_service,
    }


def _write_items_by_namespace(
    output_dir: str,
    dirname: str,
    items: List[Dict[str, Any]],
    live_ns: Optional[set] = None,
) -> int:
    resource_dir = os.path.join(output_dir, dirname)
    _reset_directory(resource_dir)
    skipped = 0
    for item in items:
        metadata = item.get("metadata") or {}
        name = metadata.get("name") or "unknown"
        namespace = metadata.get("namespace") or "default"
        if live_ns is not None and namespace not in live_ns:
            skipped += 1
            continue
        ns_dir = os.path.join(resource_dir, namespace)
        os.makedirs(ns_dir, exist_ok=True)
        file_path = os.path.join(ns_dir, f"{name}.yaml")
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(item, f, default_flow_style=False, allow_unicode=True)
        logger.info("已保存: %s", file_path)
    if skipped:
        logger.warning(
            "跳过 %s 项不在现存命名空间中的 %s（Namespace 对象已删除，kubectl get ns 看不到）",
            skipped,
            dirname,
        )
    return skipped


def _export_control_plane_via_kubectl(output_dir: str) -> Dict[str, Any]:
    """本机有 kubectl 时导出控制面，不依赖 python kubernetes 库。"""
    changes: Dict[str, Any] = {}
    os.makedirs(output_dir, exist_ok=True)
    logger.info("使用 kubectl 从集群导出控制面配置")
    live_ns = _live_namespaces()
    if live_ns:
        logger.info("现存命名空间 %s 个: %s", len(live_ns), ", ".join(sorted(live_ns)))
    for dirname, kind in _KUBECTL_KINDS:
        data = _kubectl_json(["get", kind, "-A"])
        if not data:
            continue
        items = data.get("items") or []
        if live_ns:
            items = [
                it for it in items
                if ((it.get("metadata") or {}).get("namespace") or "default") in live_ns
            ]
            data = dict(data)
            data["items"] = items
        _write_items_by_namespace(output_dir, dirname, items)
        list_file = os.path.join(output_dir, dirname, "list.json")
        os.makedirs(os.path.dirname(list_file), exist_ok=True)
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        changes[f"control_plane_{dirname}"] = data
        logger.info("kubectl 导出 %s: %s 项", dirname, len(items))
    return changes


def _init_k8s_client(
    k8s_host: Optional[str] = None,
    k8s_token: Optional[str] = None,
) -> tuple:
    """
    初始化 Kubernetes 客户端

    Returns:
        (custom_objects_api, core_v1_api, configuration or None)
    """
    if not client or not config:
        raise ImportError("请安装 kubernetes 库: pip install kubernetes")

    configuration = None
    try:
        if k8s_host:
            configuration = client.Configuration()
            configuration.host = f"https://{k8s_host}:6443"
            configuration.verify_ssl = False
            configuration.debug = False

            auth_configured = False
            if k8s_token:
                token = k8s_token.strip()
                if token.startswith("Bearer "):
                    token = token[7:]
                configuration.api_key = {"authorization": token}
                configuration.api_key_prefix = {"authorization": "Bearer"}
                auth_configured = True
            else:
                sa_path = '/var/run/secrets/kubernetes.io/serviceaccount/token'
                if os.path.exists(sa_path):
                    with open(sa_path, 'r') as f:
                        token = f.read().strip()
                        configuration.api_key = {"authorization": token}
                        configuration.api_key_prefix = {"authorization": "Bearer"}
                        auth_configured = True

            if not auth_configured:
                try:
                    config.load_kube_config()
                    cfg = client.Configuration.get_default_copy()
                    configuration.api_key = cfg.api_key
                    configuration.api_key_prefix = cfg.api_key_prefix
                    configuration.ssl_ca_cert = cfg.ssl_ca_cert
                    configuration.cert_file = cfg.cert_file
                    configuration.key_file = cfg.key_file
                    auth_configured = True
                except Exception as e:
                    logger.warning(f"无法从 kubeconfig 加载: {e}")

            if not auth_configured:
                raise ValueError("未配置 Kubernetes 认证，请提供 --k8s-token 或配置 KUBECONFIG")

            client.Configuration.set_default(configuration)
        else:
            config.load_kube_config()

        api_client = client.ApiClient(configuration) if configuration else client.ApiClient()
        custom_api = client.CustomObjectsApi(api_client)
        core_v1 = client.CoreV1Api(api_client)
        return custom_api, core_v1, configuration
    except Exception as e:
        logger.error(f"初始化 Kubernetes 客户端失败: {e}")
        raise


def export_control_plane_config(
    output_dir: str,
    k8s_host: Optional[str] = None,
    k8s_token: Optional[str] = None,
    k8s_client=None,
    core_v1_api=None,
) -> Dict[str, Any]:
    """
    导出控制平面配置到指定目录

    Args:
        output_dir: 输出目录（如 istio_control_config）
        k8s_host: 远程 K8s API 地址（可选）
        k8s_token: 认证 token（可选）
        k8s_client: 已初始化的 CustomObjectsApi（可选，与 core_v1_api 一起传入可复用）
        core_v1_api: 已初始化的 CoreV1Api（可选）

    Returns:
        变更的配置项 {config_key: data}
    """
    changes = {}
    os.makedirs(output_dir, exist_ok=True)

    if client is None:
        return _export_control_plane_via_kubectl(output_dir)

    if k8s_client is None or core_v1_api is None:
        try:
            k8s_client, core_v1_api, _ = _init_k8s_client(k8s_host, k8s_token)
        except Exception as exc:
            logger.warning("K8s Python 客户端不可用（%s），改用 kubectl 导出控制面", exc)
            return _export_control_plane_via_kubectl(output_dir)

    # 1. 导出 Istio 自定义资源
    for group, version, plural in ISTIO_RESOURCES:
        try:
            response = k8s_client.list_cluster_custom_object(
                group=group, version=version, plural=plural
            )
            resource_dir = os.path.join(output_dir, plural)
            _reset_directory(resource_dir)

            for item in response.get('items', []):
                metadata = item.get('metadata', {})
                name = metadata.get('name', 'unknown')
                namespace = metadata.get('namespace', 'default')
                ns_dir = os.path.join(resource_dir, namespace)
                os.makedirs(ns_dir, exist_ok=True)
                file_path = os.path.join(ns_dir, f"{name}.yaml")
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(item, f, default_flow_style=False, allow_unicode=True)
                logger.info(f"已保存: {file_path}")

            list_file = os.path.join(resource_dir, "list.json")
            with open(list_file, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)

            changes[f"control_plane_{plural}"] = response
        except Exception as e:
            logger.error(f"获取 {plural} 失败: {e}")

    # 2. 导出 Kubernetes Service
    try:
        services = core_v1_api.list_service_for_all_namespaces()
        services_dir = os.path.join(output_dir, "services")
        _reset_directory(services_dir)

        for service in services.items:
            namespace = service.metadata.namespace
            name = service.metadata.name
            ns_dir = os.path.join(services_dir, namespace)
            os.makedirs(ns_dir, exist_ok=True)

            service_dict = {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": service.metadata.name,
                    "namespace": service.metadata.namespace,
                    "labels": dict(service.metadata.labels) if service.metadata.labels else {},
                    "annotations": dict(service.metadata.annotations) if service.metadata.annotations else {},
                },
                "spec": {
                    "ports": [
                        {
                            "name": port.name,
                            "port": port.port,
                            "protocol": port.protocol,
                            "targetPort": port.target_port,
                        }
                        for port in (service.spec.ports or [])
                    ],
                    "selector": dict(service.spec.selector) if service.spec.selector else {},
                    "type": service.spec.type,
                    "clusterIP": service.spec.cluster_ip,
                    "sessionAffinity": service.spec.session_affinity,
                },
            }
            file_path = os.path.join(ns_dir, f"{name}.yaml")
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(service_dict, f, default_flow_style=False, allow_unicode=True)
            logger.info(f"已保存: {file_path}")

        def _json_handler(obj):
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            return str(obj)

        list_file = os.path.join(services_dir, "list.json")
        with open(list_file, 'w', encoding='utf-8') as f:
            json.dump(
                [s.to_dict() for s in services.items],
                f, ensure_ascii=False, indent=2, default=_json_handler
            )
        changes["core_services"] = services
    except Exception as e:
        logger.error(f"获取 Service 失败: {e}")

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="从 Kubernetes 导出 Istio 控制平面配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python export_control_plane_config.py
  python export_control_plane_config.py --k8s-host 192.168.1.100 --k8s-token <token>
  python export_control_plane_config.py -o ./my_control_config
        """,
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="输出目录",
    )
    parser.add_argument("--k8s-host", help="Kubernetes API 地址（远程集群）")
    parser.add_argument("--k8s-token", help="认证 token")
    args = parser.parse_args()
    try:
        from consistency_checker.config import fill_args_from_config
        fill_args_from_config(args, {
            "output_dir": "control_plane_config_dir",
            "k8s_host": "k8s_host",
            "k8s_token": "k8s_token",
        })
    except Exception:
        pass
    if not args.output_dir:
        args.output_dir = "istio_config_parser/istio_monitor/istio_control_config"

    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        output_dir = os.path.normpath(os.path.join(project_root, output_dir))

    print("\n" + "=" * 60)
    print("控制平面配置导出")
    print("=" * 60)
    print(f"输出: {output_dir}")
    print("=" * 60 + "\n")

    try:
        export_control_plane_config(
            output_dir=output_dir,
            k8s_host=args.k8s_host,
            k8s_token=args.k8s_token,
        )
        print("\n导出完成。")
        return 0
    except Exception as e:
        logger.error(f"导出失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
