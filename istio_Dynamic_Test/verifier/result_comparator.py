#!/usr/bin/env python3
"""
结果对比器

主要功能：
1. 比较实际观测行为与期望行为
2. 生成详细的验证结果
3. 提供多维度的一致性检查
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum

from log_parser import LogEntry, EnvoyLogParser
from behavior_model import ExpectedBehavior, TestType, PolicyType

class VerificationStatus(Enum):
    """验证状态枚举"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"

@dataclass
class VerificationResult:
    """单项验证结果"""
    test_name: str
    case_id: str
    status: VerificationStatus
    expected_value: Any
    actual_value: Any
    deviation: Optional[float] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_passed(self) -> bool:
        return self.status == VerificationStatus.PASSED
    
    @property
    def is_failed(self) -> bool:
        return self.status == VerificationStatus.FAILED

@dataclass
class ComprehensiveResult:
    """综合验证结果"""
    case_id: str
    test_description: str
    overall_status: VerificationStatus
    individual_results: List[VerificationResult]
    summary: str
    metrics: Dict[str, Any]
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.individual_results if r.is_passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.individual_results if r.is_failed)
    
    @property
    def success_rate(self) -> float:
        if not self.individual_results:
            return 0.0
        return self.passed_count / len(self.individual_results)

class ResultComparator:
    """结果对比器"""
    
    def __init__(self, log_parser: Optional[EnvoyLogParser] = None):
        """
        初始化对比器
        
        Args:
            log_parser: 日志解析器实例
        """
        self.log_parser = log_parser or EnvoyLogParser()
    
    def compare_single_result(self, case_id: str, expected_behavior: ExpectedBehavior,
                            parsed_logs: Dict[str, List[LogEntry]]) -> ComprehensiveResult:
        """
        比较单个测试用例的结果
        
        Args:
            case_id: 测试用例 ID
            expected_behavior: 期望行为
            parsed_logs: 解析后的日志数据
            
        Returns:
            综合验证结果
        """
        individual_results = []
        
        # 1. 基本统计验证
        total_requests = sum(len(entries) for entries in parsed_logs.values())
        basic_result = self._verify_basic_metrics(
            case_id, expected_behavior, total_requests
        )
        individual_results.append(basic_result)
        
        # 2. 根据测试类型进行具体验证
        if expected_behavior.test_type == TestType.SINGLE_REQUEST:
            route_result = self._verify_routing(case_id, expected_behavior, parsed_logs)
            individual_results.append(route_result)
            
        elif expected_behavior.test_type == TestType.LOAD_TEST:
            if expected_behavior.policy_type == PolicyType.TRAFFIC_SPLIT:
                dist_result = self._verify_traffic_distribution(
                    case_id, expected_behavior, parsed_logs
                )
                individual_results.append(dist_result)
            elif expected_behavior.policy_type == PolicyType.CIRCUIT_BREAKER:
                cb_result = self._verify_circuit_breaker(
                    case_id, expected_behavior, parsed_logs
                )
                individual_results.append(cb_result)
        
        # 3. 故障注入验证
        if expected_behavior.policy_type == PolicyType.FAULT_INJECTION:
            fault_result = self._verify_fault_injection(
                case_id, expected_behavior, parsed_logs
            )
            individual_results.append(fault_result)
        
        # 4. 性能指标验证
        performance_result = self._verify_performance_metrics(
            case_id, expected_behavior, parsed_logs
        )
        individual_results.append(performance_result)
        
        # 5. 计算综合状态
        overall_status = self._calculate_overall_status(individual_results)
        
        # 6. 生成指标摘要
        metrics = self._generate_metrics_summary(parsed_logs)
        
        # 7. 生成文字摘要
        summary = self._generate_summary(expected_behavior, individual_results, metrics)
        
        return ComprehensiveResult(
            case_id=case_id,
            test_description=expected_behavior.description,
            overall_status=overall_status,
            individual_results=individual_results,
            summary=summary,
            metrics=metrics
        )
    
    def _verify_basic_metrics(self, case_id: str, expected_behavior: ExpectedBehavior,
                            total_requests: int) -> VerificationResult:
        """验证基本指标"""
        expected_min = expected_behavior.minimum_requests
        
        if total_requests >= expected_min:
            status = VerificationStatus.PASSED
            message = f"请求数量充足: {total_requests} >= {expected_min}"
        else:
            status = VerificationStatus.FAILED
            message = f"请求数量不足: {total_requests} < {expected_min}"
        
        return VerificationResult(
            test_name="基本指标验证",
            case_id=case_id,
            status=status,
            expected_value=expected_min,
            actual_value=total_requests,
            message=message
        )
    
    def _verify_routing(self, case_id: str, expected_behavior: ExpectedBehavior,
                       parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证路由行为"""
        expected_dest = expected_behavior.expected_destination
        
        if not expected_dest:
            return VerificationResult(
                test_name="路由验证",
                case_id=case_id,
                status=VerificationStatus.SKIPPED,
                expected_value=None,
                actual_value=None,
                message="未配置期望目标版本"
            )
        
        # 检查是否有请求命中期望的版本
        target_pods = [pod for pod in parsed_logs.keys() 
                      if f"-{expected_dest}-" in pod]
        
        if target_pods:
            total_target_requests = sum(len(parsed_logs[pod]) for pod in target_pods)
            total_requests = sum(len(entries) for entries in parsed_logs.values())
            
            if total_target_requests > 0:
                status = VerificationStatus.PASSED
                message = f"成功路由到目标版本 {expected_dest}"
                details = {
                    'target_pods': target_pods,
                    'target_requests': total_target_requests,
                    'total_requests': total_requests,
                    'routing_ratio': total_target_requests / total_requests if total_requests > 0 else 0
                }
            else:
                status = VerificationStatus.FAILED
                message = f"未找到路由到版本 {expected_dest} 的请求"
                details = {'target_pods': target_pods}
        else:
            status = VerificationStatus.FAILED
            message = f"未找到版本 {expected_dest} 的 pod"
            details = {'available_pods': list(parsed_logs.keys())}
        
        return VerificationResult(
            test_name="路由验证",
            case_id=case_id,
            status=status,
            expected_value=expected_dest,
            actual_value=target_pods,
            message=message,
            details=details
        )
    
    def _verify_traffic_distribution(self, case_id: str, expected_behavior: ExpectedBehavior,
                                   parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证流量分布"""
        expected_dist = expected_behavior.expected_distribution
        margin_of_error = expected_behavior.margin_of_error
        
        if not expected_dist:
            return VerificationResult(
                test_name="流量分布验证",
                case_id=case_id,
                status=VerificationStatus.SKIPPED,
                expected_value=None,
                actual_value=None,
                message="未配置期望分布"
            )
        
        # 分析实际分布
        service_name = self._extract_service_name_from_logs(parsed_logs)
        distribution_result = self.log_parser.analyze_distribution(parsed_logs, service_name)
        
        # 使用日志解析器的权重验证功能
        weight_verification = self.log_parser.verify_weight_distribution(
            distribution_result, expected_dist, margin_of_error
        )
        
        status = VerificationStatus.PASSED if weight_verification['overall_passed'] else VerificationStatus.FAILED
        
        return VerificationResult(
            test_name="流量分布验证",
            case_id=case_id,
            status=status,
            expected_value=expected_dist,
            actual_value=distribution_result['version_percentages'],
            deviation=self._calculate_distribution_deviation(expected_dist, distribution_result['version_percentages']),
            message=weight_verification['summary'],
            details=weight_verification
        )
    
    def _verify_fault_injection(self, case_id: str, expected_behavior: ExpectedBehavior,
                              parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证故障注入"""
        expected_fault_rate = expected_behavior.expected_fault_rate
        expected_fault_code = expected_behavior.expected_fault_code
        
        # 统计所有日志条目
        all_entries = []
        for entries in parsed_logs.values():
            all_entries.extend(entries)
        
        if not all_entries:
            return VerificationResult(
                test_name="故障注入验证",
                case_id=case_id,
                status=VerificationStatus.FAILED,
                expected_value=expected_fault_rate,
                actual_value=0,
                message="未找到任何日志条目"
            )
        
        # 计算实际故障率
        fault_entries = []
        if expected_fault_code:
            fault_entries = [e for e in all_entries if e.status_code == expected_fault_code]
        else:
            fault_entries = [e for e in all_entries if e.is_error]
        
        actual_fault_rate = len(fault_entries) / len(all_entries)
        
        # 判断是否符合期望
        if expected_fault_rate is not None:
            deviation = abs(actual_fault_rate - expected_fault_rate)
            tolerance = 0.1  # 10% 容错
            
            if deviation <= tolerance:
                status = VerificationStatus.PASSED
                message = f"故障率符合预期: {actual_fault_rate:.2%} ≈ {expected_fault_rate:.2%}"
            else:
                status = VerificationStatus.FAILED
                message = f"故障率偏差过大: {actual_fault_rate:.2%} vs {expected_fault_rate:.2%}"
        else:
            # 没有期望故障率，只检查是否有故障
            if fault_entries:
                status = VerificationStatus.PASSED
                message = f"检测到故障注入生效: {len(fault_entries)} 个故障请求"
            else:
                status = VerificationStatus.WARNING
                message = "未检测到故障注入效果"
        
        return VerificationResult(
            test_name="故障注入验证",
            case_id=case_id,
            status=status,
            expected_value=expected_fault_rate,
            actual_value=actual_fault_rate,
            deviation=abs(actual_fault_rate - (expected_fault_rate or 0)),
            message=message,
            details={
                'total_requests': len(all_entries),
                'fault_requests': len(fault_entries),
                'expected_fault_code': expected_fault_code,
                'fault_status_codes': [e.status_code for e in fault_entries]
            }
        )
    
    def _verify_circuit_breaker(self, case_id: str, expected_behavior: ExpectedBehavior,
                              parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证熔断器行为"""
        # 统计所有日志条目
        all_entries = []
        for entries in parsed_logs.values():
            all_entries.extend(entries)
        
        if not all_entries:
            return VerificationResult(
                test_name="熔断器验证",
                case_id=case_id,
                status=VerificationStatus.FAILED,
                expected_value="熔断行为",
                actual_value="无日志",
                message="未找到任何日志条目"
            )
        
        # 分析错误模式，寻找熔断特征
        error_entries = [e for e in all_entries if e.is_error]
        
        # 检查是否有 503 错误（通常是熔断标志）
        circuit_breaker_errors = [e for e in error_entries if e.status_code == 503]
        
        # 计算错误率
        error_rate = len(error_entries) / len(all_entries)
        
        # 简单的熔断判断逻辑
        if circuit_breaker_errors and error_rate > 0.1:  # 超过 10% 错误率且有 503
            status = VerificationStatus.PASSED
            message = f"检测到熔断行为: {len(circuit_breaker_errors)} 个 503 错误"
        elif error_rate > 0.5:  # 错误率超过 50%
            status = VerificationStatus.WARNING
            message = f"高错误率可能表示熔断: {error_rate:.2%}"
        else:
            status = VerificationStatus.WARNING
            message = f"未明确检测到熔断行为，错误率: {error_rate:.2%}"
        
        return VerificationResult(
            test_name="熔断器验证",
            case_id=case_id,
            status=status,
            expected_value="熔断行为",
            actual_value=f"{error_rate:.2%} 错误率",
            message=message,
            details={
                'total_requests': len(all_entries),
                'error_requests': len(error_entries),
                'circuit_breaker_errors': len(circuit_breaker_errors),
                'error_rate': error_rate
            }
        )
    
    def _verify_performance_metrics(self, case_id: str, expected_behavior: ExpectedBehavior,
                                  parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证性能指标"""
        # 统计所有日志条目
        all_entries = []
        for entries in parsed_logs.values():
            all_entries.extend(entries)
        
        if not all_entries:
            return VerificationResult(
                test_name="性能指标验证",
                case_id=case_id,
                status=VerificationStatus.SKIPPED,
                expected_value=None,
                actual_value=None,
                message="无日志数据进行性能分析"
            )
        
        # 计算成功率
        success_entries = [e for e in all_entries if e.is_success]
        actual_success_rate = len(success_entries) / len(all_entries)
        
        # 与期望成功率比较
        expected_success_rate = expected_behavior.expected_success_rate
        
        if expected_success_rate is not None:
            deviation = abs(actual_success_rate - expected_success_rate)
            tolerance = 0.1  # 10% 容错
            
            if deviation <= tolerance:
                status = VerificationStatus.PASSED
                message = f"成功率符合预期: {actual_success_rate:.2%} ≈ {expected_success_rate:.2%}"
            else:
                status = VerificationStatus.WARNING
                message = f"成功率偏差: {actual_success_rate:.2%} vs {expected_success_rate:.2%}"
        else:
            # 没有期望成功率，根据一般标准判断
            if actual_success_rate >= 0.95:
                status = VerificationStatus.PASSED
                message = f"成功率良好: {actual_success_rate:.2%}"
            elif actual_success_rate >= 0.8:
                status = VerificationStatus.WARNING
                message = f"成功率一般: {actual_success_rate:.2%}"
            else:
                status = VerificationStatus.WARNING
                message = f"成功率较低: {actual_success_rate:.2%}"
        
        return VerificationResult(
            test_name="性能指标验证",
            case_id=case_id,
            status=status,
            expected_value=expected_success_rate,
            actual_value=actual_success_rate,
            deviation=deviation if expected_success_rate else None,
            message=message,
            details={
                'total_requests': len(all_entries),
                'success_requests': len(success_entries),
                'success_rate': actual_success_rate
            }
        )
    
    def _calculate_overall_status(self, individual_results: List[VerificationResult]) -> VerificationStatus:
        """计算综合状态"""
        if not individual_results:
            return VerificationStatus.SKIPPED
        
        failed_count = sum(1 for r in individual_results if r.status == VerificationStatus.FAILED)
        warning_count = sum(1 for r in individual_results if r.status == VerificationStatus.WARNING)
        
        if failed_count > 0:
            return VerificationStatus.FAILED
        elif warning_count > 0:
            return VerificationStatus.WARNING
        else:
            return VerificationStatus.PASSED
    
    def _generate_metrics_summary(self, parsed_logs: Dict[str, List[LogEntry]]) -> Dict[str, Any]:
        """生成指标摘要"""
        total_requests = sum(len(entries) for entries in parsed_logs.values())
        total_pods = len(parsed_logs)
        
        # 统计所有条目
        all_entries = []
        for entries in parsed_logs.values():
            all_entries.extend(entries)
        
        success_count = sum(1 for e in all_entries if e.is_success)
        error_count = sum(1 for e in all_entries if e.is_error)
        
        # 响应时间统计
        response_times = [e.request_time for e in all_entries if e.request_time > 0]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            'total_requests': total_requests,
            'total_pods': total_pods,
            'success_count': success_count,
            'error_count': error_count,
            'success_rate': success_count / total_requests if total_requests > 0 else 0,
            'error_rate': error_count / total_requests if total_requests > 0 else 0,
            'avg_response_time': avg_response_time,
            'pods_with_traffic': [pod for pod, entries in parsed_logs.items() if entries]
        }
    
    def _generate_summary(self, expected_behavior: ExpectedBehavior,
                         individual_results: List[VerificationResult],
                         metrics: Dict[str, Any]) -> str:
        """生成文字摘要"""
        passed_count = sum(1 for r in individual_results if r.is_passed)
        total_count = len(individual_results)
        
        summary_parts = [
            f"验证完成: {passed_count}/{total_count} 项通过",
            f"总请求: {metrics['total_requests']}",
            f"成功率: {metrics['success_rate']:.2%}"
        ]
        
        if expected_behavior.policy_type == PolicyType.TRAFFIC_SPLIT:
            summary_parts.append("流量分布测试")
        elif expected_behavior.policy_type == PolicyType.ROUTING:
            summary_parts.append("路由测试")
        elif expected_behavior.policy_type == PolicyType.FAULT_INJECTION:
            summary_parts.append("故障注入测试")
        
        return " | ".join(summary_parts)
    
    def _extract_service_name_from_logs(self, parsed_logs: Dict[str, List[LogEntry]]) -> str:
        """从日志中提取服务名称"""
        if not parsed_logs:
            return "unknown"
        
        # 从第一个 pod 名称提取服务名
        first_pod = next(iter(parsed_logs.keys()))
        # 假设 pod 名称格式为 servicename-version-hash
        parts = first_pod.split('-')
        if len(parts) >= 2:
            return parts[0]
        
        return "unknown"
    
    def _calculate_distribution_deviation(self, expected: Dict[str, float], 
                                        actual: Dict[str, float]) -> float:
        """计算分布偏差"""
        if not expected or not actual:
            return 1.0
        
        total_deviation = 0.0
        for version, expected_weight in expected.items():
            actual_weight = actual.get(version, 0.0)
            total_deviation += abs(expected_weight - actual_weight)
        
        return total_deviation / len(expected)

# 工具函数
def compare_batch_results(expected_behaviors: List[ExpectedBehavior],
                         logs_by_case: Dict[str, Dict[str, List[LogEntry]]],
                         comparator: Optional[ResultComparator] = None) -> List[ComprehensiveResult]:
    """
    批量比较测试结果
    
    Args:
        expected_behaviors: 期望行为列表
        logs_by_case: {case_id: {pod_name: [LogEntry]}} 格式的日志数据
        comparator: 结果对比器实例
        
    Returns:
        综合验证结果列表
    """
    if comparator is None:
        comparator = ResultComparator()
    
    results = []
    
    for i, behavior in enumerate(expected_behaviors):
        case_id = f"case_{i+1:03d}"  # 默认生成 case_001, case_002...
        
        if case_id in logs_by_case:
            parsed_logs = logs_by_case[case_id]
            result = comparator.compare_single_result(case_id, behavior, parsed_logs)
            results.append(result)
        else:
            # 创建一个失败的结果
            result = ComprehensiveResult(
                case_id=case_id,
                test_description=behavior.description,
                overall_status=VerificationStatus.FAILED,
                individual_results=[],
                summary=f"未找到测试用例 {case_id} 的日志数据",
                metrics={}
            )
            results.append(result)
    
    return results 