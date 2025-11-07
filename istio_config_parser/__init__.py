# Istio Config Parser Package
"""
Istio配置解析器包
用于解析和分析Istio配置文件的工具集合
"""

# 尝试导入新版本的功能
try:
    from .main_parser import parse_unified_from_dir, parse_and_export_models
    from .models.ir_models import SystemIR, SimpleIRConverter
    NEW_VERSION_AVAILABLE = True
except ImportError:
    NEW_VERSION_AVAILABLE = False

# 尝试导入旧版本的解析器（保留向后兼容）
try:
    from .traffic_management.service_parser import ServiceParser
    from .traffic_management.route_parser import RouteParser
    from .traffic_management.canary_parser import CanaryParser
    from .traffic_management.ratelimit_parser import RateLimitParser
    from .traffic_management.circuit_breaker_parser import CircuitBreakerParser
    LEGACY_AVAILABLE = True
except ImportError:
    LEGACY_AVAILABLE = False

__version__ = "1.0.0"
__author__ = "Istio Config Parser Team"

__all__ = []
if NEW_VERSION_AVAILABLE:
    __all__.extend(["parse_unified_from_dir", "parse_and_export_models", "SystemIR", "SimpleIRConverter"])
if LEGACY_AVAILABLE:
    __all__.extend(["ServiceParser", "RouteParser", "CanaryParser", "RateLimitParser", "CircuitBreakerParser"])
