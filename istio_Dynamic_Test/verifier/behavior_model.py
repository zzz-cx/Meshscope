#!/usr/bin/env python3
"""
策略行为模型

主要功能：
1. 解析 Istio 配置文件（VirtualService, DestinationRule 等）
2. 根据测试用例配置生成期望行为
3. 定义各种策略的验证规则
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Any
from enum import Enum

class TestType(Enum):
    """测试类型枚举"""
    SINGLE_REQUEST = "single_request"
    LOAD_TEST = "load_test"
    FAULT_INJECTION = "fault_injection"
    CIRCUIT_BREAKER = "circuit_breaker"
    RETRY = "retry"

class PolicyType(Enum):
    """策略类型枚举"""
    ROUTING = "routing"
    TRAFFIC_SPLIT = "traffic_split"
    FAULT_INJECTION = "fault_injection"
    CIRCUIT_BREAKER = "circuit_breaker"
    RETRY = "retry"
    RATE_LIMIT = "rate_limit"

@dataclass
class ExpectedBehavior:
    """期望行为定义"""
    test_type: TestType
    policy_type: PolicyType
    
    # 路由相关
    expected_destination: Optional[str] = None  # 期望的目标版本
    expected_pod_pattern: Optional[str] = None  # 期望的 pod 名称模式
    
    # 流量分布相关
    expected_distribution: Optional[Dict[str, float]] = None  # {version: weight}
    margin_of_error: float = 0.05  # 容错率
    
    # 故障注入相关
    expected_fault_rate: Optional[float] = None  # 期望的故障率
    expected_fault_code: Optional[int] = None  # 期望的故障状态码
    expected_delay: Optional[float] = None  # 期望的延迟（秒）
    
    # 重试相关
    expected_retry_attempts: Optional[int] = None  # 期望的重试次数
    expected_retry_timeout: Optional[float] = None  # 期望的重试超时
    
    # 熔断相关
    expected_circuit_breaker_threshold: Optional[int] = None  # 熔断阈值
    expected_circuit_breaker_timeout: Optional[float] = None  # 熔断超时
    
    # 性能相关
    expected_response_time_p95: Optional[float] = None  # 期望的 P95 响应时间
    expected_success_rate: Optional[float] = None  # 期望的成功率
    
    # 通用
    minimum_requests: int = 1  # 最少请求数
    description: str = ""  # 行为描述
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'test_type': self.test_type.value,
            'policy_type': self.policy_type.value,
            'expected_destination': self.expected_destination,
            'expected_pod_pattern': self.expected_pod_pattern,
            'expected_distribution': self.expected_distribution,
            'margin_of_error': self.margin_of_error,
            'expected_fault_rate': self.expected_fault_rate,
            'expected_fault_code': self.expected_fault_code,
            'expected_delay': self.expected_delay,
            'expected_retry_attempts': self.expected_retry_attempts,
            'expected_retry_timeout': self.expected_retry_timeout,
            'expected_circuit_breaker_threshold': self.expected_circuit_breaker_threshold,
            'expected_circuit_breaker_timeout': self.expected_circuit_breaker_timeout,
            'expected_response_time_p95': self.expected_response_time_p95,
            'expected_success_rate': self.expected_success_rate,
            'minimum_requests': self.minimum_requests,
            'description': self.description
        }

class BehaviorModel:
    """策略行为模型"""
    
    def __init__(self):
        """初始化行为模型"""
        pass
    
    def parse_test_case(self, test_case: Dict[str, Any]) -> ExpectedBehavior:
        """
        解析测试用例，生成期望行为
        
        Args:
            test_case: 测试用例配置
            
        Returns:
            ExpectedBehavior 对象
        """
        case_type = test_case.get('type', 'single_request')
        expected_outcome = test_case.get('expected_outcome', {})
        request_params = test_case.get('request_params', {})
        load_params = test_case.get('load_params', {})
        
        # 确定测试类型
        test_type = TestType(case_type)
        
        # 确定策略类型
        policy_type = self._determine_policy_type(test_case)
        
        # 基本信息
        behavior = ExpectedBehavior(
            test_type=test_type,
            policy_type=policy_type,
            description=test_case.get('description', '')
        )
        
        # 设置最少请求数
        if test_type == TestType.LOAD_TEST:
            behavior.minimum_requests = load_params.get('num_requests', 1)
        
        # 根据策略类型设置期望行为
        if policy_type == PolicyType.ROUTING:
            self._parse_routing_behavior(behavior, expected_outcome, request_params)
        elif policy_type == PolicyType.TRAFFIC_SPLIT:
            self._parse_traffic_split_behavior(behavior, expected_outcome, load_params)
        elif policy_type == PolicyType.FAULT_INJECTION:
            self._parse_fault_injection_behavior(behavior, expected_outcome, request_params)
        elif policy_type == PolicyType.CIRCUIT_BREAKER:
            self._parse_circuit_breaker_behavior(behavior, expected_outcome, load_params)
        elif policy_type == PolicyType.RETRY:
            self._parse_retry_behavior(behavior, expected_outcome, request_params)
        
        return behavior
    
    def _determine_policy_type(self, test_case: Dict[str, Any]) -> PolicyType:
        """根据测试用例确定策略类型"""
        description = test_case.get('description', '').lower()
        expected_outcome = test_case.get('expected_outcome', {})
        request_params = test_case.get('request_params', {})
        
        # 检查是否有故障注入
        if 'inject_fault_to' in request_params or 'trigger_condition' in request_params:
            if '重试' in description or 'retry' in description:
                return PolicyType.RETRY
            elif '熔断' in description or 'circuit' in description:
                return PolicyType.CIRCUIT_BREAKER
            else:
                return PolicyType.FAULT_INJECTION
        
        # 检查是否是流量分布测试
        if 'distribution' in expected_outcome:
            return PolicyType.TRAFFIC_SPLIT
        
        # 检查是否是路由测试
        if 'destination' in expected_outcome:
            return PolicyType.ROUTING
        
        # 默认为路由测试
        return PolicyType.ROUTING
    
    def _parse_routing_behavior(self, behavior: ExpectedBehavior, 
                              expected_outcome: Dict, request_params: Dict):
        """解析路由行为"""
        destination = expected_outcome.get('destination')
        if destination:
            behavior.expected_destination = destination
            # 生成期望的 pod 模式
            service = request_params.get('host', 'unknown')
            behavior.expected_pod_pattern = f"{service}-{destination}-*"
        
        # 设置期望成功率（路由测试通常期望 100% 成功）
        behavior.expected_success_rate = 1.0
    
    def _parse_traffic_split_behavior(self, behavior: ExpectedBehavior,
                                    expected_outcome: Dict, load_params: Dict):
        """解析流量分布行为"""
        distribution = expected_outcome.get('distribution', {})
        if distribution:
            # 转换权重格式
            parsed_distribution = {}
            for version, weight_str in distribution.items():
                if isinstance(weight_str, str) and 'approx' in weight_str:
                    # 解析 "approx 0.80" 格式
                    weight = float(weight_str.replace('approx', '').strip())
                else:
                    weight = float(weight_str)
                parsed_distribution[version] = weight
            
            behavior.expected_distribution = parsed_distribution
        
        # 设置容错率
        margin = expected_outcome.get('margin_of_error', 0.05)
        if isinstance(margin, str):
            behavior.margin_of_error = float(margin)
        else:
            behavior.margin_of_error = margin
        
        # 设置期望成功率
        behavior.expected_success_rate = 0.95  # 负载测试允许少量失败
    
    def _parse_fault_injection_behavior(self, behavior: ExpectedBehavior,
                                      expected_outcome: Dict, request_params: Dict):
        """解析故障注入行为"""
        trigger_condition = request_params.get('trigger_condition', '')
        
        if 'simulate_503_error' in trigger_condition:
            behavior.expected_fault_code = 503
            behavior.expected_fault_rate = 1.0  # 100% 故障率
        elif 'simulate_delay' in trigger_condition:
            behavior.expected_delay = 5.0  # 默认 5 秒延迟
        
        # 故障注入测试通常期望低成功率
        behavior.expected_success_rate = 0.0
    
    def _parse_circuit_breaker_behavior(self, behavior: ExpectedBehavior,
                                      expected_outcome: Dict, load_params: Dict):
        """解析熔断行为"""
        concurrency = load_params.get('concurrency', 1)
        num_requests = load_params.get('num_requests', 1)
        
        # 设置熔断阈值（通常基于并发数）
        behavior.expected_circuit_breaker_threshold = max(5, concurrency)
        behavior.expected_circuit_breaker_timeout = 30.0  # 30 秒熔断窗口
        
        # 熔断测试期望部分请求失败
        behavior.expected_success_rate = 0.5
    
    def _parse_retry_behavior(self, behavior: ExpectedBehavior,
                            expected_outcome: Dict, request_params: Dict):
        """解析重试行为"""
        # 默认重试配置
        behavior.expected_retry_attempts = 3
        behavior.expected_retry_timeout = 10.0
        
        # 重试测试的成功率取决于故障恢复情况
        behavior.expected_success_rate = 0.8
    
    def generate_behavior_summary(self, behavior: ExpectedBehavior) -> str:
        """生成行为摘要描述"""
        summary_parts = [f"测试类型: {behavior.test_type.value}"]
        summary_parts.append(f"策略类型: {behavior.policy_type.value}")
        
        if behavior.expected_destination:
            summary_parts.append(f"期望目标: {behavior.expected_destination}")
        
        if behavior.expected_distribution:
            dist_str = ", ".join([f"{v}:{w:.0%}" for v, w in behavior.expected_distribution.items()])
            summary_parts.append(f"期望分布: {dist_str}")
        
        if behavior.expected_fault_rate:
            summary_parts.append(f"期望故障率: {behavior.expected_fault_rate:.0%}")
        
        if behavior.expected_success_rate is not None:
            summary_parts.append(f"期望成功率: {behavior.expected_success_rate:.0%}")
        
        return " | ".join(summary_parts)
    
    def validate_behavior_config(self, behavior: ExpectedBehavior) -> List[str]:
        """验证行为配置的完整性"""
        warnings = []
        
        if behavior.test_type == TestType.LOAD_TEST:
            if behavior.minimum_requests < 10:
                warnings.append("负载测试的请求数过少，可能影响统计准确性")
        
        if behavior.policy_type == PolicyType.TRAFFIC_SPLIT:
            if not behavior.expected_distribution:
                warnings.append("流量分布测试缺少期望分布配置")
            elif abs(sum(behavior.expected_distribution.values()) - 1.0) > 0.01:
                warnings.append("流量分布权重总和不等于 1.0")
        
        if behavior.policy_type == PolicyType.ROUTING:
            if not behavior.expected_destination:
                warnings.append("路由测试缺少期望目标配置")
        
        return warnings

# 工具函数
def parse_test_matrix(matrix_file: str) -> List[ExpectedBehavior]:
    """
    解析测试矩阵文件，生成期望行为列表
    
    Args:
        matrix_file: 测试矩阵文件路径
        
    Returns:
        期望行为列表
    """
    model = BehaviorModel()
    behaviors = []
    
    try:
        with open(matrix_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        test_cases = data.get('test_cases', [])
        for test_case in test_cases:
            try:
                behavior = model.parse_test_case(test_case)
                behaviors.append(behavior)
            except Exception as e:
                print(f"⚠️ 解析测试用例 {test_case.get('case_id', 'unknown')} 失败: {e}")
        
        print(f"📊 成功解析 {len(behaviors)} 个测试用例的期望行为")
        
    except Exception as e:
        print(f"❌ 解析测试矩阵文件失败: {e}")
    
    return behaviors

def save_behaviors_to_file(behaviors: List[ExpectedBehavior], output_file: str):
    """保存期望行为到文件"""
    data = {
        'behaviors': [behavior.to_dict() for behavior in behaviors],
        'total_count': len(behaviors),
        'generated_at': __import__('datetime').datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2) 