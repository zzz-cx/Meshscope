"""数据模型模块"""

from consistency_checker.models.data_models import (
    StaticPolicy,
    DynamicBehavior,
    ConsistencyResult,
    VerificationReport,
    ServiceNode,
    ConfigEdge,
    InconsistencyAnnotation
)
try:
    from consistency_checker.models.three_layer_graph_models import (  # type: ignore
        ThreeLayerGraph,
        Layer1Node,
        Layer2Node,
        Layer3Node,
        PlaneType,
        ConfigResourceType,
        FunctionalRelationType,
    )
    _THREE_LAYER_AVAILABLE = True
except Exception:  # pragma: no cover
    _THREE_LAYER_AVAILABLE = False

__all__ = [
    "StaticPolicy",
    "DynamicBehavior",
    "ConsistencyResult",
    "VerificationReport",
    "ServiceNode",
    "ConfigEdge",
    "InconsistencyAnnotation",
]

if _THREE_LAYER_AVAILABLE:
    __all__.extend([
        "ThreeLayerGraph",
        "Layer1Node",
        "Layer2Node",
        "Layer3Node",
        "PlaneType",
        "ConfigResourceType",
        "FunctionalRelationType",
    ])


