"""
静态分析器

负责解析和分析控制平面和数据平面配置，提取策略定义和服务关系
"""

import os
import sys
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from istio_config_parser.main_parser import (
    parse_control_plane_from_dir,
    parse_data_plane_from_dir
)
from consistency_checker.models.data_models import (
    StaticPolicy,
    PolicyType,
    ServiceNode,
    ConfigEdge,
    ConsistencyStatus
)
from consistency_checker.config import get_config

logger = logging.getLogger(__name__)


class StaticAnalyzer:
    """静态配置分析器"""
    
    def __init__(self, config_dir: Optional[str] = None, namespace: Optional[str] = None):
        """
        初始化静态分析器
        
        Args:
            config_dir: 配置目录路径
            namespace: Kubernetes命名空间
        """
        self.config = get_config()
        self.config_dir = config_dir or self.config.control_plane_config_dir
        self.namespace = namespace or self.config.namespace
        
        self.control_plane_data = None
        self.data_plane_data = None
        self.static_policies: List[StaticPolicy] = []
        self.service_nodes: List[ServiceNode] = []
        self.config_edges: List[ConfigEdge] = []
        
    def analyze(self) -> Dict[str, Any]:
        """
        执行静态分析
        
        Returns:
            包含策略、节点和边的分析结果
        """
        logger.info(f"开始静态分析: 配置目录={self.config_dir}, 命名空间={self.namespace}")
        
        # 1. 解析控制平面配置
        self.control_plane_data = parse_control_plane_from_dir(
            self.config_dir,
            self.namespace
        )
        logger.info(f"✓ 解析控制平面配置完成")
        
        # 2. 解析数据平面配置
        self.data_plane_data = parse_data_plane_from_dir(self.config_dir)
        logger.info(f"✓ 解析数据平面配置完成")
        
        # 3. 提取静态策略
        self._extract_static_policies()
        logger.info(f"✓ 提取静态策略: {len(self.static_policies)} 个")
        
        # 4. 构建服务图
        self._build_service_graph()
        logger.info(f"✓ 构建服务图: {len(self.service_nodes)} 个节点, {len(self.config_edges)} 条边")
        
        # 5. 检测控制平面和数据平面一致性
        consistency_issues = self._check_plane_consistency()
        logger.info(f"✓ 平面一致性检查: 发现 {len(consistency_issues)} 个问题")
        
        return {
            "control_plane": self.control_plane_data,
            "data_plane": self.data_plane_data,
            "static_policies": self.static_policies,
            "service_nodes": self.service_nodes,
            "config_edges": self.config_edges,
            "plane_consistency_issues": consistency_issues,
            "summary": {
                "total_services": len(self.service_nodes),
                "total_policies": len(self.static_policies),
                "total_edges": len(self.config_edges),
                "has_inconsistencies": len(consistency_issues) > 0
            }
        }
    
    def _extract_static_policies(self):
        """从控制平面配置提取静态策略"""
        policy_id_counter = 1
        
        for service_name, relations in self.control_plane_data.get('serviceRelations', {}).items():
            # 提取VirtualService路由策略
            for vs in relations.get('incomingVirtualServices', []):
                for idx, rule in enumerate(vs.get('rules', [])):
                    policy = StaticPolicy(
                        policy_id=f"policy_{policy_id_counter:04d}",
                        policy_type=PolicyType.ROUTING,
                        source_service="*",  # VirtualService通常接受来自任意源的流量
                        target_service=service_name,
                        namespace=vs.get('namespace', self.namespace),
                        config_name=vs.get('name', 'unknown'),
                        config_type="VirtualService",
                        rules=rule,
                        match_conditions=rule.get('match', {}),
                        created_at=datetime.now()
                    )
                    self.static_policies.append(policy)
                    policy_id_counter += 1
            
            # 提取流量分配策略
            weights = relations.get('weights', {})
            if weights:
                policy = StaticPolicy(
                    policy_id=f"policy_{policy_id_counter:04d}",
                    policy_type=PolicyType.TRAFFIC_SPLIT,
                    source_service="*",
                    target_service=service_name,
                    namespace=self.namespace,
                    config_name=f"{service_name}-traffic-split",
                    config_type="DestinationRule",
                    rules={"weights": weights},
                    applies_to=list(weights.keys()),
                    created_at=datetime.now()
                )
                self.static_policies.append(policy)
                policy_id_counter += 1
            
            # 提取熔断策略
            circuit_breaker = relations.get('circuitBreaker', {})
            if circuit_breaker:
                # 全局熔断策略
                if circuit_breaker.get('global_'):
                    policy = StaticPolicy(
                        policy_id=f"policy_{policy_id_counter:04d}",
                        policy_type=PolicyType.CIRCUIT_BREAKER,
                        source_service="*",
                        target_service=service_name,
                        namespace=self.namespace,
                        config_name=f"{service_name}-circuit-breaker-global",
                        config_type="DestinationRule",
                        rules=circuit_breaker['global_'],
                        created_at=datetime.now()
                    )
                    self.static_policies.append(policy)
                    policy_id_counter += 1
                
                # 子集熔断策略
                for subset_name, subset_policy in circuit_breaker.get('subsets', {}).items():
                    if subset_policy:
                        policy = StaticPolicy(
                            policy_id=f"policy_{policy_id_counter:04d}",
                            policy_type=PolicyType.CIRCUIT_BREAKER,
                            source_service="*",
                            target_service=service_name,
                            namespace=self.namespace,
                            config_name=f"{service_name}-circuit-breaker-{subset_name}",
                            config_type="DestinationRule",
                            rules=subset_policy,
                            applies_to=[subset_name],
                            created_at=datetime.now()
                        )
                        self.static_policies.append(policy)
                        policy_id_counter += 1
            
            # 提取限流策略
            rate_limits = relations.get('rateLimit', [])
            for limit in rate_limits:
                policy = StaticPolicy(
                    policy_id=f"policy_{policy_id_counter:04d}",
                    policy_type=PolicyType.RATE_LIMIT,
                    source_service="*",
                    target_service=service_name,
                    namespace=self.namespace,
                    config_name=f"{service_name}-rate-limit",
                    config_type="EnvoyFilter",
                    rules=limit,
                    created_at=datetime.now()
                )
                self.static_policies.append(policy)
                policy_id_counter += 1
    
    def _build_service_graph(self):
        """构建服务拓扑图"""
        service_map = {}
        edge_id_counter = 1
        
        # 创建服务节点
        for service_name, relations in self.control_plane_data.get('serviceRelations', {}).items():
            subsets = [s['name'] for s in relations.get('subsets', [])]
            
            node = ServiceNode(
                service_name=service_name,
                namespace=self.namespace,
                node_type="service",
                subsets=subsets,
                has_virtualservice=len(relations.get('incomingVirtualServices', [])) > 0,
                has_destinationrule=len(subsets) > 0,
                has_policies=[p.policy_id for p in self.static_policies if p.target_service == service_name],
                consistency_status=ConsistencyStatus.UNKNOWN
            )
            self.service_nodes.append(node)
            service_map[service_name] = node
        
        # 创建配置边
        for service_name, relations in self.control_plane_data.get('serviceRelations', {}).items():
            # 从VirtualService提取路由边
            for vs in relations.get('incomingVirtualServices', []):
                for rule in vs.get('rules', []):
                    for route in rule.get('route', []):
                        target = route.get('destination', {}).get('host', '')
                        if target and target in service_map:
                            edge = ConfigEdge(
                                edge_id=f"edge_{edge_id_counter:04d}",
                                source=service_name,
                                target=target,
                                edge_type="route",
                                weight=route.get('weight'),
                                policies=[p.policy_id for p in self.static_policies 
                                         if p.source_service == service_name and p.target_service == target],
                                consistency_status=ConsistencyStatus.UNKNOWN,
                                label=f"{route.get('weight', 100)}%"
                            )
                            self.config_edges.append(edge)
                            edge_id_counter += 1
            
            # 从Gateway信息提取入口边
            for gateway in relations.get('gateways', []):
                edge = ConfigEdge(
                    edge_id=f"edge_{edge_id_counter:04d}",
                    source="istio-gateway",
                    target=service_name,
                    edge_type="gateway",
                    policies=[],
                    consistency_status=ConsistencyStatus.UNKNOWN,
                    label=gateway.get('name', 'gateway')
                )
                self.config_edges.append(edge)
                edge_id_counter += 1
    
    def _check_plane_consistency(self) -> List[Dict[str, Any]]:
        """检查控制平面和数据平面的一致性"""
        issues = []
        
        # 对比服务定义
        control_services = set(self.control_plane_data.get('serviceRelations', {}).keys())
        data_services = set(self.data_plane_data.get('serviceRelations', {}).keys())
        
        # 检查缺失的服务
        missing_in_data = control_services - data_services
        if missing_in_data:
            issues.append({
                "type": "missing_in_data_plane",
                "severity": "high",
                "services": list(missing_in_data),
                "description": f"控制平面定义的服务在数据平面中缺失: {missing_in_data}"
            })
        
        extra_in_data = data_services - control_services
        if extra_in_data:
            issues.append({
                "type": "extra_in_data_plane",
                "severity": "medium",
                "services": list(extra_in_data),
                "description": f"数据平面存在控制平面未定义的服务: {extra_in_data}"
            })
        
        # 对比路由配置
        for service in control_services & data_services:
            control_routes = self.control_plane_data['serviceRelations'][service]
            data_routes = self.data_plane_data['serviceRelations'].get(service, {})
            
            # 对比权重配置
            control_weights = control_routes.get('weights', {})
            data_weights = data_routes.get('weights', {})
            
            if control_weights != data_weights:
                issues.append({
                    "type": "weight_mismatch",
                    "severity": "high",
                    "service": service,
                    "control_plane": control_weights,
                    "data_plane": data_weights,
                    "description": f"服务 {service} 的流量权重配置不一致"
                })
        
        return issues
    
    def get_policy_by_id(self, policy_id: str) -> Optional[StaticPolicy]:
        """根据ID获取策略"""
        for policy in self.static_policies:
            if policy.policy_id == policy_id:
                return policy
        return None
    
    def get_policies_by_service(self, service_name: str) -> List[StaticPolicy]:
        """获取服务相关的所有策略"""
        return [p for p in self.static_policies if p.target_service == service_name]


