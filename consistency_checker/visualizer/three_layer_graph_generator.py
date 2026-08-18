"""
三层空间配置依赖图生成器

从静态分析结果和一致性检查结果构建三层空间服务依赖图，
输出 D3.js 兼容的 JSON 格式用于可视化。
"""

import json
import logging
from typing import Dict, List, Any, Optional

from consistency_checker.models.three_layer_graph_models import (
    ThreeLayerGraph,
    Layer1Node,
    Layer1Edge,
    Layer2Node,
    Layer2Edge,
    Layer3Node,
    Layer3Edge,
    CrossLayerEdge,
    PlaneType,
    LayerType,
    ConsistencyMatchType,
    FunctionalRelationType,
    ConfigResourceType,
)
from consistency_checker.models.data_models import (
    ConsistencyStatus,
    ConsistencyResult,
)

logger = logging.getLogger(__name__)


class ThreeLayerGraphGenerator:
    """三层空间配置依赖图生成器"""

    @classmethod
    def from_static_result(
        cls,
        static_result: Dict[str, Any],
        consistency_result: Optional[ConsistencyResult] = None,
        namespace: str = "default",
    ) -> "ThreeLayerGraphGenerator":
        """
        从静态分析结果创建生成器

        Args:
            static_result: 静态分析结果 (含 control_plane, data_plane, service_nodes, config_edges)
            consistency_result: 一致性检查结果
            namespace: 命名空间
        """
        cp = static_result.get("control_plane", {})
        dp = static_result.get("data_plane", {})
        return cls(
            control_plane_data=cp,
            data_plane_data=dp,
            service_nodes=static_result.get("service_nodes", []),
            config_edges=static_result.get("config_edges", []),
            consistency_result=consistency_result,
            namespace=namespace,
            issues=static_result.get("plane_consistency_issues")
            or static_result.get("conflicts")
            or [],
        )

    def __init__(
        self,
        control_plane_data: Dict[str, Any],
        data_plane_data: Dict[str, Any],
        service_nodes: Optional[List[Any]] = None,
        config_edges: Optional[List[Any]] = None,
        consistency_result: Optional[ConsistencyResult] = None,
        namespace: str = "default",
        issues: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        初始化三层图生成器

        Args:
            control_plane_data: 控制平面解析结果 (serviceRelations 等)
            data_plane_data: 数据平面解析结果
            service_nodes: 服务节点列表 (可选，用于补充)
            config_edges: 配置边列表 (可选)
            consistency_result: 一致性检查结果
            namespace: 命名空间
        """
        self.control_plane_data = control_plane_data or {}
        self.data_plane_data = data_plane_data or {}
        self.service_nodes = service_nodes or []
        self.config_edges = config_edges or []
        self.consistency_result = consistency_result
        self.namespace = namespace
        self.issues = list(issues or [])

        self.graph = ThreeLayerGraph()
        self._id_counter = 0

    def _next_id(self, prefix: str = "n") -> str:
        self._id_counter += 1
        return f"{prefix}_{self._id_counter:04d}"

    def generate(self) -> ThreeLayerGraph:
        """生成完整的三层图"""
        logger.info("生成三层空间配置依赖图")

        self._build_layer1()
        logger.info(f"  ✓ Layer1: {len(self.graph.layer1_nodes)} 节点, {len(self.graph.layer1_edges)} 边")

        self._build_layer2()
        logger.info(f"  ✓ Layer2: {len(self.graph.layer2_nodes)} 节点, {len(self.graph.layer2_edges)} 边")

        self._build_layer3()
        logger.info(f"  ✓ Layer3: {len(self.graph.layer3_nodes)} 节点, {len(self.graph.layer3_edges)} 边")

        self._build_cross_layer_edges()
        logger.info(f"  ✓ 跨层边: {len(self.graph.cross_layer_edges)} 条")

        self._add_metadata()
        return self.graph

    def _build_layer1(self):
        """构建第一层：控制面/数据面/一致性检查器"""
        # 节点
        self.graph.layer1_nodes = [
            Layer1Node(
                id="control_plane",
                label="Control Plane",
                plane_type=PlaneType.CONTROL_PLANE,
            ),
            Layer1Node(
                id="data_plane",
                label="Data Plane",
                plane_type=PlaneType.DATA_PLANE,
            ),
            Layer1Node(
                id="consistency_checker",
                label="Consistency Checker",
                plane_type=PlaneType.CONSISTENCY_CHECKER,
            ),
        ]

        # 边：控制面/数据面 → 一致性检查器（一致/不一致匹配）
        cp_services = set(self.control_plane_data.get("serviceRelations", {}).keys())
        dp_services = set(self.data_plane_data.get("serviceRelations", {}).keys())
        common_services = cp_services & dp_services

        # 控制面配置 → 一致性检查器
        match_type = ConsistencyMatchType.CONSISTENT
        if self.issues:
            match_type = ConsistencyMatchType.INCONSISTENT
        if self.consistency_result:
            status = self.consistency_result.overall_status
            if status == ConsistencyStatus.INCONSISTENT or self.issues:
                match_type = ConsistencyMatchType.INCONSISTENT
            elif status == ConsistencyStatus.PARTIAL:
                match_type = ConsistencyMatchType.PARTIAL
            elif status == ConsistencyStatus.UNKNOWN:
                match_type = ConsistencyMatchType.UNKNOWN

        config_refs = [
            {"service": s, "plane": "control"} for s in cp_services
        ]
        self.graph.layer1_edges.append(
            Layer1Edge(
                id=self._next_id("l1e"),
                source="control_plane",
                target="consistency_checker",
                match_type=match_type,
                label=f"控制面配置 ({len(cp_services)} 服务)",
                config_refs=config_refs[:20],  # 限制数量
            )
        )

        # 数据面配置 → 一致性检查器
        dp_refs = [
            {"service": s, "plane": "data"} for s in dp_services
        ]
        self.graph.layer1_edges.append(
            Layer1Edge(
                id=self._next_id("l1e"),
                source="data_plane",
                target="consistency_checker",
                match_type=match_type,
                label=f"数据面状态 ({len(dp_services)} 服务)",
                config_refs=dp_refs[:20],
            )
        )

    def _build_layer2(self):
        """构建第二层：服务与子服务，服务间功能关系"""
        cp_relations = self.control_plane_data.get("serviceRelations", {})
        dp_relations = self.data_plane_data.get("serviceRelations", {})
        all_services = set(cp_relations.keys()) | set(dp_relations.keys())

        node_ids = set()

        # Gateway 节点（若有）
        def _edge_source(e):
            return e.source if hasattr(e, "source") else (e.get("source", "") if isinstance(e, dict) else "")

        has_gateway = any(
            rel.get("gateways") for rel in cp_relations.values()
        ) or any(
            _edge_source(e) == "istio-gateway" for e in self.config_edges
        )
        if has_gateway:
            gw_id = "istio-gateway"
            self.graph.layer2_nodes.append(
                Layer2Node(
                    id=gw_id,
                    label="istio-gateway",
                    plane_type=PlaneType.CONTROL_PLANE,
                    node_type="gateway",
                    namespace=self.namespace,
                )
            )
            node_ids.add(gw_id)

        # 控制面服务节点
        for svc in all_services:
            rel = cp_relations.get(svc, {})
            subsets = rel.get("subsets", [])
            weights = rel.get("weights", {})

            # 主服务节点 (控制面)
            cp_svc_id = f"cp_svc_{svc}"
            if cp_svc_id not in node_ids:
                self.graph.layer2_nodes.append(
                    Layer2Node(
                        id=cp_svc_id,
                        label=svc,
                        plane_type=PlaneType.CONTROL_PLANE,
                        node_type="service",
                        namespace=self.namespace,
                    )
                )
                node_ids.add(cp_svc_id)

            # 子集节点 (SVC-A V1, SVC-A V2)
            for sub in subsets:
                sub_name = sub.get("name", sub) if isinstance(sub, dict) else getattr(sub, "name", str(sub))
                sub_id = f"cp_svc_{svc}_{sub_name}"
                if sub_id not in node_ids:
                    self.graph.layer2_nodes.append(
                        Layer2Node(
                            id=sub_id,
                            label=f"{svc} {sub_name}",
                            plane_type=PlaneType.CONTROL_PLANE,
                            parent_service=cp_svc_id,
                            node_type="subset",
                            namespace=self.namespace,
                        )
                    )
                    node_ids.add(sub_id)

            # 数据面：envoy 代理、pod
            dp_svc_id = f"dp_envoy_{svc}"
            if dp_svc_id not in node_ids:
                self.graph.layer2_nodes.append(
                    Layer2Node(
                        id=dp_svc_id,
                        label=f"envoy-{svc}",
                        plane_type=PlaneType.DATA_PLANE,
                        parent_service=cp_svc_id,
                        node_type="envoy",
                        namespace=self.namespace,
                    )
                )
                node_ids.add(dp_svc_id)

            for sub in subsets:
                sub_name = sub.get("name", sub) if isinstance(sub, dict) else getattr(sub, "name", str(sub))
                pod_id = f"dp_pod_{svc}_{sub_name}"
                if pod_id not in node_ids:
                    self.graph.layer2_nodes.append(
                        Layer2Node(
                            id=pod_id,
                            label=f"pod {svc}/{sub_name}",
                            plane_type=PlaneType.DATA_PLANE,
                            parent_service=dp_svc_id,
                            node_type="pod",
                            namespace=self.namespace,
                        )
                    )
                    node_ids.add(pod_id)

        # 全局限速器（若有 RateLimit）
        has_rls = any(
            rel.get("rateLimit") for rel in cp_relations.values()
        )
        if has_rls:
            rls_id = "dp_rls_global"
            if rls_id not in node_ids:
                self.graph.layer2_nodes.append(
                    Layer2Node(
                        id=rls_id,
                        label="rls-server global limiter",
                        plane_type=PlaneType.DATA_PLANE,
                        node_type="rls_server",
                        namespace=self.namespace,
                    )
                )
                node_ids.add(rls_id)

        # 第二层边：服务间功能关系
        self._build_layer2_edges(cp_relations, node_ids)

    def _build_layer2_edges(self, cp_relations: Dict, node_ids: set):
        """构建第二层功能关系边"""
        # 从 config_edges 提取
        for edge in self.config_edges:
            src = edge.source if hasattr(edge, "source") else edge.get("source", "")
            tgt = edge.target if hasattr(edge, "target") else edge.get("target", "")
            edge_type = edge.edge_type if hasattr(edge, "edge_type") else edge.get("edge_type", "route")
            weight = getattr(edge, "weight", None) or (edge.get("weight") if isinstance(edge, dict) else None)
            label = getattr(edge, "label", None) or (edge.get("label") if isinstance(edge, dict) else None)

            rel_type = FunctionalRelationType.ROUTE
            if edge_type == "gateway":
                rel_type = FunctionalRelationType.GATEWAY
                src = "istio-gateway"
            elif edge_type == "traffic_split":
                rel_type = FunctionalRelationType.TRAFFIC_SPLIT
                if src == tgt:
                    continue

            cp_src = f"cp_svc_{src}" if src != "istio-gateway" else "istio-gateway"
            cp_tgt = f"cp_svc_{tgt}"
            dp_src = f"dp_envoy_{src}" if src != "istio-gateway" else "istio-gateway"
            dp_tgt = f"dp_envoy_{tgt}"

            # 控制面 Route / Gateway
            if cp_src in node_ids and cp_tgt in node_ids:
                self.graph.layer2_edges.append(
                    Layer2Edge(
                        id=self._next_id("l2e"),
                        source=cp_src,
                        target=cp_tgt,
                        relation_type=rel_type,
                        label=label or ("Route" if rel_type != FunctionalRelationType.GATEWAY else "Gateway"),
                        weight=weight,
                    )
                )
            # 数据面 Route（仅非 gateway，gateway 在控制面）
            if edge_type != "gateway" and dp_src in node_ids and dp_tgt in node_ids:
                self.graph.layer2_edges.append(
                    Layer2Edge(
                        id=self._next_id("l2e"),
                        source=dp_src,
                        target=dp_tgt,
                        relation_type=rel_type,
                        label=label or "Route",
                        weight=weight,
                    )
                )

        # 从 VirtualService 规则提取路由
        for svc, rel in cp_relations.items():
            for vs in rel.get("incomingVirtualServices", []):
                for rule in vs.get("rules", []):
                    for route in rule.get("route", []):
                        dest = route.get("destination", {})
                        target_host = dest.get("host", "")
                        if target_host:
                            target_svc = target_host.split(".")[0]
                            if target_svc != svc and f"cp_svc_{target_svc}" in {n.id for n in self.graph.layer2_nodes}:
                                self.graph.layer2_edges.append(
                                    Layer2Edge(
                                        id=self._next_id("l2e"),
                                        source=f"cp_svc_{svc}",
                                        target=f"cp_svc_{target_svc}",
                                        relation_type=FunctionalRelationType.ROUTE,
                                        label="Route",
                                        weight=route.get("weight"),
                                    )
                                )

            # 流量分配边：控制面 service → subset（期望），数据面 envoy → pod（默认按配置，观测值稍后覆盖）
            weights = rel.get("weights", {})
            for sub_name, w_info in weights.items():
                w = w_info.get("weight", w_info) if isinstance(w_info, dict) else w_info
                cp_src = f"cp_svc_{svc}"
                cp_sub = f"cp_svc_{svc}_{sub_name}"
                if cp_src in {n.id for n in self.graph.layer2_nodes} and cp_sub in {n.id for n in self.graph.layer2_nodes}:
                    self.graph.layer2_edges.append(
                        Layer2Edge(
                            id=self._next_id("l2e"),
                            source=cp_src,
                            target=cp_sub,
                            relation_type=FunctionalRelationType.TRAFFIC_SPLIT,
                            label=f"Exp {w}%",
                            weight=w,
                            role="expected",
                        )
                    )
                envoy_id = f"dp_envoy_{svc}"
                pod_id = f"dp_pod_{svc}_{sub_name}"
                if envoy_id in {n.id for n in self.graph.layer2_nodes} and pod_id in {n.id for n in self.graph.layer2_nodes}:
                    self.graph.layer2_edges.append(
                        Layer2Edge(
                            id=self._next_id("l2e"),
                            source=envoy_id,
                            target=pod_id,
                            relation_type=FunctionalRelationType.TRAFFIC_SPLIT,
                            label=f"Exp {w}%",
                            weight=w,
                            role="expected",
                        )
                    )

            # RateLimit 边
            if rel.get("rateLimit"):
                for dp_n in self.graph.layer2_nodes:
                    if dp_n.id == f"dp_envoy_{svc}":
                        self.graph.layer2_edges.append(
                            Layer2Edge(
                                id=self._next_id("l2e"),
                                source=dp_n.id,
                                target="dp_rls_global",
                                relation_type=FunctionalRelationType.RATE_LIMIT,
                                label="RateLimit",
                            )
                        )
                        break

        self._overlay_observed_splits()

    def _overlay_observed_splits(self):
        """把动态数据面测到的流量权重画到 envoy → pod 上（Obs），与控制面期望（Exp）并列。"""
        node_ids = {n.id for n in self.graph.layer2_nodes}
        for issue in self.issues:
            if not isinstance(issue, dict):
                continue
            itype = str(issue.get("type") or "")
            if itype not in ("traffic_split_drift", "weight_error", "alignment_traffic_split"):
                continue
            svc = (issue.get("service") or "").strip()
            expected = issue.get("expected") or {}
            observed = issue.get("observed") or {}
            if not svc or not isinstance(observed, dict) or not observed:
                continue
            envoy_id = f"dp_envoy_{svc}"
            for edge in self.graph.layer2_edges:
                if edge.source != envoy_id or not str(edge.target).startswith(f"dp_pod_{svc}_"):
                    continue
                sub = str(edge.target)[len(f"dp_pod_{svc}_"):]
                edge.role = "expected"
                if sub in expected:
                    try:
                        edge.weight = int(expected[sub])
                    except (TypeError, ValueError):
                        pass
                if edge.weight is not None:
                    edge.label = f"Exp {edge.weight}%"
            for sub, raw in observed.items():
                try:
                    w = int(raw)
                except (TypeError, ValueError):
                    continue
                pod_id = f"dp_pod_{svc}_{sub}"
                if envoy_id not in node_ids or pod_id not in node_ids:
                    continue
                self.graph.layer2_edges.append(
                    Layer2Edge(
                        id=self._next_id("l2e"),
                        source=envoy_id,
                        target=pod_id,
                        relation_type=FunctionalRelationType.TRAFFIC_SPLIT,
                        label=f"Obs {w}%",
                        weight=w,
                        role="observed",
                    )
                )

    def _build_layer3(self):
        """构建第三层：配置资源及依赖"""
        cp_relations = self.control_plane_data.get("serviceRelations", {})

        for svc, rel in cp_relations.items():
            # DR（每服务一个）
            dr_id = f"cp_{svc}_DR"
            if rel.get("subsets"):
                self.graph.layer3_nodes.append(
                    Layer3Node(
                        id=dr_id,
                        label="DR",
                        resource_type=ConfigResourceType.DR,
                        service_name=svc,
                        plane_type=PlaneType.CONTROL_PLANE,
                        config_name=f"{svc}-dr",
                        namespace=self.namespace,
                    )
                )

            # VS
            for vs in rel.get("incomingVirtualServices", []):
                vs_name = vs.get("name", "vs")
                vs_id = f"cp_{svc}_VS_{vs_name}"
                self.graph.layer3_nodes.append(
                    Layer3Node(
                        id=vs_id,
                        label="VS",
                        resource_type=ConfigResourceType.VS,
                        service_name=svc,
                        plane_type=PlaneType.CONTROL_PLANE,
                        config_name=vs_name,
                        namespace=self.namespace,
                    )
                )
                # DR -> VS (Subnet 引用)
                if rel.get("subsets"):
                    dr_id = f"cp_{svc}_DR"
                    self.graph.layer3_edges.append(
                        Layer3Edge(
                            id=self._next_id("l3e"),
                            source=dr_id,
                            target=vs_id,
                            label="Subnet",
                            dependency_type="references",
                        )
                    )
                # VS -> 子集 (流量分配)
                for rule in vs.get("rules", []):
                    for route in rule.get("route", []):
                        dest = route.get("destination", {})
                        sub = dest.get("subset")
                        if sub:
                            sub_node_id = f"cp_svc_{svc}_{sub}"
                            if any(n.id == sub_node_id for n in self.graph.layer2_nodes):
                                self.graph.cross_layer_edges.append(
                                    CrossLayerEdge(
                                        id=self._next_id("cle"),
                                        source=vs_id,
                                        target=sub_node_id,
                                        relation_type=FunctionalRelationType.TRAFFIC_SPLIT,
                                        label=f"{route.get('weight', 100)}%",
                                    )
                                )

            # EF, RLS
            if rel.get("rateLimit"):
                ef_id = f"cp_{svc}_EF"
                rls_id = f"cp_{svc}_RLS"
                self.graph.layer3_nodes.append(
                    Layer3Node(
                        id=ef_id,
                        label="EF",
                        resource_type=ConfigResourceType.EF,
                        service_name=svc,
                        plane_type=PlaneType.CONTROL_PLANE,
                        config_name=f"{svc}-ratelimit",
                        namespace=self.namespace,
                    )
                )
                self.graph.layer3_nodes.append(
                    Layer3Node(
                        id=rls_id,
                        label="RLS",
                        resource_type=ConfigResourceType.RLS,
                        service_name=svc,
                        plane_type=PlaneType.CONTROL_PLANE,
                        config_name=f"{svc}-rls",
                        namespace=self.namespace,
                    )
                )
                self.graph.layer3_edges.append(
                    Layer3Edge(
                        id=self._next_id("l3e"),
                        source=ef_id,
                        target=rls_id,
                        label="",
                        dependency_type="references",
                    )
                )
                if rel.get("subsets"):
                    dr_id = f"cp_{svc}_DR"
                    self.graph.layer3_edges.append(
                        Layer3Edge(
                            id=self._next_id("l3e"),
                            source=rls_id,
                            target=dr_id,
                            label="",
                            dependency_type="references",
                        )
                    )

        # 数据面：envoy route 配置节点
        dp_relations = self.data_plane_data.get("serviceRelations", {})
        for svc in dp_relations:
            dp_route_id = f"dp_{svc}_route"
            self.graph.layer3_nodes.append(
                Layer3Node(
                    id=dp_route_id,
                    label="envoy route",
                    resource_type=ConfigResourceType.VS,  # 用 VS 表示路由配置
                    service_name=svc,
                    plane_type=PlaneType.DATA_PLANE,
                    config_name=f"{svc}-envoy-route",
                    namespace=self.namespace,
                )
            )

    def _build_cross_layer_edges(self):
        """构建跨层边：第三层资源 -> 第二层服务（服务间依赖）"""
        cp_relations = self.control_plane_data.get("serviceRelations", {})

        for svc, rel in cp_relations.items():
            for vs in rel.get("incomingVirtualServices", []):
                vs_id = f"cp_{svc}_VS_{vs.get('name', 'vs')}"
                for rule in vs.get("rules", []):
                    for route in rule.get("route", []):
                        dest = route.get("destination", {})
                        target_host = dest.get("host", "")
                        if target_host:
                            target_svc = target_host.split(".")[0]
                            if target_svc != svc:
                                tgt_id = f"cp_svc_{target_svc}"
                                if any(n.id == tgt_id for n in self.graph.layer2_nodes):
                                    self.graph.cross_layer_edges.append(
                                        CrossLayerEdge(
                                            id=self._next_id("cle"),
                                            source=vs_id,
                                            target=tgt_id,
                                            relation_type=FunctionalRelationType.ROUTE,
                                            label="Route",
                                        )
                                    )

            # EF/RLS -> 目标服务（RateLimit 影响）
            if rel.get("rateLimit"):
                ef_id = f"cp_{svc}_EF"
                rls_id = f"cp_{svc}_RLS"
                # 限流通常作用于当前服务或上游
                self.graph.cross_layer_edges.append(
                    CrossLayerEdge(
                        id=self._next_id("cle"),
                        source=ef_id,
                        target=f"cp_svc_{svc}",
                        relation_type=FunctionalRelationType.RATE_LIMIT,
                        label="RateLimit",
                    )
                )
                self.graph.cross_layer_edges.append(
                    CrossLayerEdge(
                        id=self._next_id("cle"),
                        source=rls_id,
                        target=f"cp_svc_{svc}",
                        relation_type=FunctionalRelationType.RATE_LIMIT,
                        label="RateLimit",
                    )
                )

    def _add_metadata(self):
        """添加图元数据"""
        self.graph.metadata = {
            "model": "three_layer",
            "layer1": {
                "nodes": len(self.graph.layer1_nodes),
                "edges": len(self.graph.layer1_edges),
            },
            "layer2": {
                "nodes": len(self.graph.layer2_nodes),
                "edges": len(self.graph.layer2_edges),
            },
            "layer3": {
                "nodes": len(self.graph.layer3_nodes),
                "edges": len(self.graph.layer3_edges),
            },
            "cross_layer_edges": len(self.graph.cross_layer_edges),
            "issue_count": len(self.issues),
            "legend": {
                "layer1": "控制面/数据面/一致性检查器",
                "layer2": "服务与子服务、功能关系",
                "layer3": "配置资源(DR/VS/EF/RLS/SE)及依赖",
                "cross_layer": "配置→服务（服务间依赖）",
            },
        }

    def to_d3_json(self) -> Dict[str, Any]:
        """转换为 D3.js 兼容的 JSON 格式"""
        nodes = []
        edges = []

        def _get_service_name(n) -> Optional[str]:
            """从节点推导服务名，用于分组"""
            if hasattr(n, "service_name") and n.service_name:
                return n.service_name
            nid = getattr(n, "id", str(n))
            if nid.startswith("cp_svc_") and "_" in nid[7:]:
                return nid[7:].rsplit("_", 1)[0]  # cp_svc_reviews_v1 -> reviews
            if nid.startswith("cp_svc_"):
                return nid[7:]  # cp_svc_reviews -> reviews
            if nid.startswith("dp_envoy_"):
                return nid[9:]
            if nid.startswith("dp_pod_") and "_" in nid[7:]:
                return nid[7:].rsplit("_", 1)[0]  # dp_pod_reviews_v1 -> reviews
            if nid.startswith("cp_") and "_" in nid[3:]:
                return nid.split("_")[1]  # cp_reviews_DR -> reviews
            if nid.startswith("dp_") and "_" in nid[3:]:
                return nid.split("_")[1]  # dp_reviews_route -> reviews
            return None

        def add_node(n, layer: str, **extra):
            node = {
                "id": n.id,
                "label": getattr(n, "label", n.id),
                "layer": layer,
                **extra,
            }
            if hasattr(n, "plane_type"):
                node["plane_type"] = n.plane_type.value if hasattr(n.plane_type, "value") else str(n.plane_type)
            if hasattr(n, "node_type"):
                node["node_type"] = n.node_type
            if hasattr(n, "resource_type"):
                node["resource_type"] = n.resource_type.value if hasattr(n.resource_type, "value") else str(n.resource_type)
            if getattr(n, "namespace", None):
                node["namespace"] = n.namespace
            if getattr(n, "config_name", None):
                node["config_name"] = n.config_name
            svc = _get_service_name(n)
            if svc:
                node["service_name"] = svc
            nodes.append(node)

        def add_edge(e, layer: str, **extra):
            edge = {
                "id": e.id,
                "source": e.source,
                "target": e.target,
                "layer": layer,
                **extra,
            }
            if hasattr(e, "relation_type"):
                edge["relation_type"] = e.relation_type.value if hasattr(e.relation_type, "value") else str(e.relation_type)
            if hasattr(e, "match_type"):
                edge["match_type"] = e.match_type.value if hasattr(e.match_type, "value") else str(e.match_type)
            if getattr(e, "label", None):
                edge["label"] = e.label
            if getattr(e, "weight", None) is not None:
                edge["weight"] = e.weight
            if getattr(e, "role", None):
                edge["role"] = e.role
            edges.append(edge)

        for n in self.graph.layer1_nodes:
            add_node(n, "layer1", shape="rectangle")
        for n in self.graph.layer2_nodes:
            add_node(n, "layer2", shape="hexagon" if n.node_type == "service" else "rect")
        for n in self.graph.layer3_nodes:
            add_node(n, "layer3", shape="rect")

        for e in self.graph.layer1_edges:
            add_edge(e, "layer1", style="dashed")
        for e in self.graph.layer2_edges:
            add_edge(e, "layer2", style="solid")
        for e in self.graph.layer3_edges:
            add_edge(e, "layer3", style="solid")
        for e in self.graph.cross_layer_edges:
            add_edge(e, "cross_layer", style="solid")

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": self.graph.metadata,
            "issues": self._attach_issues(nodes, edges),
            "layers": [
                {"id": "layer1", "name": "数据面/控制面全局", "description": "边为一致/不一致匹配内容"},
                {"id": "layer2", "name": "服务关系层", "description": "节点为服务与子服务，边为服务间功能关系"},
                {"id": "layer3", "name": "配置关系层", "description": "节点为资源空间，边为配置资源依赖关系"},
            ],
        }

    _ISSUE_TITLES = {
        "missing_subset": "VS 引用不存在的 subset",
        "gateway_unmatched": "Gateway 未匹配",
        "gateway_selector_empty": "Gateway 选择器为空",
        "gateway_selector_conflict": "Gateway 选择器冲突",
        "route_priority_conflict": "路由优先级冲突",
        "alignment_timeout": "超时配置不一致",
        "alignment_discrete": "控制面/数据面语义不一致",
        "traffic_split_drift": "流量权重偏离",
        "weight_error": "流量权重错误",
    }

    def _issue_node_ids(self, issue: Dict[str, Any], node_ids: set) -> List[str]:
        found: List[str] = []
        svc = (issue.get("service") or "").strip()
        vs_name = (issue.get("virtualservice") or "").strip()
        gw = (issue.get("gateway") or "").strip()
        itype = str(issue.get("type") or "")

        def add(nid: str):
            if nid and nid in node_ids and nid not in found:
                found.append(nid)

        if svc:
            add(f"cp_svc_{svc}")
            add(f"dp_envoy_{svc}")
            add(f"cp_{svc}_DR")
            add(f"cp_{svc}_VS_{svc}")
            add(f"dp_{svc}_route")
            for key in ("expected", "observed"):
                mapping = issue.get(key) if isinstance(issue.get(key), dict) else {}
                for sub in mapping:
                    add(f"cp_svc_{svc}_{sub}")
                    add(f"dp_pod_{svc}_{sub}")
        if vs_name:
            add(f"cp_{svc}_VS_{vs_name}" if svc else "")
            for nid in node_ids:
                if vs_name and vs_name in nid and ("_VS" in nid or nid.startswith("cp_")):
                    add(nid)
        if "gateway" in itype or gw:
            add("istio-gateway")
            add("cp_svc_istio-ingressgateway")
        for n in self.graph.layer3_nodes:
            if svc and getattr(n, "service_name", "") == svc:
                add(n.id)
            if vs_name and (getattr(n, "config_name", "") == vs_name or vs_name in n.id):
                add(n.id)
        return found

    def _attach_issues(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        node_ids = {n["id"] for n in nodes}
        by_id = {n["id"]: n for n in nodes}
        records: List[Dict[str, Any]] = []
        affected: set = set()
        for i, raw in enumerate(self.issues):
            if not isinstance(raw, dict):
                continue
            itype = str(raw.get("type") or "unknown")
            targets = self._issue_node_ids(raw, node_ids)
            if not targets and raw.get("node_ids"):
                targets = [nid for nid in raw["node_ids"] if nid in node_ids]
            rec = {
                "id": raw.get("id") or f"issue_{i + 1}",
                "type": itype,
                "severity": raw.get("severity") or "medium",
                "title": raw.get("title") or self._ISSUE_TITLES.get(itype, itype.replace("_", " ")),
                "description": raw.get("description") or "",
                "service": raw.get("service"),
                "node_ids": targets,
                "expected": raw.get("expected"),
                "observed": raw.get("observed"),
            }
            records.append(rec)
            affected.update(targets)
            snippet = {
                "id": rec["id"],
                "type": rec["type"],
                "severity": rec["severity"],
                "title": rec["title"],
                "description": rec["description"],
            }
            for nid in targets:
                node = by_id.get(nid)
                if not node:
                    continue
                node["has_issue"] = True
                node.setdefault("issues", []).append(snippet)

        if records:
            for edge in edges:
                if edge.get("role") == "observed":
                    edge["match_type"] = "inconsistent"
                if edge.get("layer") == "layer1":
                    edge["match_type"] = "inconsistent"
        return records

    def save_to_file(self, filepath: str):
        """保存图数据到 JSON 文件"""
        import os
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        data = self.to_d3_json()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"三层图数据已保存到: {filepath}")
