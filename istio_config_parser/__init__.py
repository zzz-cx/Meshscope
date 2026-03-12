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

# Legacy 格式解析（内部使用 UnifiedParser）
try:
    from .main_parser import parse_control_plane_from_dir, parse_data_plane_from_dir, parse_to_legacy_format
    LEGACY_API_AVAILABLE = True
except ImportError:
    LEGACY_API_AVAILABLE = False

__version__ = "1.0.0"
__author__ = "Istio Config Parser Team"

__all__ = []
if NEW_VERSION_AVAILABLE:
    __all__.extend(["parse_unified_from_dir", "parse_and_export_models", "SystemIR", "SimpleIRConverter"])
if LEGACY_API_AVAILABLE:
    __all__.extend(["parse_control_plane_from_dir", "parse_data_plane_from_dir", "parse_to_legacy_format"])
