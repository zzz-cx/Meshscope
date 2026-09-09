import os
import sys
import logging
import json
from typing import Dict, Any, List, Optional, Tuple

# 添加项目根目录到 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 统一解析器和模型（推荐使用）
from istio_config_parser.parsers.unified_parser import UnifiedParser
from istio_config_parser.models.ir_models import SystemIR
from istio_config_parser.utils.file_utils import load_yaml_file, load_json_file

# Legacy 格式数据结构与适配器
from istio_config_parser.models.data_structures import (
    ControlPlaneResult,
    DataPlaneResult,
)
from istio_config_parser.parsers.service_parser import parse_services
from istio_config_parser.utils.ir_to_legacy import system_ir_to_legacy

logger = logging.getLogger(__name__)

# 包目录与项目根，用于路径解析
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PKG_DIR)


def _resolve_config_dir(path: str) -> str:
    """
    解析配置目录路径。
    - 绝对路径：原样返回
    - 以 istio_config_parser 开头：相对于项目根（用户从项目根传入）
    - 否则：相对于包目录（默认 istio_monitor/...）
    """
    if os.path.isabs(path):
        return path
    if path.startswith('istio_config_parser' + os.sep) or path.startswith('istio_config_parser/'):
        return os.path.join(_PROJECT_ROOT, path)
    return os.path.join(_PKG_DIR, path)


def _get_tau() -> float:
    try:
        from consistency_checker.config import get_config
        cfg = get_config()
        tau = getattr(cfg, "alignment_tau", None)
        if tau is None:
            tau = cfg.traffic_split_tolerance
        return float(tau)
    except Exception:
        return 0.1


def _get_timeout_abs() -> float:
    try:
        from consistency_checker.config import get_config
        return max(0.0, float(get_config().timeout_tolerance_seconds))
    except Exception:
        return 0.5


def aligned_semantic_path(output_dir: Optional[str] = None) -> str:
    if output_dir:
        base = output_dir if os.path.isabs(output_dir) else os.path.join(_PROJECT_ROOT, output_dir)
        return os.path.join(base, "aligned_semantic.json")
    try:
        from consistency_checker.config import get_config
        return os.path.join(get_config().consistency_output_dir, "aligned_semantic.json")
    except Exception:
        return os.path.join(_PROJECT_ROOT, "results", "consistency", "aligned_semantic.json")


class AlignedModelMissingError(FileNotFoundError):
    """动态期望依赖静态对齐产物，尚未生成 aligned_semantic.json。"""


def load_aligned_semantic(path: Optional[str] = None) -> Dict[str, Any]:
    target = path or aligned_semantic_path()
    if not os.path.isfile(target):
        raise AlignedModelMissingError(
            f"未找到对齐后的语义模型: {target}。请先执行静态分析"
            "（python -m configpilot static 或 POST /api/static/analyze）。"
        )
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_aligned_semantic(artifact: Dict[str, Any], path: Optional[str] = None) -> str:
    target = path or aligned_semantic_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"已写入对齐语义模型: {target}")
    return target


