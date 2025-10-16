"""
图谱生成器

生成服务拓扑图的JSON数据，用于D3.js可视化
"""

import json
import logging
from typing import Dict, List, Optional, Any

from consistency_checker.models.data_models import (
    ServiceNode,
    ConfigEdge,
    ConsistencyResult,
    ConsistencyStatus,
    SeverityLevel
)

logger = logging.getLogger(__name__)


class GraphGenerator:
    """服务拓扑图生成器"""
    
    def __init__(
        self,
        service_nodes: List[ServiceNode],
        config_edges: List[ConfigEdge],
        consistency_result: Optional[ConsistencyResult] = None
    ):
        """
        初始化图生成器
        
        Args:
            service_nodes: 服务节点列表
            config_edges: 配置边列表
            consistency_result: 一致性检查结果
        """
        self.service_nodes = service_nodes
        self.config_edges = config_edges
        self.consistency_result = consistency_result
        
        self.graph_data = {
            "nodes": [],
            "edges": [],
            "metadata": {}
        }
        
    def generate(self) -> Dict[str, Any]:
        """
        生成图数据
        
        Returns:
            包含节点和边的图数据
        """
        logger.info("生成服务拓扑图数据")
        
        # 1. 处理节点
        self._process_nodes()
        logger.info(f"  ✓ 处理节点: {len(self.graph_data['nodes'])} 个")
        
        # 2. 处理边
        self._process_edges()
        logger.info(f"  ✓ 处理边: {len(self.graph_data['edges'])} 条")
        
        # 3. 添加一致性标注
        if self.consistency_result:
            self._annotate_inconsistencies()
            logger.info(f"  ✓ 标注不一致性: {len(self.consistency_result.inconsistencies)} 个")
        
        # 4. 添加元数据
        self._add_metadata()
        
        return self.graph_data
    
    def _process_nodes(self):
        """处理服务节点"""
        for node in self.service_nodes:
            graph_node = {
                "id": node.service_name,
                "label": node.service_name,
                "namespace": node.namespace,
                "type": node.node_type,
                "subsets": node.subsets,
                
                # 配置状态
                "hasVirtualService": node.has_virtualservice,
                "hasDestinationRule": node.has_destinationrule,
                "policies": node.has_policies,
                
                # 一致性状态
                "consistencyStatus": node.consistency_status.value,
                "inconsistencies": node.inconsistencies,
                
                # 可视化属性
                "color": self._get_node_color(node),
                "size": self._get_node_size(node),
                "shape": self._get_node_shape(node)
            }
            
            self.graph_data["nodes"].append(graph_node)
    
    def _process_edges(self):
        """处理配置边"""
        for edge in self.config_edges:
            graph_edge = {
                "id": edge.edge_id,
                "source": edge.source,
                "target": edge.target,
                "type": edge.edge_type,
                "label": edge.label or "",
                
                # 边属性
                "weight": edge.weight,
                "protocol": edge.protocol,
                "policies": edge.policies,
                
                # 一致性状态
                "consistencyStatus": edge.consistency_status.value,
                "inconsistencies": edge.inconsistencies,
                
                # 可视化属性
                "color": self._get_edge_color(edge),
                "width": self._get_edge_width(edge),
                "style": self._get_edge_style(edge)
            }
            
            self.graph_data["edges"].append(graph_edge)
    
    def _annotate_inconsistencies(self):
        """标注不一致性到节点和边上"""
        if not self.consistency_result:
            return
        
        # 为每个不一致性创建标注
        for inc in self.consistency_result.inconsistencies:
            # 更新受影响的节点
            for service in inc.affected_services:
                for node in self.graph_data["nodes"]:
                    if node["id"] == service:
                        node["inconsistencies"].append({
                            "id": inc.inconsistency_id,
                            "type": inc.inconsistency_type,
                            "severity": inc.severity.value,
                            "description": inc.description
                        })
                        
                        # 更新节点颜色以反映最严重的问题
                        if inc.severity == SeverityLevel.CRITICAL:
                            node["color"] = "#d32f2f"  # 红色
                            node["consistencyStatus"] = ConsistencyStatus.INCONSISTENT.value
                        elif inc.severity == SeverityLevel.HIGH and node["color"] != "#d32f2f":
                            node["color"] = "#f57c00"  # 橙色
                            node["consistencyStatus"] = ConsistencyStatus.PARTIAL.value
            
            # 更新受影响的边
            for policy_id in inc.affected_policies:
                for edge in self.graph_data["edges"]:
                    if policy_id in edge.get("policies", []):
                        edge["inconsistencies"].append({
                            "id": inc.inconsistency_id,
                            "type": inc.inconsistency_type,
                            "severity": inc.severity.value,
                            "description": inc.description
                        })
                        
                        # 更新边颜色
                        if inc.severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH]:
                            edge["color"] = "#d32f2f"
                            edge["style"] = "dashed"
                            edge["consistencyStatus"] = ConsistencyStatus.INCONSISTENT.value
    
    def _add_metadata(self):
        """添加图元数据"""
        self.graph_data["metadata"] = {
            "totalNodes": len(self.graph_data["nodes"]),
            "totalEdges": len(self.graph_data["edges"]),
            "consistencyStatus": self.consistency_result.overall_status.value if self.consistency_result else "unknown",
            "totalInconsistencies": len(self.consistency_result.inconsistencies) if self.consistency_result else 0,
            "legend": {
                "nodeColors": {
                    "consistent": {"color": "#4caf50", "label": "一致"},
                    "partial": {"color": "#f57c00", "label": "部分一致"},
                    "inconsistent": {"color": "#d32f2f", "label": "不一致"},
                    "unknown": {"color": "#9e9e9e", "label": "未知"}
                },
                "edgeTypes": {
                    "route": {"label": "路由"},
                    "traffic_split": {"label": "流量分配"},
                    "gateway": {"label": "网关"}
                }
            }
        }
    
    def _get_node_color(self, node: ServiceNode) -> str:
        """获取节点颜色"""
        status_colors = {
            ConsistencyStatus.CONSISTENT: "#4caf50",  # 绿色
            ConsistencyStatus.PARTIAL: "#f57c00",     # 橙色
            ConsistencyStatus.INCONSISTENT: "#d32f2f",  # 红色
            ConsistencyStatus.UNKNOWN: "#9e9e9e"      # 灰色
        }
        return status_colors.get(node.consistency_status, "#9e9e9e")
    
    def _get_node_size(self, node: ServiceNode) -> int:
        """获取节点大小（基于策略数量）"""
        base_size = 20
        policy_count = len(node.has_policies)
        return base_size + policy_count * 5
    
    def _get_node_shape(self, node: ServiceNode) -> str:
        """获取节点形状"""
        if node.node_type == "gateway":
            return "diamond"
        elif node.node_type == "external":
            return "square"
        else:
            return "circle"
    
    def _get_edge_color(self, edge: ConfigEdge) -> str:
        """获取边颜色"""
        status_colors = {
            ConsistencyStatus.CONSISTENT: "#4caf50",
            ConsistencyStatus.PARTIAL: "#f57c00",
            ConsistencyStatus.INCONSISTENT: "#d32f2f",
            ConsistencyStatus.UNKNOWN: "#757575"
        }
        return status_colors.get(edge.consistency_status, "#757575")
    
    def _get_edge_width(self, edge: ConfigEdge) -> int:
        """获取边宽度（基于流量权重）"""
        if edge.weight:
            return max(1, int(edge.weight / 20))
        return 2
    
    def _get_edge_style(self, edge: ConfigEdge) -> str:
        """获取边样式"""
        if edge.consistency_status == ConsistencyStatus.INCONSISTENT:
            return "dashed"
        elif edge.edge_type == "gateway":
            return "dotted"
        else:
            return "solid"
    
    def get_graph_data(self) -> Dict[str, Any]:
        """获取生成的图数据"""
        return self.graph_data
    
    def save_to_file(self, filepath: str):
        """保存图数据到文件"""
        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.graph_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"图数据已保存到: {filepath}")


