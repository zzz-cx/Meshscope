"""
Istio 动态测试验证模块

本模块包含：
- log_parser.py: Envoy 访问日志解析工具
- behavior_model.py: 策略行为模型（配置 → 期望行为）
- result_comparator.py: 对比配置期望和观测行为
- report_generator.py: 输出 HTML / JSON 报告
"""

from .log_parser import EnvoyLogParser, LogEntry
from .behavior_model import BehaviorModel, ExpectedBehavior
from .result_comparator import ResultComparator, VerificationResult
from .report_generator import ReportGenerator

__all__ = [
    'EnvoyLogParser', 'LogEntry',
    'BehaviorModel', 'ExpectedBehavior', 
    'ResultComparator', 'VerificationResult',
    'ReportGenerator'
] 