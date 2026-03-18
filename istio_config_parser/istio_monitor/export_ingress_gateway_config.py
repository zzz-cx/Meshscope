#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Ingress Gateway 配置采集模块

从 istio-ingressgateway 的 Envoy 导出 routes.json、clusters.json、listeners.json，
用于对 Gateway 绑定的 VirtualService（如 frontend-ingress、bookinfo）做一致性校验。

与 export_data_plane_config 的区别：
- 本模块采集的是 ingress gateway 的配置（入口流量）
- export_data_plane_config 采集的是 mesh sidecar 的配置（出站流量）
- Gateway 绑定的 VS 配置只存在于 ingress gateway，不在 sidecar 中

支持三种获取方式:
1. kubectl-exec: 在 istio-ingressgateway Pod 内执行 curl 获取 config_dump（推荐）
2. istioctl: 使用 istioctl proxy-config 获取（自动选择 ingress gateway）
3. from-yaml: 从已有 proxy_config_all.yaml 解析（kubectl/istioctl 不可用时）

用法示例:
  # 使用 kubectl exec（自动查找 ingress gateway pod）
  python export_ingress_gateway_config.py --method kubectl-exec

  # 指定 ingress gateway 的 deployment 名称
  python export_ingress_gateway_config.py --deployment istio-ingressgateway -n istio-system

  # 使用 istioctl
  python export_ingress_gateway_config.py --method istioctl

  # 指定输出目录（供 main_parser 的 --ingress-plane-dir 使用）
  python export_ingress_gateway_config.py -o istio_config_parser/istio_monitor/istio_ingress_config