def _load_control_plane_configs(cp_dir: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    return {
        "services": _load_config_files(cp_dir, "services", namespace),
        "virtual_services": _load_config_files(cp_dir, "virtualservices", namespace),
        "destination_rules": _load_config_files(cp_dir, "destinationrules", namespace),
        "envoy_filters": _load_config_files(cp_dir, "envoyfilters", namespace),
        "gateways": _load_config_files(cp_dir, "gateways", namespace),
    }


_DP_FILES = (
    ("routes", "routes.json", "路由配置"),
    ("clusters", "clusters.json", "集群配置"),
    ("listeners", "listeners.json", "监听器配置"),
)


def _load_data_plane_configs(dp_dir: str, verbose: bool = False) -> Dict[str, Any]:
    configs: Dict[str, Any] = {}
    for key, filename, label in _DP_FILES:
        path = os.path.join(dp_dir, filename)
        if os.path.exists(path):
            configs[key] = load_json_file(path)
            if verbose:
                logger.info(f"已加载{label}: {path}")
        elif verbose:
            logger.warning(f"未找到{label}文件: {path}")
    return configs


def _load_config_files(config_dir: str, resource_type: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    加载指定资源类型的所有配置文件
    :param config_dir: 配置目录
    :param resource_type: 资源类型（services/virtualservices等）
    :param namespace: 可选的命名空间过滤
    :return: 配置字典
    """
    configs = {'items': []}
    resource_dir = os.path.join(config_dir, resource_type)
    
    if not os.path.exists(resource_dir):
        logger.warning(f"资源目录不存在: {resource_dir}")
        return configs
    
    try:
        # 如果指定了命名空间，只读取该命名空间的配置
        if namespace:
            ns_dir = os.path.join(resource_dir, namespace)
            if os.path.isdir(ns_dir):
                for config_file in os.listdir(ns_dir):
                    if config_file.endswith('.yaml'):
                        config_path = os.path.join(ns_dir, config_file)
                        config = load_yaml_file(config_path)
                        if config:
                            configs['items'].append(config)
        else:
            # 遍历所有命名空间目录
            for ns in os.listdir(resource_dir):
                ns_dir = os.path.join(resource_dir, ns)
                if os.path.isdir(ns_dir):
                    for config_file in os.listdir(ns_dir):
                        if config_file.endswith('.yaml'):
                            config_path = os.path.join(ns_dir, config_file)
                            config = load_yaml_file(config_path)
                            if config:
                                configs['items'].append(config)
    except Exception as e:
        logger.error(f"加载配置文件时出错: {str(e)}")
        return {'items': []}
    
    return configs

# 缓存 parse_to_legacy_format 结果，避免重复解析
_legacy_cache: Dict[str, tuple] = {}
_legacy_cache_key: Optional[str] = None


def parse_to_legacy_format(
    control_plane_dir: str,
    data_plane_dir: str,
    namespace: Optional[str] = None
) -> tuple:
    """
    使用 UnifiedParser 解析并转换为 legacy 格式
    :return: (ControlPlaneResult, DataPlaneResult)
    """
    cp_dir = _resolve_config_dir(control_plane_dir)
    dp_dir = _resolve_config_dir(data_plane_dir)

    cache_key = f"{cp_dir}|{dp_dir}|{namespace}"
    if cache_key in _legacy_cache:
        return _legacy_cache[cache_key]

    control_plane_configs = _load_control_plane_configs(cp_dir, namespace)
    data_plane_configs = _load_data_plane_configs(dp_dir)
    if not data_plane_configs.get("routes"):
        data_plane_configs["routes"] = []

    parser = UnifiedParser(
        enable_parallel=True,
        max_workers=None,
        tau=_get_tau(),
        timeout_abs=_get_timeout_abs(),
    )
    system_ir = parser.parse_align_and_build_ir(control_plane_configs, data_plane_configs)
    services = parse_services(control_plane_configs.get('services', {}))
    control_result, data_result = system_ir_to_legacy(system_ir, services)
    _legacy_cache[cache_key] = (control_result, data_result)
    return control_result, data_result


def parse_control_plane_from_dir(
    control_plane_dir: str = 'istio_config_parser/istio_monitor/istio_control_config',
    namespace: Optional[str] = None,
    data_plane_dir: Optional[str] = None
) -> ControlPlaneResult:
    """
    从配置目录解析控制平面配置（内部使用 UnifiedParser 并转换为 legacy 格式）
    :param control_plane_dir: 控制平面配置目录
    :param namespace: 可选的命名空间过滤
    :param data_plane_dir: 数据平面配置目录（用于 UnifiedParser 对齐，默认与 control 同级的 istio_sidecar_config）
    :return: 控制平面配置结果
    """
    dp_dir = data_plane_dir
    if dp_dir is None:
        dp_dir = control_plane_dir.replace('istio_control_config', 'istio_sidecar_config')
        if dp_dir == control_plane_dir:
            dp_dir = 'istio_config_parser/istio_monitor/istio_sidecar_config'
    control_result, _ = parse_to_legacy_format(control_plane_dir, dp_dir, namespace)
    return control_result


def parse_data_plane_from_dir(
    data_plane_dir: str = 'istio_config_parser/istio_monitor/istio_sidecar_config',
    control_plane_dir: Optional[str] = None
) -> DataPlaneResult:
    """
    从配置目录解析数据平面配置（内部使用 UnifiedParser 并转换为 legacy 格式）
    :param data_plane_dir: 数据平面配置目录
    :param control_plane_dir: 控制平面配置目录（用于 UnifiedParser 对齐）
    :return: 数据平面配置结果
    """
    cp_dir = control_plane_dir
    if cp_dir is None:
        cp_dir = data_plane_dir.replace('istio_sidecar_config', 'istio_control_config')
        if cp_dir == data_plane_dir:
            cp_dir = 'istio_config_parser/istio_monitor/istio_control_config'
    _, data_result = parse_to_legacy_format(cp_dir, data_plane_dir, None)
    return data_result


def _merge_data_plane_configs(
    base: Dict[str, Any],
    extra: Dict[str, Any],
    label: str = "ingress"
) -> Dict[str, Any]:
    """合并数据平面配置（sidecar + ingress），用于 Gateway 绑定项校验"""
    merged = dict(base)
    for key in ['routes', 'clusters', 'listeners']:
        if key not in extra or not extra[key]:
            continue
        a = base.get(key)
        b = extra[key]
        if a is None:
            a = []
        if b is None:
            b = []
        if not isinstance(a, list):
            a = [a]
        if not isinstance(b, list):
            b = [b]
        merged[key] = a + b
        if a and b:
            logger.info(f"已合并 {label} {key}: +{len(b)} 条")
    return merged


def parse_unified_from_dir(
    control_plane_dir: str = 'istio_config_parser/istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_config_parser/istio_monitor/istio_sidecar_config',
    ingress_plane_dir: Optional[str] = None,
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None,
    return_control_plane_configs: bool = False
):
    """
    使用统一解析器从配置目录解析控制平面和数据平面配置，生成中间表示（IR）
    
    这是推荐的解析方法，提供以下优势：
    - 语义聚合：自动聚合相关配置（如VirtualService + DestinationRule）
    - 双平面统一：使用统一的FunctionModel表示控制平面和数据平面
    - 一致性验证：自动检测配置不一致问题
    - 完整的IR：生成包含所有配置信息的中间表示
    - 并行处理：支持多线程并行解析不同配置类型，提高效率
    
    Args:
        control_plane_dir: 控制平面配置目录（相对于当前文件）
        data_plane_dir: 数据平面配置目录（sidecar 配置，相对于当前文件）
        ingress_plane_dir: Ingress Gateway 配置目录（可选，用于 Gateway 绑定项如 frontend-ingress/bookinfo 校验）
        namespace: 可选的命名空间过滤
        enable_parallel: 是否启用并行处理（默认True）
        max_workers: 最大工作线程数，None表示自动计算
        
    Returns:
        SystemIR: 系统级中间表示，包含所有服务的配置和一致性状态
        
    Example:
        >>> system_ir = parse_unified_from_dir(namespace='online-boutique')
        >>> summary = system_ir.get_summary()
        >>> print(f"一致性比例: {summary['consistency_rate']:.2%}")
    """
    cp_dir = _resolve_config_dir(control_plane_dir)
    dp_dir = _resolve_config_dir(data_plane_dir)

    # 加载控制平面配置
    logger.info("加载控制平面配置...")
    control_plane_configs = _load_control_plane_configs(cp_dir, namespace)

    # 加载数据平面配置
    logger.info("加载数据平面配置...")
    data_plane_configs = _load_data_plane_configs(dp_dir, verbose=True)

    if ingress_plane_dir:
        ig_dir = _resolve_config_dir(ingress_plane_dir)
        ingress_configs = _load_data_plane_configs(ig_dir)
        if ingress_configs:
            data_plane_configs = _merge_data_plane_configs(
                data_plane_configs, ingress_configs, "ingress gateway"
            )
        else:
            logger.warning(f"Ingress 目录 {ig_dir} 下未找到 routes/clusters/listeners.json")
    
    # 使用统一解析器（数值容差 tau 来自 configpilot.json）
    logger.info("开始解析和对齐配置...")
    parser = UnifiedParser(
        enable_parallel=enable_parallel,
        max_workers=max_workers,
        tau=_get_tau(),
        timeout_abs=_get_timeout_abs(),
    )
    system_ir = parser.parse_align_and_build_ir(control_plane_configs, data_plane_configs)
    
    logger.info("解析完成")
    if return_control_plane_configs:
        return system_ir, control_plane_configs
    return system_ir


ALIGNED_STATUSES = ("matched", "partial_matched")


def _strip_empty(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        cleaned = {k: _strip_empty(v) for k, v in obj.items() if v not in (None, "", [], {})}
        return {k: v for k, v in cleaned.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [item for item in (_strip_empty(v) for v in obj) if item not in (None, "", [], {})]
    return obj


_META_DROP = {
    "managedFields", "resourceVersion", "uid", "generation",
    "creationTimestamp", "selfLink", "ownerReferences",
}


def _clean_manifest(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or not raw.get("kind"):
        return None
    meta_in = dict(raw.get("metadata") or {})
    ann = dict(meta_in.get("annotations") or {})
    ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    meta = {
        k: meta_in[k]
        for k in ("name", "namespace", "labels")
        if meta_in.get(k)
    }
    if ann:
        meta["annotations"] = ann
    return {
        "apiVersion": raw.get("apiVersion") or "",
        "kind": raw["kind"],
        "metadata": meta,
        "spec": raw.get("spec") if isinstance(raw.get("spec"), dict) else {},
    }


def _iter_manifests(raw: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    if not isinstance(raw, dict):
        return found
    manifest = _clean_manifest(raw)
    if manifest:
        found.append(manifest)
        return found
    for value in raw.values():
        if isinstance(value, dict):
            found.extend(_iter_manifests(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found.extend(_iter_manifests(item))
    return found


def _host_parts(host: Any, default_ns: str) -> Tuple[str, str]:
    text = str(host or "").split(":")[0].strip()
    if not text:
        return default_ns, ""
    text = text.replace(".svc.cluster.local", "")
    parts = [p for p in text.split(".") if p]
    name = parts[0] if parts else ""
    ns = parts[1] if len(parts) > 1 else default_ns
    return ns or "default", name


def _svc_id(ns: str, name: str) -> str:
    return f"{ns or 'default'}/{name}"


def _res_id(kind: str, ns: str, name: str) -> str:
    return f"{kind}/{ns or 'default'}/{name}"


def _cluster_digest(item: Any) -> Optional[Dict[str, Any]]:
    cluster = item
    if isinstance(item, dict) and isinstance(item.get("cluster"), dict):
        cluster = item["cluster"]
    if not isinstance(cluster, dict):
        return None
    thresholds = ((cluster.get("circuit_breakers") or {}).get("thresholds") or [])
    return _strip_empty({
        "name": cluster.get("name") or cluster.get("alt_stat_name"),
        "lb_policy": cluster.get("lb_policy"),
        "connect_timeout": cluster.get("connect_timeout"),
        "circuit_breakers": thresholds,
    })


def _summarize_data_plane(dp: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(dp, dict):
        return None
    out: Dict[str, Any] = {}
    for key in (
        "function_type", "service_name", "namespace",
        "hosts", "routes", "gateways", "algorithm", "subsets",
        "connection_pool", "outlier_detection", "subset_policies",
        "rules", "rate_limit_type", "rate_limit_service",
        "retry_policy", "timeout", "idle_timeout", "destinations",
    ):
        val = dp.get(key)
        if val not in (None, "", [], {}):
            out[key] = _strip_empty(val)
    raw = dp.get("raw_config") or {}
    if isinstance(raw, dict):
        if raw.get("clusters") and "connection_pool" not in out:
            clusters = [_cluster_digest(c) for c in (raw.get("clusters") or [])]
            out["envoy_clusters"] = [c for c in clusters if c][:8]
        if raw.get("domains") and "hosts" not in out:
            out["hosts"] = raw.get("domains")
        routes = raw.get("routes")
        if routes and "routes" not in out:
            simplified = []
            for route in routes[:8]:
                if not isinstance(route, dict):
                    continue
                dest = route.get("route") or {}
                simplified.append(_strip_empty({
                    "match": route.get("match"),
                    "cluster": dest.get("cluster"),
                    "timeout": dest.get("timeout"),
                    "retry_policy": dest.get("retry_policy"),
                    "weighted_clusters": dest.get("weightedClusters") or dest.get("weighted_clusters"),
                }))
            if simplified:
                out["envoy_routes"] = simplified
    return out or None


def _ensure_service(
    nodes: Dict[str, Dict[str, Any]],
    ns: str,
    name: str,
) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    sid = _svc_id(ns, name)
    node = nodes.get(sid)
    if node is None:
        node = {
            "id": sid,
            "label": name,
            "namespace": ns or "default",
            "type": "service",
            "subsets": [],
            "functions": [],
            "resources": [],
            "declarative": [],
            "data_plane_rules": [],
            "alignment": "unknown",
        }
        nodes[sid] = node
    return node


def _add_function(node: Dict[str, Any], function_type: str, status: str) -> None:
    for item in node["functions"]:
        if item.get("function_type") == function_type:
            item["alignment_status"] = status
            return
    node["functions"].append({
        "function_type": function_type,
        "alignment_status": status,
    })


def _service_alignment(functions: List[Dict[str, Any]]) -> str:
    statuses = {str(f.get("alignment_status") or "") for f in functions}
    statuses.discard("")
    if not statuses:
        return "unknown"
    if statuses & {"mismatched", "inconsistent"}:
        return "mismatched"
    if "control_only" in statuses and "data_only" in statuses:
        return "mismatched"
    if "control_only" in statuses:
        return "control_only"
    if "data_only" in statuses:
        return "data_only"
    if "partial_matched" in statuses or "partial" in statuses:
        return "partial_matched"
    if statuses <= {"matched", "consistent"}:
        return "matched"
    return "unknown"


def _add_manifest(nodes: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]], edge_id: List[int],
                  seen_edges: set, manifest: Dict[str, Any], default_ns: str,
                  owner_svc: Optional[str] = None) -> None:
    kind = manifest.get("kind") or "Resource"
    meta = manifest.get("metadata") or {}
    name = meta.get("name") or kind.lower()
    ns = meta.get("namespace") or default_ns or "default"
    rid = _res_id(kind, ns, name)
    if rid not in nodes:
        nodes[rid] = {
            "id": rid,
            "label": f"{kind}/{name}",
            "name": name,
            "namespace": ns,
            "type": "resource",
            "kind": kind,
            "declarative": [manifest],
        }
    else:
        existing = nodes[rid].setdefault("declarative", [])
        if manifest not in existing:
            existing.append(manifest)

    targets: List[str] = []
    if owner_svc:
        targets.append(owner_svc)
    spec = manifest.get("spec") or {}
    if kind == "VirtualService":
        for host in spec.get("hosts") or []:
            hns, hname = _host_parts(host, ns)
            node = _ensure_service(nodes, hns, hname)
            if node:
                targets.append(node["id"])
        for http in spec.get("http") or []:
            for dest in (http.get("route") or []):
                destination = (dest or {}).get("destination") or {}
                hns, hname = _host_parts(destination.get("host"), ns)
                node = _ensure_service(nodes, hns, hname)
                if node:
                    targets.append(node["id"])
    elif kind == "DestinationRule":
        hns, hname = _host_parts(spec.get("host"), ns)
        node = _ensure_service(nodes, hns, hname)
        if node:
            targets.append(node["id"])
    elif kind == "EnvoyFilter":
        labels = ((spec.get("workloadSelector") or {}).get("labels") or {})
        app = labels.get("app") or labels.get("istio")
        if app:
            node = _ensure_service(nodes, ns, app)
            if node:
                targets.append(node["id"])

    elif kind == "Service":
        node = _ensure_service(nodes, ns, name)
        if node:
            targets.append(node["id"])

    seen = set()
    for tid in targets:
        if not tid or tid in seen:
            continue
        seen.add(tid)
        svc = nodes.get(tid)
        if svc and svc.get("type") == "service":
            ref = {"kind": kind, "name": name, "namespace": ns, "id": rid}
            if ref not in svc["resources"]:
                svc["resources"].append(ref)
            if manifest not in svc["declarative"]:
                svc["declarative"].append(manifest)
        ekey = (rid, tid, "declares")
        if ekey in seen_edges:
            continue
        seen_edges.add(ekey)
        edges.append({
            "id": f"edge_{edge_id[0]:04d}",
            "source": rid,
            "target": tid,
            "type": "declares",
            "label": kind,
        })
        edge_id[0] += 1


def _simple_graph_from_pairs(
    pairs: List[Dict[str, Any]],
    control_plane_configs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """服务 + Istio 资源图：命名空间、声明式配置、对应数据面规则。"""
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    edge_id = [1]
    seen_route = set()
    seen_edges: set = set()

    for pair in pairs:
        svc = pair.get("service_name") or ""
        ns = pair.get("namespace") or "default"
        node = _ensure_service(nodes, ns, svc)
        if not node:
            continue
        status = pair.get("alignment_status") or "unknown"
        ftype = pair.get("function_type") or "unknown"
        _add_function(node, ftype, status)

        for tup in (pair.get("control_tuples") or []) + (pair.get("data_tuples") or []):
            subsets = ((tup.get("scope") or {}).get("subsets") or [])
            node["subsets"] = list(dict.fromkeys((node.get("subsets") or []) + subsets))
            dests = ((tup.get("constraint") or {}).get("destinations") or [])
            weights = ((tup.get("constraint") or {}).get("weights") or {})
            for dest in dests:
                host = dest.get("host") or dest.get("subset") or ""
                tns, target = _host_parts(host, ns)
                if not target and dest.get("subset"):
                    target = svc
                    tns = ns
                if not target:
                    continue
                other = _ensure_service(nodes, tns, target)
                if not other:
                    continue
                if dest.get("subset"):
                    other["subsets"] = list(dict.fromkeys((other.get("subsets") or []) + [dest["subset"]]))
                weight = dest.get("weight")
                if weight is None and dest.get("subset") in weights:
                    weight = weights.get(dest.get("subset"))
                key = (node["id"], other["id"], weight, ftype)
                if key in seen_route:
                    continue
                seen_route.add(key)
                edges.append({
                    "id": f"edge_{edge_id[0]:04d}",
                    "source": node["id"],
                    "target": other["id"],
                    "type": "route",
                    "weight": weight,
                    "function_type": ftype,
                    "label": f"{weight}%" if weight is not None else ftype,
                })
                edge_id[0] += 1

        cp = pair.get("control_plane")
        if isinstance(cp, dict):
            for manifest in _iter_manifests(cp.get("raw_config")):
                    _add_manifest(nodes, edges, edge_id, seen_edges, manifest, ns, node["id"])

        dp = _summarize_data_plane(pair.get("data_plane"))
        if dp:
            dp["alignment_status"] = status
            node["data_plane_rules"].append(dp)

    kind_map = {
        "virtual_services": "VirtualService",
        "destination_rules": "DestinationRule",
        "envoy_filters": "EnvoyFilter",
        "gateways": "Gateway",
        "services": "Service",
    }
    for key, kind in kind_map.items():
        bucket = (control_plane_configs or {}).get(key) or {}
        items: List[Any]
        if isinstance(bucket, dict):
            items = bucket.get("items") if isinstance(bucket.get("items"), list) else list(bucket.values())
        elif isinstance(bucket, list):
            items = bucket
        else:
            items = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            payload = dict(raw)
            payload.setdefault("kind", kind)
            for manifest in _iter_manifests(payload):
                _add_manifest(
                    nodes, edges, edge_id, seen_edges, manifest,
                    manifest.get("metadata", {}).get("namespace") or "default",
                )

    for node in nodes.values():
        if node.get("type") == "service":
            node["alignment"] = _service_alignment(node.get("functions") or [])

    namespaces = sorted({n.get("namespace") or "default" for n in nodes.values()})
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "metadata": {
            "namespaces": namespaces,
            "service_count": sum(1 for n in nodes.values() if n.get("type") == "service"),
            "resource_count": sum(1 for n in nodes.values() if n.get("type") == "resource"),
        },
    }


def _expected_tuples_from_pairs(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    expected = []
    for pair in pairs:
        status = pair.get("alignment_status")
        if status not in ALIGNED_STATUSES:
            continue
        tuples = pair.get("control_tuples") or pair.get("data_tuples") or []
        for tup in tuples:
            item = dict(tup)
            item["alignment_status"] = status
            item["service_name"] = pair.get("service_name")
            item["namespace"] = pair.get("namespace")
            item["differences"] = pair.get("differences") or []
            expected.append(item)
    return expected


def parse_static_semantic(
    control_plane_dir: str = "istio_config_parser/istio_monitor/istio_control_config",
    data_plane_dir: str = "istio_config_parser/istio_monitor/istio_sidecar_config",
    ingress_plane_dir: Optional[str] = None,
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """一次解析：对齐语义元组、跨资源冲突，并写出 aligned_semantic.json。

    动态期望只能消费本产物中 alignment_status 为 matched / partial_matched 的元组。
    """
    from datetime import datetime
    from istio_config_parser.parsers.conflict_analyzer import analyze_cross_resource_conflicts

    parsed = parse_unified_from_dir(
        control_plane_dir=control_plane_dir,
        data_plane_dir=data_plane_dir,
        ingress_plane_dir=ingress_plane_dir,
        namespace=namespace,
        enable_parallel=enable_parallel,
        max_workers=max_workers,
        return_control_plane_configs=True,
    )
    system_ir, control_plane_configs = parsed
    services = parse_services(control_plane_configs.get("services", {}))
    control_result, data_result = system_ir_to_legacy(system_ir, services)

    pairs: List[Dict[str, Any]] = []
    for svc in system_ir.get_all_services():
        for func_ir in svc.functions.values():
            pair = func_ir.aligned_pair
            if pair is not None:
                pairs.append(pair.to_dict())
            else:
                pairs.append({
                    "function_type": func_ir.function_type.value if hasattr(func_ir.function_type, "value") else str(func_ir.function_type),
                    "service_name": func_ir.service_name,
                    "namespace": func_ir.namespace,
                    "alignment_status": func_ir.consistency_status.value,
                    "differences": [i.to_dict() for i in func_ir.issues],
                    "control_tuples": (func_ir.config or {}).get("control_tuples") or [],
                    "data_tuples": (func_ir.config or {}).get("data_tuples") or [],
                })

    conflicts = analyze_cross_resource_conflicts(control_plane_configs)
    expected_tuples = _expected_tuples_from_pairs(pairs)
    graph_data = _simple_graph_from_pairs(pairs, control_plane_configs)
    tau = _get_tau()
    timeout_abs = _get_timeout_abs()
    summary = system_ir.get_summary()
    summary["tau"] = tau
    summary["timeout_tolerance_seconds"] = timeout_abs
    summary["conflict_count"] = len(conflicts)
    summary["expected_tuple_count"] = len(expected_tuples)
    summary["aligned_pair_count"] = sum(
        1 for p in pairs if p.get("alignment_status") in ALIGNED_STATUSES
    )

    artifact = {
        "generated_at": datetime.now().isoformat(),
        "namespace": namespace,
        "tau": tau,
        "timeout_tolerance_seconds": timeout_abs,
        "summary": summary,
        "pairs": pairs,
        "conflicts": conflicts,
        "expected_tuples": expected_tuples,
        "control_plane": control_result,
        "data_plane": data_result,
        "graph_data": graph_data,
    }
    artifact_path = dump_aligned_semantic(artifact, output_path)
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "system_ir": system_ir,
        "control_plane": control_result,
        "data_plane": data_result,
        "conflicts": conflicts,
        "graph_data": graph_data,
        "summary": summary,
    }


def export_three_layer_graph(
    control_plane_dir: str = 'istio_config_parser/istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_config_parser/istio_monitor/istio_sidecar_config',
    ingress_plane_dir: Optional[str] = None,
    output_file: str = 'models_output/three_layer_graph.json',
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None
) -> str:
    """
    解析配置并导出三层配置依赖图
    
    三层结构：
    - 第一层（平面层）：控制面/数据面全局节点，边为一致/不一致匹配
    - 第二层（服务层）：服务与子服务节点，边为服务间功能关系
    - 第三层（配置层）：配置资源（VS/DR/EF），边为配置依赖
    
    跨层：第三层→第二层表示配置归属服务；第三层内边表示服务内配置依赖
    
    Returns:
        导出的 JSON 文件路径
    """
    from istio_config_parser.visualizer.three_layer_graph import ThreeLayerGraphGenerator
    
    system_ir = parse_unified_from_dir(
        control_plane_dir=control_plane_dir,
        data_plane_dir=data_plane_dir,
        ingress_plane_dir=ingress_plane_dir,
        namespace=namespace,
        enable_parallel=enable_parallel,
        max_workers=max_workers
    )
    
    cp_dir = _resolve_config_dir(control_plane_dir)
    control_plane_configs = _load_control_plane_configs(cp_dir, namespace)
    
    generator = ThreeLayerGraphGenerator(system_ir, control_plane_configs)
    generator.generate()
    
    out_path = output_file if os.path.isabs(output_file) else os.path.join(_PROJECT_ROOT, output_file)
    generator.save_to_file(out_path)
    
    return out_path


def parse_and_export_models(
    control_plane_dir: str = 'istio_config_parser/istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_config_parser/istio_monitor/istio_sidecar_config',
    output_dir: str = 'models_output',
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None
) -> Dict[str, str]:
    """
    解析配置并导出独立的建模文件
    
    此函数是 parse_unified_from_dir 的扩展版本，不仅生成IR，
    还会导出控制平面和数据平面的独立模型文件，便于后续分析和可视化。
    
    Args:
        control_plane_dir: 控制平面配置目录
        data_plane_dir: 数据平面配置目录
        output_dir: 输出目录
        namespace: 可选的命名空间过滤
        
    Returns:
        Dict[str, str]: 导出文件路径字典，包含：
            - control_plane_file: 控制平面模型文件
            - data_plane_file: 数据平面模型文件
            - comparison_file: 对比文件
            - visualization_file: 可视化数据文件
            
    Example:
        >>> files = parse_and_export_models(namespace='online-boutique')
        >>> print(f"控制平面模型: {files['control_plane_file']}")
    """
    cp_dir = _resolve_config_dir(control_plane_dir)
    dp_dir = _resolve_config_dir(data_plane_dir)
    out_dir = _resolve_config_dir(output_dir) if not os.path.isabs(output_dir) else output_dir

    # 加载控制平面配置
    logger.info("加载控制平面配置...")
    control_plane_configs = _load_control_plane_configs(cp_dir, namespace)
    
    # 加载数据平面配置
    logger.info("加载数据平面配置...")
    data_plane_configs = _load_data_plane_configs(dp_dir)
    
    # 使用统一解析器
    logger.info("开始解析配置...")
    parser = UnifiedParser(
        enable_parallel=enable_parallel,
        max_workers=max_workers,
        tau=_get_tau(),
        timeout_abs=_get_timeout_abs(),
    )
    exported_files = parser.parse_and_export(
        control_plane_configs, 
        data_plane_configs, 
        output_dir=out_dir
    )
    
    logger.info(f"模型文件已导出到: {out_dir}")
    return exported_files


def save_ir_to_file(system_ir: SystemIR, output_file: str):
    """
    将IR保存到文件
    
    Args:
        system_ir: 系统级IR
        output_file: 输出文件路径
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(system_ir.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info(f"IR已保存到: {output_file}")

if __name__ == "__main__":
    import argparse
    from istio_config_parser.utils.console_encoding import fix_console_encoding
    fix_console_encoding()

    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 命令行参数
    parser_cli = argparse.ArgumentParser(
        description='Istio配置统一解析器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 解析并生成IR（默认，并行处理）
  python main_parser.py
  
  # 解析特定命名空间
  python main_parser.py --namespace online-boutique
  
  # 保存IR到文件
  python main_parser.py --output my_ir.json
  
  # 导出模型文件（推荐）
  python main_parser.py --export --output-dir models_output
  
  # 禁用并行处理（使用串行）
  python main_parser.py --no-parallel
  
  # 指定最大工作线程数
  python main_parser.py --max-workers 4
  
  # 使用旧版解析器（已废弃）
  python main_parser.py --mode legacy --namespace online-boutique
        """
    )
    parser_cli.add_argument('--mode', choices=['legacy', 'unified'], default='unified',
                           help='解析模式：legacy（旧版，已废弃）或 unified（统一解析器，推荐）')
    parser_cli.add_argument('--namespace', type=str, default=None,
                           help='命名空间过滤（可选）')
    parser_cli.add_argument('--output', type=str, default=None,
                           help='输出IR文件路径（unified模式）')
    parser_cli.add_argument('--export', action='store_true',
                           help='导出独立的模型文件（控制平面/数据平面/可视化）')
    parser_cli.add_argument('--export-three-layer-graph', action='store_true',
                           help='导出三层配置依赖图（平面层/服务层/配置层）')
    parser_cli.add_argument('--output-dir', type=str, default='models_output',
                           help='模型文件输出目录（与--export一起使用）')
    parser_cli.add_argument('--summary', action='store_true', default=True,
                           help='显示摘要信息（默认开启）')
    parser_cli.add_argument('--details', action='store_true',
                           help='显示详细的服务和功能信息')
    parser_cli.add_argument('--control-plane-dir', type=str, 
                           default=None,
                           help='控制平面配置目录（支持项目根相对路径）')
    parser_cli.add_argument('--data-plane-dir', type=str,
                           default=None,
                           help='数据平面配置目录（支持项目根相对路径）')
    parser_cli.add_argument('--ingress-plane-dir', type=str,
                           default=None,
                           help='Ingress Gateway 配置目录')
    parser_cli.add_argument('--no-ingress', action='store_true',
                           help='禁用 Ingress Gateway 配置校验（不加载 istio_ingress_config）')
    parser_cli.add_argument('--no-parallel', action='store_true',
                           help='禁用并行处理（使用串行处理）')
    parser_cli.add_argument('--max-workers', type=int, default=None,
                           help='最大工作线程数（默认自动计算）')
    args = parser_cli.parse_args()
    try:
        from consistency_checker.config import fill_args_from_config
        fill_args_from_config(args, {
            "namespace": "namespace",
            "control_plane_dir": "control_plane_config_dir",
            "data_plane_dir": "data_plane_config_dir",
            "ingress_plane_dir": "ingress_plane_config_dir",
        })
    except Exception:
        pass
    if not args.control_plane_dir:
        args.control_plane_dir = 'istio_config_parser/istio_monitor/istio_control_config'
    if not args.data_plane_dir:
        args.data_plane_dir = 'istio_config_parser/istio_monitor/istio_sidecar_config'
    if not args.ingress_plane_dir:
        args.ingress_plane_dir = 'istio_config_parser/istio_monitor/istio_ingress_config'

    # --no-ingress 时禁用 ingress 配置
    ingress_plane_dir = None if args.no_ingress else args.ingress_plane_dir

    if args.mode == 'unified':
        # 解析并行处理选项
        enable_parallel = not args.no_parallel
        max_workers = args.max_workers
        
        print("\n" + "="*80)
        print("Istio配置统一解析器（Unified Parser）")
        print("="*80)
        print(f"控制平面目录: {args.control_plane_dir}")
        print(f"数据平面目录: {args.data_plane_dir}")
        if ingress_plane_dir:
            print(f"Ingress 目录:   {ingress_plane_dir} （Gateway 绑定项校验）")
        if args.namespace:
            print(f"命名空间过滤: {args.namespace}")
        print(f"并行处理: {'启用' if enable_parallel else '禁用'}")
        if enable_parallel and max_workers:
            print(f"最大工作线程: {max_workers}")
        print("="*80)
        
        # 如果使用导出模式
        if args.export:
            print("\n[模式] 解析并导出模型文件")
            print("-"*80)
            
            exported_files = parse_and_export_models(
                control_plane_dir=args.control_plane_dir,
                data_plane_dir=args.data_plane_dir,
                output_dir=args.output_dir,
                namespace=args.namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
            
            print("\n[成功] 模型文件已导出:")
            for file_type, file_path in exported_files.items():
                print(f"  - {file_type}: {file_path}")
            
            print(f"\n[提示] 可以使用以下方式查看可视化:")
            print(f"  cd {os.path.dirname(exported_files.get('visualization_file', args.output_dir))}")
            print(f"  python -m http.server 8080")
            print(f"  # 然后在浏览器访问: http://localhost:8080/visualization_demo.html")
        
        else:
            # 标准模式：生成IR
            print("\n[模式] 解析并生成中间表示（IR）")
            print("-"*80)
            
            bundle = parse_static_semantic(
                control_plane_dir=args.control_plane_dir,
                data_plane_dir=args.data_plane_dir,
                ingress_plane_dir=ingress_plane_dir,
                namespace=args.namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
            system_ir = bundle["system_ir"]
            print(f"\n[对齐模型] {bundle['artifact_path']}")
            print(f"[跨资源冲突] {len(bundle.get('conflicts') or [])} 项")
            
            # 打印摘要（功能级：以控制平面为意图，仅检测控制平面配置是否成功映射到数据平面）
            if args.summary:
                print("\n[系统级摘要]")
                print("-"*80)
                summary = system_ir.get_summary()
                total_func = summary.get('total_functions', 0)
                consistent_func = summary.get('consistent_functions', 0)
                inconsistent_func = summary.get('inconsistent_functions', 0)
                func_rate = summary.get('function_consistency_rate', 0)
                gateway_bound = summary.get('gateway_bound_functions', 0)
                print(f"待检测功能数:   {total_func} （控制平面有配置的路由/流量拆分/熔断等，DATA_ONLY 已忽略）")
                print(f"一致的功能:     {consistent_func} ({consistent_func/max(total_func,1)*100:.1f}%)")
                print(f"不一致的功能:   {inconsistent_func} ({inconsistent_func/max(total_func,1)*100:.1f}%)")
                if gateway_bound > 0:
                    print(f"Gateway 绑定:   {gateway_bound} （需采集 ingress gateway 配置才能校验，如 frontend-ingress/bookinfo）")
                print(f"一致性比例:     {func_rate:.2%}")
                print(f"总问题数:       {summary['total_issues']}")
                print(f"  - 错误:       {summary['total_errors']}")
                print(f"  - 警告:       {summary['total_warnings']}")
                print(f"（服务级: {summary['total_services']} 服务, {summary['consistent_services']} 一致）")
            
            # 打印详细信息
            if args.details:
                print("\n[服务详情]")
                print("-"*80)
                for service_ir in system_ir.get_all_services():
                    print(f"\n服务: {service_ir.namespace}.{service_ir.service_name}")
                    print(f"  一致性状态: {service_ir.get_consistency_status().value}")
                    print(f"  功能配置数: {len(service_ir.functions)}")
                    
                    for func_type, func_ir in service_ir.functions.items():
                        print(f"\n  功能: {func_type}")
                        print(f"    状态: {func_ir.consistency_status.value}")
                        print(f"    错误: {func_ir.get_error_count()}")
                        print(f"    警告: {func_ir.get_warning_count()}")
                        
                        if func_ir.has_issues():
                            print(f"    问题列表:")
                            for issue in func_ir.issues:
                                print(f"      - [{issue.severity}] {issue.field_path}")
                                print(f"        控制平面: {issue.control_plane_value}")
                                print(f"        数据平面: {issue.data_plane_value}")
                                if issue.description:
                                    print(f"        描述: {issue.description}")
            
            # 如果指定了输出文件，保存IR
            if args.output:
                save_ir_to_file(system_ir, args.output)
                print(f"\n[保存] 中间表示（IR）已保存到: {args.output}")
            
            print("\n[提示] 使用 --export 参数可导出独立的模型文件用于可视化")
    
    else:
        print("\n" + "="*80)
        print("使用旧版解析器（Legacy Parser）- 已废弃")
        print("="*80)
        print("[警告] 旧版解析器已废弃，建议使用 --mode unified")
        print("[警告] 旧版解析器不支持语义聚合和一致性验证")
        print("="*80)
        
        # 与 config.py 保持一致：istio_config_parser/istio_monitor/istio_control_config, istio_sidecar_config
        control_plane_dir = _resolve_config_dir(args.control_plane_dir)
        data_plane_dir = _resolve_config_dir(args.data_plane_dir)
        print(f"控制平面目录: {control_plane_dir}")
        print(f"数据平面目录: {data_plane_dir}")
        
        namespace = args.namespace or "online-boutique"
        control_plane = parse_control_plane_from_dir(control_plane_dir, namespace)
        data_plane = parse_data_plane_from_dir(data_plane_dir)
        
        # 打印控制平面配置
        print(f"\n命名空间 {namespace} 的控制平面配置：")
        for service in control_plane['services']:
            print(f"\n服务 {service['name']}:")
            print(f"  命名空间: {service['namespace']}")
            print(f"  类型: {service['type']}")
            print("  端口配置:")
            for port in service['ports']:
                print(f"    - 名称: {port['name']}")
                print(f"      端口: {port['port']}")
                print(f"      目标端口: {port['targetPort']}")
                print(f"      协议: {port['protocol']}")
            print(f"  选择器: {service['selector']}")
            print(f"  标签: {service['labels']}")
            print(f"  注解: {service['annotations']}")
            print(f"  集群IP: {service['clusterIP']}")
            print(f"  会话亲和性: {service['sessionAffinity']}")
            
            # 打印服务关系
            relations = control_plane['serviceRelations'].get(service['name'], {})
            print("\n  服务关系:")
            print("  入站路由:")
            for vs in relations.get('incomingVirtualServices', []):
                print(f"    - 名称: {vs['name']}")
                print(f"      命名空间: {vs['namespace']}")
                print(f"      规则数: {len(vs['rules'])}")
            
            print("  子集和权重:")
            # 获取所有子集
            subsets = {subset['name']: subset for subset in relations.get('subsets', [])}
            # 获取所有权重
            weights = relations.get('weights', {})
            
            # 合并显示子集和权重信息
            for subset_name, subset in subsets.items():
                print(f"    - 子集: {subset['name']}")
                print(f"      版本: {subset['version']}")
                print(f"      标签: {subset['labels']}")
                # 显示对应的权重信息
                if subset_name in weights:
                    weight_info = weights[subset_name]
                    print(f"      权重: {weight_info['weight']}")
                    print(f"      命名空间: {weight_info['namespace']}")
                else:
                    print("      权重: 未配置")
            
            print("  限流规则:")
            for limit in relations.get('rateLimit', []):
                print(f"    - 类型: {limit['type']}")
                print(f"      请求数: {limit['requests_per_unit']}")
                print(f"      时间单位: {limit['unit']}")
                print(f"      条件: {limit['conditions']}")
            
            print("  网关:")
            for gateway in relations.get('gateways', []):
                print(f"    - 名称: {gateway['name']}")
                print(f"      类型: {gateway['type']}")
                print(f"      虚拟服务: {gateway['virtualService']}")
                print(f"      命名空间: {gateway['namespace']}")
            
            print("  熔断配置:")
            # 显示全局熔断配置
            if relations.get('circuitBreaker'):
                circuit_breaker = relations['circuitBreaker']
                
                # 显示全局熔断配置
                if circuit_breaker.get('global_'):
                    print("    全局配置:")
                    global_policy = circuit_breaker['global_']
                    if global_policy and 'connectionPool' in global_policy:
                        cp = global_policy['connectionPool']
                        print("      连接池:")
                        if 'http' in cp:
                            print(f"        HTTP最大等待请求数: {cp['http'].get('http1MaxPendingRequests')}")
                            print(f"        HTTP最大请求数: {cp['http'].get('http2MaxRequests')}")
                            print(f"        每连接最大请求数: {cp['http'].get('maxRequestsPerConnection')}")
                            print(f"        最大重试次数: {cp['http'].get('maxRetries')}")
                        if 'tcp' in cp:
                            print(f"        TCP最大连接数: {cp['tcp'].get('maxConnections')}")
                            print(f"        连接超时: {cp['tcp'].get('connectTimeout')}")
                    
                    if global_policy and 'outlierDetection' in global_policy:
                        od = global_policy['outlierDetection']
                        print("      异常检测:")
                        print(f"        基础驱逐时间: {od.get('baseEjectionTime')}")
                        print(f"        连续5xx错误数: {od.get('consecutive5xxErrors')}")
                        print(f"        检测间隔: {od.get('interval')}")
                        print(f"        最大驱逐百分比: {od.get('maxEjectionPercent')}")
                        print(f"        最小健康百分比: {od.get('minHealthPercent')}")
                
                # 显示子集的熔断配置
                if circuit_breaker.get('subsets'):
                    for subset_name, subset_policy in circuit_breaker['subsets'].items():
                        # 跳过null配置
                        if subset_policy is None:
                            print(f"\n    子集 {subset_name} 配置: 未配置")
                            continue
                            
                        print(f"\n    子集 {subset_name} 配置:")
                        if subset_policy and 'connectionPool' in subset_policy:
                            cp = subset_policy['connectionPool']
                            print("      连接池:")
                            if 'http' in cp:
                                print(f"        HTTP最大等待请求数: {cp['http'].get('http1MaxPendingRequests')}")
                                print(f"        HTTP最大请求数: {cp['http'].get('http2MaxRequests')}")
                                print(f"        每连接最大请求数: {cp['http'].get('maxRequestsPerConnection')}")
                                print(f"        最大重试次数: {cp['http'].get('maxRetries')}")
                            if 'tcp' in cp:
                                print(f"        TCP最大连接数: {cp['tcp'].get('maxConnections')}")
                                print(f"        连接超时: {cp['tcp'].get('connectTimeout')}")
                        
                        if subset_policy and 'outlierDetection' in subset_policy:
                            od = subset_policy['outlierDetection']
                            print("      异常检测:")
                            print(f"        基础驱逐时间: {od.get('baseEjectionTime')}")
                            print(f"        连续5xx错误数: {od.get('consecutive5xxErrors')}")
                            print(f"        检测间隔: {od.get('interval')}")
                            print(f"        最大驱逐百分比: {od.get('maxEjectionPercent')}")
                            print(f"        最小健康百分比: {od.get('minHealthPercent')}")
        
        # 打印数据平面配置
        print("\n数据平面配置：")
        for service, relations in data_plane['serviceRelations'].items():
            print(f"\n服务 {service}:")
            print("  入站路由:")
            for route in relations.get('inbound', []):
                print(f"    - {route}")
            
            print("  出站路由:")
            for route in relations.get('outbound', []):
                print(f"    - 服务: {route['service']}")
                print(f"      端口: {route['port']}")
            
            print("  权重:")
            for subset, weight in relations.get('weights', {}).items():
                print(f"    - {subset}: {weight}") 