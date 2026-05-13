"""可视化模块"""

from consistency_checker.visualizer.graph_generator import GraphGenerator
from consistency_checker.visualizer.report_generator import ComprehensiveReportGenerator
try:
    from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator  # type: ignore
    _THREE_LAYER_AVAILABLE = True
except Exception:  # pragma: no cover
    _THREE_LAYER_AVAILABLE = False

__all__ = [
    "GraphGenerator",
    "ComprehensiveReportGenerator",
]

if _THREE_LAYER_AVAILABLE:
    __all__.append("ThreeLayerGraphGenerator")