"""
import os
import sys
import json
import argparse
import subprocess
import logging
import yaml
from typing import Optional, Dict, Any, List

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# 修复 Windows 控制台中文乱码
try:
    from istio_config_parser.utils.console_encoding import fix_console_encoding
    fix_console_encoding()
except ImportError:
    pass

try:
    from .export_data_plane_config import parse_config_dump, get_config_dump_via_kubectl
except ImportError:
    from export_data_plane_config import parse_config_dump, get_config_dump_via_kubectl

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INGRESS_NAMESPACE = "istio-system"
DEFAULT_INGRESS_DEPLOYMENT = "istio-ingressgateway"
DEFAULT_OUTPUT_DIR = "istio_config_parser/istio_monitor/istio_ingress_config"


def _run_cmd(cmd: str, timeout: int = 60) -> Optional[str]:
    """执行 shell 命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning(f"命令失败 (code={result.returncode}): {cmd}\n{result.stderr}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"命令超时: {cmd}")
        return None
    except Exception as e:
        logger.error(f"执行命令异常: {e}")
        return None


def get_ingress_gateway_pod(
    deployment: str = DEFAULT_INGRESS_DEPLOYMENT,
    namespace: str = DEFAULT_INGRESS_NAMESPACE
) -> Optional[str]:
    """
    获取 istio-ingressgateway 的 Pod 名称
    
    Returns:
        Pod 名称，如 "istio-ingressgateway-7b5d6c9d8f-xxxxx"，失败返回 None
    """
    # 兼容 Windows：不使用 2>/dev/null（PowerShell 无 /dev/null）
    cmd = (
        f"kubectl get pods -n {namespace} -l app={deployment} "
        "-o jsonpath='{.items[0].metadata.name}'"
    )
    pod = _run_cmd(cmd)
    if not pod:
        # 尝试 app.kubernetes.io/name 标签
        cmd = (
            f"kubectl get pods -n {namespace} "
            f"-l app.kubernetes.io/name=istio-ingressgateway "
            "-o jsonpath='{.items[0].metadata.name}'"
        )
        pod = _run_cmd(cmd)
    if not pod:
        # 尝试通过 deployment 名称查找
        cmd = (
            f"kubectl get pods -n {namespace} "
            f"--selector=istio=ingressgateway "
            "-o jsonpath='{.items[0].metadata.name}'"
        )
        pod = _run_cmd(cmd)
    # 去除 jsonpath 可能返回的引号（Windows/PowerShell 兼容）
    if pod:
        pod = pod.strip().strip("'\"")
    return pod


def get_ingress_proxy_via_istioctl(
    namespace: str = DEFAULT_INGRESS_NAMESPACE
) -> Optional[str]:
    """
    通过 istioctl proxy-status 获取 ingress gateway 的 proxy ID (pod.namespace)
    """
    output = _run_cmd("istioctl proxy-status")
    if not output:
        return None
    lines = output.strip().split("\n")
    if len(lines) <= 1:
        return None
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if not parts:
            continue
        proxy_id = parts[0]  # pod.namespace
        if proxy_id.endswith(f".{namespace}") and "ingressgateway" in proxy_id.lower():
            return proxy_id
    return None


def get_config_via_istioctl(proxy_id: str, config_type: str) -> Optional[Any]:
    """通过 istioctl proxy-config 获取指定类型配置"""
    output = _run_cmd(f"istioctl proxy-config {config_type} {proxy_id} -o json")
    if not output:
        return None
    try:
        data = json.loads(output)
        if config_type == "clusters":
            if isinstance(data, list):
                return data
            return data.get("dynamicActiveClusters", data.get("dynamic_active_clusters", data))
        if config_type == "listeners":
            if isinstance(data, list):
                return data
            return data.get("dynamicListeners", data.get("dynamic_listeners", data))
        if config_type == "routes":
            if isinstance(data, list):
                return data
            return data.get("dynamicRouteConfigs", data.get("dynamic_route_configs", data))
        return data
    except json.JSONDecodeError:
        return None


def parse_proxy_config_yaml(yaml_path: str) -> Optional[Dict[str, Any]]:
    """从已有的 proxy_config_all.yaml 解析出 routes、clusters、listeners"""
    if not os.path.exists(yaml_path):
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config_dump = yaml.safe_load(f)
        return parse_config_dump(config_dump) if config_dump else None
    except Exception as e:
        logger.warning(f"解析 {yaml_path} 失败: {e}")
        return None


def export_ingress_gateway_config(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    method: str = "kubectl-exec",
    deployment: str = DEFAULT_INGRESS_DEPLOYMENT,
    namespace: str = DEFAULT_INGRESS_NAMESPACE,
    pod: Optional[str] = None,
    yaml_path: Optional[str] = None,
) -> bool:
    """
    导出 Ingress Gateway 数据平面配置到 output_dir

    Args:
        output_dir: 输出目录，将生成 routes.json、clusters.json、listeners.json
        method: 获取方式 ("kubectl-exec" | "istioctl" | "from-yaml")
        deployment: Ingress Gateway Deployment 名称
        namespace: Ingress Gateway 所在命名空间
        pod: Pod 名称（method=kubectl-exec 时可指定，否则自动查找）
        yaml_path: proxy_config_all.yaml 路径（method=from-yaml 时）

    Returns:
        是否成功
    """
    os.makedirs(output_dir, exist_ok=True)
    routes_data = None
    clusters_data = None
    listeners_data = None

    if method == "from-yaml":
        path = yaml_path or os.path.join(output_dir, "proxy_config_all.yaml")
        parsed = parse_proxy_config_yaml(path)
        if not parsed:
            logger.error(f"无法解析 {path}，请确保文件存在且格式正确")
            return False
        routes_data = parsed["routes"]
        clusters_data = parsed["clusters"]
        listeners_data = parsed["listeners"]
        logger.info(f"已从 {path} 解析 routes/clusters/listeners")

    elif method == "kubectl-exec":
        if not pod:
            pod = get_ingress_gateway_pod(deployment, namespace)
        if not pod:
            logger.error(
                f"未找到 Ingress Gateway Pod。请检查:\n"
                f"  - 命名空间 {namespace} 中是否存在 {deployment}\n"
                f"  - kubectl get pods -n {namespace} -l app={deployment}"
            )
            return False
        logger.info(f"使用 Ingress Gateway Pod: {pod} ({namespace})")
        config_dump = get_config_dump_via_kubectl(pod, namespace)
        if not config_dump:
            logger.error("无法获取 config_dump，请确保 kubectl 可访问集群")
            return False
        parsed = parse_config_dump(config_dump)
        routes_data = parsed["routes"]
        clusters_data = parsed["clusters"]
        listeners_data = parsed["listeners"]
        # 同时保存完整 config_dump 供调试
        config_dump_path = os.path.join(output_dir, "proxy_config_all.yaml")
        with open(config_dump_path, "w", encoding="utf-8") as f:
            yaml.dump(config_dump, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"已保存完整 config_dump: {config_dump_path}")

    elif method == "istioctl":
        proxy_id = get_ingress_proxy_via_istioctl(namespace)
        if not proxy_id:
            logger.error(
                "未找到 Ingress Gateway 代理。请确保:\n"
                "  - istioctl 可访问集群\n"
                "  - istioctl proxy-status 中能看到 istio-ingressgateway"
            )
            return False
        logger.info(f"使用 Ingress Gateway 代理: {proxy_id}")
        routes_data = get_config_via_istioctl(proxy_id, "routes")
        clusters_data = get_config_via_istioctl(proxy_id, "clusters")
        listeners_data = get_config_via_istioctl(proxy_id, "listeners")

    else:
        logger.error(f"不支持的 method: {method}")
        return False

    saved = 0
    if routes_data is not None:
        path = os.path.join(output_dir, "routes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(routes_data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存: {path}")
        saved += 1

    if clusters_data is not None:
        path = os.path.join(output_dir, "clusters.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clusters_data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存: {path}")
        saved += 1

    if listeners_data is not None:
        path = os.path.join(output_dir, "listeners.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(listeners_data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存: {path}")
        saved += 1

    return saved > 0


def main():
    parser = argparse.ArgumentParser(
        description="从 Istio Ingress Gateway 导出 routes/clusters/listeners 配置，用于 Gateway 绑定项一致性校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 kubectl exec（推荐，自动查找 ingress gateway pod）
  python export_ingress_gateway_config.py --method kubectl-exec

  # 使用 istioctl
  python export_ingress_gateway_config.py --method istioctl

  # 指定 deployment 和命名空间
  python export_ingress_gateway_config.py --deployment istio-ingressgateway -n istio-system

  # 指定输出目录（供 main_parser --ingress-plane-dir 使用）
  python export_ingress_gateway_config.py -o istio_config_parser/istio_monitor/istio_ingress_config

采集完成后，使用 main_parser 时指定 --ingress-plane-dir 可对 frontend-ingress、bookinfo 等 Gateway 绑定配置做一致性校验。
        """,
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--method",
        choices=["kubectl-exec", "istioctl", "from-yaml"],
        default="kubectl-exec",
        help="获取方式: kubectl-exec, istioctl, 或 from-yaml",
    )
    parser.add_argument(
        "--deployment", "-d",
        default=DEFAULT_INGRESS_DEPLOYMENT,
        help=f"Ingress Gateway Deployment 名称（默认: {DEFAULT_INGRESS_DEPLOYMENT}）",
    )
    parser.add_argument(
        "-n", "--namespace",
        default=DEFAULT_INGRESS_NAMESPACE,
        help=f"Ingress Gateway 命名空间（默认: {DEFAULT_INGRESS_NAMESPACE}）",
    )
    parser.add_argument(
        "--pod", "-p",
        help="Pod 名称（method=kubectl-exec 时可指定，否则自动查找）",
    )
    parser.add_argument(
        "--yaml-path",
        help="proxy_config_all.yaml 路径（method=from-yaml 时）",
    )
    args = parser.parse_args()

    # 相对路径转绝对路径
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        output_dir = os.path.normpath(os.path.join(project_root, output_dir))

    print("\n" + "=" * 60)
    print("Ingress Gateway 配置采集")
    print("=" * 60)
    print(f"方式:       {args.method}")
    print(f"输出目录:   {output_dir}")
    print(f"Deployment: {args.deployment} ({args.namespace})")
    if args.pod:
        print(f"Pod:        {args.pod}")
    print("=" * 60 + "\n")

    ok = export_ingress_gateway_config(
        output_dir=output_dir,
        method=args.method,
        deployment=args.deployment,
        namespace=args.namespace,
        pod=args.pod,
        yaml_path=args.yaml_path,
    )

    if not ok and args.method == "istioctl":
        yaml_path = os.path.join(output_dir, "proxy_config_all.yaml")
        if os.path.exists(yaml_path):
            logger.info("istioctl 不可用，尝试从 proxy_config_all.yaml 解析...")
            ok = export_ingress_gateway_config(
                output_dir=output_dir,
                method="from-yaml",
                yaml_path=yaml_path,
            )

    if ok:
        print("\n采集完成。使用 main_parser 时指定 --ingress-plane-dir 可对 Gateway 绑定配置做一致性校验。")
        return 0
    print("\n采集失败。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
