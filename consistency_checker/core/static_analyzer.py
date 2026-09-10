"""
静态分析器

消费 parser 产出的 aligned_semantic.json：策略、服务图、跨资源冲突。
不再自行解析 YAML，也不再做平面一致性 / VS subset 检查。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from consistency_checker.models.data_models import (
    ConfigEdge,
    ConsistencyStatus,
    PolicyType,
    ServiceNode,
    StaticPolicy,
)
from consistency_checker.config import get_config

logger = logging.getLogger(__name__)

_FUNCTION_TO_POLICY = {
    "routing": PolicyType.ROUTING,
    "traffic_shifting": PolicyType.TRAFFIC_SPLIT,
    "traffic_split": PolicyType.TRAFFIC_SPLIT,
    "retry": PolicyType.RETRY,
    "timeout": PolicyType.TIMEOUT,
    "circuit_breaker": PolicyType.CIRCUIT_BREAKER,
    "rate_limit": PolicyType.RATE_LIMIT,
    "fault_injection": PolicyType.FAULT_INJECTION,
}


class StaticAnalyzer:
    """静态配置分析器：只消费 parser 对齐产物。"""

    def __init__(self, config_dir: Optional[str] = None, namespace: Optional[str] = None):
        self.config = get_config()
        self.control_plane_config_dir = config_dir or self.config.control_plane_config_dir
        self.data_plane_config_dir = self.config.data_plane_config_dir
        self.namespace = namespace or self.config.namespace

        self.control_plane_data = None
        self.data_plane_data = None
        self.static_policies: List[StaticPolicy] = []
        self.service_nodes: List[ServiceNode] = []
        self.config_edges: List[ConfigEdge] = []
        self.artifact: Dict[str, Any] = {}

    @classmethod
    def from_artifact(cls, artifact: Dict[str, Any], namespace: Optional[str] = None) -> "StaticAnalyzer":
        analyzer = cls(namespace=namespace or artifact.get("namespace"))
        analyzer._consume_artifact(artifact)
        return analyzer

    def analyze(self) -> Dict[str, Any]:
        """加载对齐模型；若尚未生成则调用 parser 写一份。"""
        from istio_config_parser.main_parser import (
            AlignedModelMissingError,
            load_aligned_semantic,
            parse_static_semantic,
        )

        try:
            artifact = load_aligned_semantic()
            logger.info("Loaded aligned semantic model")
        except AlignedModelMissingError:
            logger.info("Aligned model missing; running parser static semantic pipeline")
            bundle = parse_static_semantic(
                control_plane_dir=self.control_plane_config_dir,
                data_plane_dir=self.data_plane_config_dir,
                namespace=self.namespace,
            )
            artifact = bundle["artifact"]

        return self._consume_artifact(artifact)

    def _consume_artifact(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        self.artifact = artifact or {}
        scope = self.namespace
        if scope:
            pairs = [
                p for p in (self.artifact.get("pairs") or [])
                if (p.get("namespace") or "default") == scope
            ]
            conflicts = [
                c for c in (self.artifact.get("conflicts") or [])
                if (c.get("namespace") or "default") == scope
            ]
            self.artifact = dict(self.artifact)
            self.artifact["pairs"] = pairs
            self.artifact["conflicts"] = conflicts
            graph = dict(self.artifact.get("graph_data") or {})
            nodes = [
                n for n in (graph.get("nodes") or [])
                if (n.get("namespace") or "default") == scope
            ]
            ids = {n.get("id") for n in nodes}
            graph["nodes"] = nodes
            graph["edges"] = [
                e for e in (graph.get("edges") or [])
                if e.get("source") in ids and e.get("target") in ids
            ]
            meta = dict(graph.get("metadata") or {})
            meta["namespaces"] = [scope]
            meta["service_count"] = sum(1 for n in nodes if n.get("type") == "service")
            meta["resource_count"] = sum(1 for n in nodes if n.get("type") == "resource")
            graph["metadata"] = meta
            self.artifact["graph_data"] = graph
        self.control_plane_data = self.artifact.get("control_plane") or {}
        self.data_plane_data = self.artifact.get("data_plane") or {}
        self.static_policies = []
        self.service_nodes = []
        self.config_edges = []

        self._extract_policies_from_tuples()
        self._build_service_graph_from_tuples()

        alignment_issues = []
        for pair in self.artifact.get("pairs") or []:
            status = pair.get("alignment_status")
            if status == "matched":
                continue
            for diff in pair.get("differences") or []:
                alignment_issues.append({
                    "type": "alignment_" + str(diff.get("kind") or status or "mismatch"),
                    "severity": "high" if diff.get("kind") == "discrete" else "medium",
                    "service": pair.get("service_name"),
                    "function_type": pair.get("function_type"),
                    "alignment_status": status,
                    "description": diff.get("description") or f"{pair.get('service_name')} {status}",
                    "control": diff.get("control"),
                    "data": diff.get("data"),
                })

        conflicts = list(self.artifact.get("conflicts") or [])
        issues = conflicts + alignment_issues

        return {
            "control_plane": self.control_plane_data,
            "data_plane": self.data_plane_data,
            "static_policies": self.static_policies,
            "service_nodes": self.service_nodes,
            "config_edges": self.config_edges,
            "plane_consistency_issues": issues,
            "conflicts": conflicts,
            "artifact": self.artifact,
            "summary": {
                "total_services": len(self.service_nodes),
                "total_policies": len(self.static_policies),
                "total_edges": len(self.config_edges),
                "has_inconsistencies": len(issues) > 0,
                "conflict_count": len(conflicts),
                "tau": self.artifact.get("tau"),
                "declared_functions": (self.artifact.get("summary") or {}).get("declared_functions"),
                "matched_functions": (self.artifact.get("summary") or {}).get("matched_functions"),
                "static_match_rate": (self.artifact.get("summary") or {}).get("static_match_rate"),
                "consistency_rate": (self.artifact.get("summary") or {}).get("consistency_rate"),
            },
        }

    def _extract_policies_from_tuples(self):
        counter = 1
        seen = set()
        for pair in self.artifact.get("pairs") or []:
            ftype = pair.get("function_type") or ""
            policy_type = _FUNCTION_TO_POLICY.get(ftype)
            if policy_type is None:
                continue
            tuples = pair.get("control_tuples") or []
            if not tuples:
                continue
            for tup in tuples:
                key = tup.get("tuple_id") or f"{pair.get('service_name')}.{ftype}.{counter}"
                if key in seen:
                    continue
                seen.add(key)
                scope = tup.get("scope") or {}
                policy = StaticPolicy(
                    policy_id=f"policy_{counter:04d}",
                    policy_type=policy_type,
                    source_service="*",
                    target_service=pair.get("service_name") or scope.get("service") or "",
                    namespace=pair.get("namespace") or scope.get("namespace") or self.namespace,
                    config_name=key,
                    config_type="SemanticTuple",
                    rules={
                        "predicate": tup.get("predicate") or {},
                        "action": tup.get("action") or {},
                        "constraint": tup.get("constraint") or {},
                        "alignment_status": pair.get("alignment_status"),
                    },
                    match_conditions=tup.get("predicate") or {},
                    applies_to=list(scope.get("subsets") or []),
                    created_at=datetime.now(),
                )
                self.static_policies.append(policy)
                counter += 1

    def _build_service_graph_from_tuples(self):
        graph = self.artifact.get("graph_data") or {}
        service_map: Dict[str, ServiceNode] = {}
        relations = (self.control_plane_data or {}).get("serviceRelations") or {}
        scoped_svcs = None
        if self.namespace:
            scoped_svcs = {
                n.get("label") or (n.get("id") or "").split("/")[-1]
                for n in (graph.get("nodes") or [])
                if n.get("type") == "service" and (n.get("namespace") or "default") == self.namespace
            }

        for svc_name, rels in relations.items():
            if scoped_svcs is not None and svc_name not in scoped_svcs:
                continue
            subsets = [s["name"] for s in rels.get("subsets", []) if isinstance(s, dict) and s.get("name")]
            node = ServiceNode(
                service_name=svc_name,
                namespace=self.namespace,
                node_type="service",
                subsets=subsets,
                has_virtualservice=len(rels.get("incomingVirtualServices", [])) > 0,
                has_destinationrule=len(subsets) > 0,
                has_policies=[p.policy_id for p in self.static_policies if p.target_service == svc_name],
                consistency_status=ConsistencyStatus.UNKNOWN,
            )
            self.service_nodes.append(node)
            service_map[svc_name] = node

        for raw in graph.get("nodes") or []:
            name = raw.get("id") or raw.get("label")
            if not name or name in service_map:
                continue
            node = ServiceNode(
                service_name=name,
                namespace=raw.get("namespace") or self.namespace,
                node_type=raw.get("type") or "service",
                subsets=list(raw.get("subsets") or []),
                has_policies=[p.policy_id for p in self.static_policies if p.target_service == name],
                consistency_status=ConsistencyStatus.UNKNOWN,
            )
            self.service_nodes.append(node)
            service_map[name] = node

        edge_counter = 1
        for raw in graph.get("edges") or []:
            source = raw.get("source")
            target = raw.get("target")
            if not source or not target:
                continue
            self.config_edges.append(ConfigEdge(
                edge_id=raw.get("id") or f"edge_{edge_counter:04d}",
                source=source,
                target=target,
                edge_type=raw.get("type") or "route",
                weight=raw.get("weight"),
                policies=[
                    p.policy_id for p in self.static_policies
                    if p.target_service in (source, target)
                ],
                consistency_status=ConsistencyStatus.UNKNOWN,
                label=raw.get("label") or "",
            ))
            edge_counter += 1

        if not self.config_edges:
            for service_name, relations in ((self.control_plane_data or {}).get("serviceRelations") or {}).items():
                for vs in relations.get("incomingVirtualServices", []):
                    for rule in vs.get("rules", []):
                        for route in rule.get("route", []):
                            dest = (route.get("destination") or {}).get("host", "")
                            target = dest.split(".")[0] if dest else ""
                            if not target:
                                continue
                            self.config_edges.append(ConfigEdge(
                                edge_id=f"edge_{edge_counter:04d}",
                                source=service_name,
                                target=target,
                                edge_type="route",
                                weight=route.get("weight"),
                                policies=[],
                                consistency_status=ConsistencyStatus.UNKNOWN,
                                label=f"{route.get('weight', 100)}%",
                            ))
                            edge_counter += 1

    def get_policy_by_id(self, policy_id: str) -> Optional[StaticPolicy]:
        for policy in self.static_policies:
            if policy.policy_id == policy_id:
                return policy
        return None

    def get_policies_by_service(self, service_name: str) -> List[StaticPolicy]:
        return [p for p in self.static_policies if p.target_service == service_name]
