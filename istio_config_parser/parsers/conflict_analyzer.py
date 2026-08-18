"""跨资源依赖与作用域冲突：单资源合法、组合后语义破裂。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List


def _docs(block: Any) -> List[Dict[str, Any]]:
    if not block:
        return []
    if isinstance(block, list):
        return [d for d in block if isinstance(d, dict)]
    if isinstance(block, dict):
        items = block.get("items")
        if isinstance(items, list):
            return [d for d in items if isinstance(d, dict)]
        # {ns: {name: doc}} or {name: doc}
        docs = []
        for val in block.values():
            if isinstance(val, dict) and ("kind" in val or "spec" in val):
                docs.append(val)
            elif isinstance(val, dict):
                docs.extend(_docs(val))
        return docs
    return []


def _short_host(host: str) -> str:
    name = (host or "").split(".svc.cluster.local")[0]
    return name.split(".")[0] if name else ""


def _gw_id(doc: Dict[str, Any]) -> List[str]:
    meta = doc.get("metadata") or {}
    name = meta.get("name") or ""
    ns = meta.get("namespace") or ""
    ids = [name]
    if ns and name:
        ids.append(f"{ns}/{name}")
    return [i for i in ids if i]


def analyze_cross_resource_conflicts(control_plane_configs: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    vs_docs = _docs(control_plane_configs.get("virtual_services"))
    dr_docs = _docs(control_plane_configs.get("destination_rules"))
    gw_docs = _docs(control_plane_configs.get("gateways"))

    subsets_by_host: Dict[str, set] = defaultdict(set)
    for dr in dr_docs:
        spec = dr.get("spec") or {}
        host = _short_host(spec.get("host") or "")
        for subset in spec.get("subsets") or []:
            if isinstance(subset, dict) and subset.get("name"):
                subsets_by_host[host].add(subset["name"])

    gw_names = set()
    selector_index: Dict[tuple, List[str]] = defaultdict(list)
    for gw in gw_docs:
        gw_names.update(_gw_id(gw))
        meta = gw.get("metadata") or {}
        gw_name = meta.get("name") or "unknown"
        gw_ns = meta.get("namespace") or ""
        selector = (gw.get("spec") or {}).get("selector") or {}
        if not selector:
            issues.append({
                "type": "gateway_selector_empty",
                "severity": "medium",
                "gateway": gw_name,
                "namespace": gw_ns,
                "description": f"Gateway '{gw_name}' 未设置 selector，无法绑定到 ingress/gateway workload",
            })
        else:
            selector_index[tuple(sorted((str(k), str(v)) for k, v in selector.items()))].append(
                f"{gw_ns}/{gw_name}" if gw_ns else gw_name
            )
    for selector_key, names in selector_index.items():
        if len(names) > 1:
            issues.append({
                "type": "gateway_selector_conflict",
                "severity": "high",
                "gateways": names,
                "selector": dict(selector_key),
                "description": f"多个 Gateway {names} 使用相同 selector {dict(selector_key)}，入口选择器冲突",
            })
    gw_names.add("mesh")

    for vs in vs_docs:
        meta = vs.get("metadata") or {}
        vs_name = meta.get("name") or "unknown"
        vs_ns = meta.get("namespace") or "default"
        spec = vs.get("spec") or {}

        for gw in spec.get("gateways") or []:
            if gw not in gw_names and gw.split("/")[-1] not in gw_names:
                issues.append({
                    "type": "gateway_unmatched",
                    "severity": "high",
                    "virtualservice": vs_name,
                    "namespace": vs_ns,
                    "gateway": gw,
                    "description": f"VirtualService '{vs_name}' 绑定 Gateway '{gw}'，但未找到对应 Gateway 资源",
                })

        http_rules = spec.get("http") or []
        seen_matches = {}
        for idx, rule in enumerate(http_rules):
            match = rule.get("match") or []
            key = str(match)
            if key in seen_matches:
                issues.append({
                    "type": "route_priority_conflict",
                    "severity": "high",
                    "virtualservice": vs_name,
                    "namespace": vs_ns,
                    "rules": [seen_matches[key], idx],
                    "description": f"VirtualService '{vs_name}' 第 {seen_matches[key]} 与第 {idx} 条 HTTP 规则匹配条件相同，优先级冲突",
                })
            else:
                seen_matches[key] = idx

            for route in rule.get("route") or []:
                dest = route.get("destination") or {}
                subset = dest.get("subset")
                if not subset:
                    continue
                host = _short_host(dest.get("host") or "")
                available = subsets_by_host.get(host, set())
                if subset not in available:
                    issues.append({
                        "type": "missing_subset",
                        "severity": "high",
                        "virtualservice": vs_name,
                        "namespace": vs_ns,
                        "service": host,
                        "missing_subset": subset,
                        "available_subsets": sorted(available),
                        "description": (
                            f"VirtualService '{vs_name}' 引用 subset '{subset}'，"
                            f"但 DestinationRule 中 {host} 只定义了 {sorted(available) or '(无)'}"
                        ),
                    })
    return issues
