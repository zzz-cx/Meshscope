"""
三层空间配置依赖图数据模型

基于三层空间模型构建服务依赖图：
- 第一层：数据面/控制面全局，边为一致/不一致匹配内容
- 第二层：服务关系层，节点为服务与子服务，边为服务间功能关系
- 第三层：配置关系层，节点为资源空间(DR/VS/EF/RLS/SE)，边为配置资源依赖关系
- 跨层：第三层→第二层 = 服务间依赖；第三层内部 = 服务内依赖
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum


class LayerType(Enum):
    """层级类型"""
    LAYER1_GLOBAL = "layer1_global"
    LAYER2_SERVICE = "layer2_service"
    LAYER3_CONFIG = "layer3_config"


class PlaneType(Enum):
    """平面类型"""
    CONTROL_PLANE = "control_plane"
    DATA_PLANE = "data_plane"
    CONSISTENCY_CHECKER = "consistency_checker"


class ConsistencyMatchType(Enum):
    """一致/不一致匹配类型"""
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class FunctionalRelationType(Enum):
    """服务间功能关系类型"""
    ROUTE = "route"
    RATE_LIMIT = "rate_limit"
    TRAFFIC_SPLIT = "traffic_split"
    CIRCUIT_BREAKER = "circuit_breaker"
    GATEWAY = "gateway"


class ConfigResourceType(Enum):
    """配置资源类型"""
    VS = "VS"   # VirtualService
    DR = "DR"   # DestinationRule
    EF = "EF"   # EnvoyFilter
    RLS = "RLS"  # RateLimitService
    SE = "SE"   # ServiceEntry


@dataclass
class Layer1Node:
    """第一层节点：控制面/数据面/一致性检查器"""
    id: str
    label: str
    plane_type: PlaneType
    shape: str = "rectangle"


@dataclass
class Layer1Edge:
    """第一层边：一致/不一致匹配内容"""
    id: str
    source: str  # 控制面配置ID 或 数据面配置ID
    target: str  # consistency_checker
    match_type: ConsistencyMatchType
    label: Optional[str] = None
    config_refs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Layer2Node:
    """第二层节点：服务与子服务"""
    id: str
    label: str
    plane_type: PlaneType
    parent_service: Optional[str] = None  # 子服务时指向父服务
    node_type: str = "service"  # service, subset, envoy, pod, rls_server
    namespace: str = "default"


@dataclass
class Layer2Edge:
    """第二层边：服务间功能关系"""
    id: str
    source: str
    target: str
    relation_type: FunctionalRelationType
    label: Optional[str] = None
    weight: Optional[int] = None
    role: Optional[str] = None  # expected | observed，动态核对流量时使用


@dataclass
class Layer3Node:
    """第三层节点：配置资源"""
    id: str
    label: str
    resource_type: ConfigResourceType
    service_name: str
    plane_type: PlaneType
    config_name: Optional[str] = None
    namespace: str = "default"


@dataclass
class Layer3Edge:
    """第三层边：配置资源依赖（服务内）"""
    id: str
    source: str
    target: str
    label: Optional[str] = None
    dependency_type: str = "references"  # references, subnet, etc.


@dataclass
class CrossLayerEdge:
    """跨层边：第三层→第二层（服务间依赖）"""
    id: str
    source: str  # Layer3 资源ID
    target: str  # Layer2 服务ID
    relation_type: FunctionalRelationType
    label: Optional[str] = None


@dataclass
class ThreeLayerGraph:
    """三层图完整数据结构"""
    layer1_nodes: List[Layer1Node] = field(default_factory=list)
    layer1_edges: List[Layer1Edge] = field(default_factory=list)
    layer2_nodes: List[Layer2Node] = field(default_factory=list)
    layer2_edges: List[Layer2Edge] = field(default_factory=list)
    layer3_nodes: List[Layer3Node] = field(default_factory=list)
    layer3_edges: List[Layer3Edge] = field(default_factory=list)
    cross_layer_edges: List[CrossLayerEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
