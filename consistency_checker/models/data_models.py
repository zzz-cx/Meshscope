"""
一致性验证数据模型

定义静态分析、动态测试、一致性检查等模块使用的统一数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime


class PolicyType(Enum):
    """策略类型"""
    ROUTING = "routing"
    TRAFFIC_SPLIT = "traffic_split"
    RETRY = "retry"
    TIMEOUT = "timeout"
    CIRCUIT_BREAKER = "circuit_breaker"
    FAULT_INJECTION = "fault_injection"
    RATE_LIMIT = "rate_limit"
    AUTHORIZATION = "authorization"
    

class ConsistencyStatus(Enum):
    """一致性状态"""
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    

class SeverityLevel(Enum):
    """严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class StaticPolicy:
    """静态策略（从控制平面配置解析）"""
    policy_id: str
    policy_type: PolicyType
    source_service: str
    target_service: str
    namespace: str
    
    # 策略详情
    config_name: str  # VirtualService/DestinationRule等名称
    config_type: str  # 配置类型
    rules: Dict[str, Any]  # 具体规则内容
    
    # 范围信息
    applies_to: List[str] = field(default_factory=list)  # 适用的服务/子集
    match_conditions: Dict[str, Any] = field(default_factory=dict)  # 匹配条件
    
    # 元数据
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    

@dataclass
class DynamicBehavior:
    """动态行为（从运行时数据收集）"""
    test_case_id: str
    policy_type: PolicyType
    source_service: str
    target_service: str
    
    # 测试参数
    test_params: Dict[str, Any] = field(default_factory=dict)
    expected_behavior: Dict[str, Any] = field(default_factory=dict)
    
    # 实际行为
    actual_behavior: Dict[str, Any] = field(default_factory=dict)
    http_results: Dict[str, Any] = field(default_factory=dict)
    
    # 验证结果
    is_verified: bool = False
    verification_details: Dict[str, Any] = field(default_factory=dict)
    
    # 时间信息
    executed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None


@dataclass
class InconsistencyAnnotation:
    """不一致性标注"""
    inconsistency_id: str
    inconsistency_type: str  # scope_mismatch, behavior_deviation, policy_ineffective等
    severity: SeverityLevel
    
    description: str
    affected_policies: List[str]
    affected_services: List[str]
    
    # 静态和动态对比
    static_expectation: Dict[str, Any] = field(default_factory=dict)
    dynamic_observation: Dict[str, Any] = field(default_factory=dict)
    
    # 根因分析
    root_cause: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    
    # 影响范围
    impact_scope: List[str] = field(default_factory=list)
    

@dataclass
class ConsistencyResult:
    """一致性检查结果"""
    result_id: str
    overall_status: ConsistencyStatus
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 策略对比
    static_policies: List[StaticPolicy] = field(default_factory=list)
    dynamic_behaviors: List[DynamicBehavior] = field(default_factory=list)
    
    # 一致性分析
    consistent_policies: List[str] = field(default_factory=list)
    inconsistent_policies: List[str] = field(default_factory=list)
    unverified_policies: List[str] = field(default_factory=list)
    
    # 不一致性详情
    inconsistencies: List[InconsistencyAnnotation] = field(default_factory=list)
    
    # 统计信息
    total_policies: int = 0
    verified_policies: int = 0
    consistency_rate: float = 0.0
    
    # 汇总
    summary: Dict[str, Any] = field(default_factory=dict)
    

@dataclass
class ServiceNode:
    """服务节点（用于图可视化）"""
    service_name: str
    namespace: str
    node_type: str  # service, gateway, external
    
    # 节点属性
    labels: Dict[str, str] = field(default_factory=dict)
    subsets: List[str] = field(default_factory=list)
    
    # 配置状态
    has_virtualservice: bool = False
    has_destinationrule: bool = False
    has_policies: List[str] = field(default_factory=list)
    
    # 一致性状态
    consistency_status: ConsistencyStatus = ConsistencyStatus.UNKNOWN
    inconsistencies: List[str] = field(default_factory=list)
    

@dataclass
class ConfigEdge:
    """配置边（用于图可视化）"""
    edge_id: str
    source: str
    target: str
    edge_type: str  # route, traffic_split, policy
    
    # 边属性
    weight: Optional[int] = None
    protocol: str = "http"
    policies: List[str] = field(default_factory=list)
    
    # 一致性状态
    consistency_status: ConsistencyStatus = ConsistencyStatus.UNKNOWN
    inconsistencies: List[str] = field(default_factory=list)
    
    # 显示属性
    label: Optional[str] = None
    color: Optional[str] = None
    

@dataclass
class VerificationReport:
    """综合验证报告"""
    report_id: str
    title: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 执行信息
    namespace: str = "default"
    executed_by: str = "system"
    
    # 静态分析结果
    static_analysis: Dict[str, Any] = field(default_factory=dict)
    
    # 动态测试结果
    dynamic_testing: Dict[str, Any] = field(default_factory=dict)
    
    # 一致性检查结果
    consistency_check: Optional[ConsistencyResult] = None
    
    # 图数据
    graph_nodes: List[ServiceNode] = field(default_factory=list)
    graph_edges: List[ConfigEdge] = field(default_factory=list)
    
    # 报告内容
    executive_summary: str = ""
    detailed_findings: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    # 附加信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于JSON序列化）"""
        return {
            "report_id": self.report_id,
            "title": self.title,
            "timestamp": self.timestamp.isoformat(),
            "namespace": self.namespace,
            "executed_by": self.executed_by,
            "static_analysis": self.static_analysis,
            "dynamic_testing": self.dynamic_testing,
            "consistency_check": {
                "overall_status": self.consistency_check.overall_status.value if self.consistency_check else "unknown",
                "total_policies": self.consistency_check.total_policies if self.consistency_check else 0,
                "verified_policies": self.consistency_check.verified_policies if self.consistency_check else 0,
                "consistency_rate": self.consistency_check.consistency_rate if self.consistency_check else 0.0,
                "inconsistencies": [
                    {
                        "id": inc.inconsistency_id,
                        "type": inc.inconsistency_type,
                        "severity": inc.severity.value,
                        "description": inc.description,
                        "affected_services": inc.affected_services
                    }
                    for inc in (self.consistency_check.inconsistencies if self.consistency_check else [])
                ]
            },
            "graph_data": {
                "nodes": [
                    {
                        "id": node.service_name,
                        "namespace": node.namespace,
                        "type": node.node_type,
                        "subsets": node.subsets,
                        "consistency_status": node.consistency_status.value
                    }
                    for node in self.graph_nodes
                ],
                "edges": [
                    {
                        "id": edge.edge_id,
                        "source": edge.source,
                        "target": edge.target,
                        "type": edge.edge_type,
                        "weight": edge.weight,
                        "consistency_status": edge.consistency_status.value
                    }
                    for edge in self.graph_edges
                ]
            },
            "executive_summary": self.executive_summary,
            "detailed_findings": self.detailed_findings,
            "recommendations": self.recommendations,
            "metadata": self.metadata
        }


