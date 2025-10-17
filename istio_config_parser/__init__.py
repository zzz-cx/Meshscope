# Istio Config Parser Package
"""
Istio配置解析器包
用于解析和分析Istio配置文件的工具集合
"""

from .main_parser import parse_control_plane_from_dir, parse_data_plane_from_dir

__version__ = "1.0.0"
__author__ = "Istio Config Parser Team"

__all__ = [
    "parse_control_plane_from_dir",
    "parse_data_plane_from_dir"
]
