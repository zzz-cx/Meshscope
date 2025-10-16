"""
Istio一致性验证和可视化模块

该模块负责：
1. 整合静态分析和动态测试的结果
2. 进行一致性检测和偏差分析
3. 生成可视化图谱和综合报告
"""

__version__ = "1.0.0"

from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.core.orchestrator import Pipeline
from consistency_checker.models.data_models import (
    StaticPolicy,
    DynamicBehavior,
    ConsistencyResult,
    VerificationReport
)

__all__ = [
    "StaticAnalyzer",
    "DynamicAnalyzer",
    "ConsistencyChecker",
    "Pipeline",
    "StaticPolicy",
    "DynamicBehavior",
    "ConsistencyResult",
    "VerificationReport"
]


