#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据平面配置导出模块
从 Envoy Sidecar 导出 routes.json、clusters.json、listeners.json

支持三种获取方式:
1. istioctl: 使用 istioctl proxy-config 分别获取（推荐，自动选择代理）
2. kubectl-exec: 在 Pod 内执行 curl 获取 config_dump，再解析
3. from-yaml: 从已有 proxy_config_all.yaml 解析（istioctl/kubectl 不可用时）

用法示例:
  # 使用 kubectl exec（需指定 Pod）
  python export_data_plane_config.py --pod productpage-v1-xxx -n default --method kubectl-exec

  # 使用 istioctl（自动选择第一个可用代理）
  python export_data_plane_config.py --method istioctl

  # 指定输出目录
  python export_data_plane_config.py --output-dir ./my_sidecar_config --method istioctl
"""
import os
import sys
import json
import argparse
import subprocess
import logging
import yaml
from typing import Optional, Dict, Any

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _run_cmd(cmd: str, timeout: int = 30) -> Optional[str]:
    """执行 shell 命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning(f"命令失败: {cmd}\n{result.stderr}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"命令超时: {cmd}")
        return None
    except Exception as e:
        logger.error(f"执行命令异常: {e}")
        return None


def parse_proxy_config_yaml(yaml_path: str) -> Optional[Dict[str, Any]]:
    """
    从已有的 proxy_config_all.yaml 解析出 routes、clusters、listeners
    适用于 istioctl/kubectl 不可用，但已有 config_dump 导出的情况
    """
    if not os.path.exists(yaml_path):
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config_dump = yaml.safe_load(f)
        return parse_config_dump(config_dump) if config_dump else None
    except Exception as e:
        logger.warning(f"解析 proxy_config_all.yaml 失败: {e}")
        return None


def get_config_dump_via_kubectl(pod: str, namespace: str = "default") -> Optional[Dict]:
    """
    通过 kubectl exec 在 Pod 内执行 curl 获取 Envoy config_dump
    """
    cmd = (
        f"kubectl exec {pod} -n {namespace} -c istio-proxy -- "
        "curl -s http://127.0.0.1:15000/config_dump"
    )
    output = _run_cmd(cmd)
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        logger.error(f"解析 config_dump JSON 失败: {e}")
        return None


def parse_config_dump(config_dump: Dict) -> Dict[str, Any]:
    """
    从 config_dump 解析出 routes、clusters、listeners
    格式与 main_parser / 各 parser 期望的格式兼容
    """
    result = {"routes": [], "clusters": [], "listeners": []}

    def _snake_to_camel(k: str) -> str:
        m = {
            "virtual_hosts": "virtualHosts",
            "weighted_clusters": "weightedClusters",
            "route_config": "routeConfig",
            "dynamic_route_configs": "dynamicRouteConfigs",
            "dynamic_active_clusters": "dynamicActiveClusters",
            "dynamic_listeners": "dynamicListeners",
        }
        return m.get(k, k)

    def _ensure_camel(obj):
        if isinstance(obj, dict):
            return {_snake_to_camel(k): _ensure_camel(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_ensure_camel(x) for x in obj]
        return obj

    configs = config_dump.get("configs", config_dump.get("configDump", {}).get("configs", []))
    if not isinstance(configs, list):
        configs = [config_dump] if config_dump else []

    for cfg in configs:
        ctype = str(cfg.get("@type", ""))
        if "RoutesConfigDump" in ctype:
            for drc in cfg.get("dynamicRouteConfigs", cfg.get("dynamic_route_configs", [])):
                rc = drc.get("routeConfig", drc.get("route_config", {}))
                if rc.get("virtualHosts") or rc.get("virtual_hosts"):
                    result["routes"].append(_ensure_camel(rc))
        elif "ClustersConfigDump" in ctype:
            result["clusters"] = cfg.get("dynamicActiveClusters", cfg.get("dynamic_active_clusters", []))
        elif "ListenersConfigDump" in ctype:
            result["listeners"] = cfg.get("dynamicListeners", cfg.get("dynamic_listeners", []))

    return result


def get_proxy_list() -> list:
    """获取可用代理列表 (pod.namespace)"""
    output = _run_cmd("istioctl proxy-status")
    if not output:
        return []
    lines = output.strip().split("\n")
    if len(lines) <= 1:
        return []
    proxies = []
    for line in lines[1:]:
        if line.strip():
            parts = line.split()
            if parts:
                proxies.append(parts[0])
    return proxies


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


def export_data_plane_config(
    output_dir: str,
    method: str = "istioctl",
    pod: Optional[str] = None,
    namespace: str = "default",
    yaml_path: Optional[str] = None,
) -> bool:
    """
    导出数据平面配置到 output_dir

    Args:
        output_dir: 输出目录
        method: 获取方式 ("kubectl-exec" 或 "istioctl")
        pod: Pod 名称（method=kubectl-exec 时必填）
        namespace: 命名空间

    Returns:
        是否成功
    """
    os.makedirs(output_dir, exist_ok=True)
    routes_data = None
    clusters_data = None
    listeners_data = None

    if method == "from-yaml":
        # 从已有 proxy_config_all.yaml 解析（istioctl/kubectl 不可用时）
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
            logger.error("使用 kubectl-exec 方式时需指定 --pod")
            return False
        config_dump = get_config_dump_via_kubectl(pod, namespace)
        if not config_dump:
            logger.error("无法获取 config_dump")
            return False
        parsed = parse_config_dump(config_dump)
        routes_data = parsed["routes"]
        clusters_data = parsed["clusters"]
        listeners_data = parsed["listeners"]
        logger.info("已从 config_dump 解析 routes/clusters/listeners")

    elif method == "istioctl":
        proxies = get_proxy_list()
        if not proxies:
            logger.error("未找到可用代理，请确保 istioctl 可访问集群")
            return False
        proxy_id = proxies[0]
        if namespace != "all":
            for p in proxies:
                if p.endswith(f".{namespace}"):
                    proxy_id = p
                    break
        logger.info(f"使用代理: {proxy_id}")

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
        description="从 Envoy Sidecar 导出 routes/clusters/listeners 配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 istioctl（推荐，自动选择代理）
  python export_data_plane_config.py --method istioctl

  # 使用 kubectl exec 指定 Pod
  python export_data_plane_config.py --pod productpage-v1-xxx -n default --method kubectl-exec

  # 指定输出目录
  python export_data_plane_config.py -o ./my_config --method istioctl
        """,
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="istio_config_parser/istio_monitor/istio_sidecar_config",
        help="输出目录",
    )
    parser.add_argument(
        "--method",
        choices=["istioctl", "kubectl-exec", "from-yaml"],
        default="istioctl",
        help="获取方式: istioctl, kubectl-exec, 或 from-yaml(从 proxy_config_all.yaml 解析)",
    )
    parser.add_argument(
        "--yaml-path",
        help="proxy_config_all.yaml 路径（method=from-yaml 时可选，默认 output-dir/proxy_config_all.yaml）",
    )
    parser.add_argument(
        "--pod", "-p",
        help="Pod 名称（method=kubectl-exec 时必填）",
    )
    parser.add_argument(
        "-n", "--namespace",
        default="default",
        help="命名空间",
    )
    args = parser.parse_args()

    # 相对路径转绝对路径（相对于项目根目录）
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        # 脚本在 istio_config_parser/istio_monitor/，项目根为上级的上级
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        output_dir = os.path.normpath(os.path.join(project_root, output_dir))

    print("\n" + "=" * 60)
    print("数据平面配置导出")
    print("=" * 60)
    print(f"方式: {args.method}")
    print(f"输出: {output_dir}")
    if args.pod:
        print(f"Pod:  {args.pod} ({args.namespace})")
    print("=" * 60 + "\n")

    ok = export_data_plane_config(
        output_dir=output_dir,
        method=args.method,
        pod=args.pod,
        namespace=args.namespace,
        yaml_path=args.yaml_path,
    )
    # 若 istioctl 失败且存在 proxy_config_all.yaml，自动尝试 from-yaml
    if not ok and args.method == "istioctl":
        yaml_path = os.path.join(output_dir, "proxy_config_all.yaml")
        if os.path.exists(yaml_path):
            logger.info("istioctl 不可用，尝试从 proxy_config_all.yaml 解析...")
            ok = export_data_plane_config(
                output_dir=output_dir,
                method="from-yaml",
                yaml_path=yaml_path,
            )
    if ok:
        print("\n导出完成，可用于 main_parser 一致性检验。")
        return 0
    print("\n导出失败。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
