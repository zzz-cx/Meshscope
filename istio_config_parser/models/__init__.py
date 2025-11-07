"""
Istio配置解析器数据模型
"""

# 导入数据结构（Legacy支持）
from .data_structures import (
    ControlPlaneResult,
    DataPlaneResult,
    BaseService,
    ServiceRelation
)

# 导入新架构模型
from .function_models import (
    FunctionModel,
    FunctionType,
    PlaneType,
    RoutingFunctionModel,
    CircuitBreakerFunctionModel,
    RateLimitFunctionModel,
    TrafficShiftingFunctionModel
)

from .alignment_models import (
    AlignedFunctionPair,
    ModelAligner,
    AlignmentResult
)

from .ir_models import (
    FunctionIR,
    ServiceIR,
    SystemIR,
    IRBuilder,
    SimpleIR,
    SimpleIRConverter
)

__all__ = [
    # Legacy数据结构
    'ControlPlaneResult',
    'DataPlaneResult',
    'BaseService',
    'ServiceRelation',
    
    # 新架构模型
    'FunctionModel',
    'FunctionType',
    'PlaneType',
    'RoutingFunctionModel',
    'CircuitBreakerFunctionModel',
    'RateLimitFunctionModel',
    'TrafficShiftingFunctionModel',
    
    # 对齐模型
    'AlignedFunctionPair',
    'ModelAligner',
    'AlignmentResult',
    
    # IR模型
    'FunctionIR',
    'ServiceIR',
    'SystemIR',
    'IRBuilder',
    
    # 简化IR模型
    'SimpleIR',
    'SimpleIRConverter'
]
