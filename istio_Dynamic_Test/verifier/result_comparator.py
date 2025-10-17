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

# 全局可调变量：流量分布验证的容错覆盖（优先级最高）。
# 将其设为 None 表示使用用例矩阵中的 margin_of_error（或动态容错）。
# 例如：将其设置为 0.08 可放宽为 ±8%。
TRAFFIC_SPLIT_MARGIN_OVERRIDE: Optional[float] = None

from .log_parser import LogEntry, EnvoyLogParser
from .behavior_model import ExpectedBehavior, TestType, PolicyType

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
    
    def _verify_http_status(self, case_id: str, expected_behavior: ExpectedBehavior,
                          http_results: Dict) -> VerificationResult:
        """
        验证HTTP状态码 (主要验证指标)
        
        Args:
            case_id: 测试用例ID
            expected_behavior: 期望行为
            http_results: HTTP测试结果
            
        Returns:
            VerificationResult: 验证结果
        """
        status_codes = http_results.get('status_codes', {})
        total_requests = http_results.get('total_requests', 0)
        success_rate = http_results.get('success_rate', 0.0)
        avg_response_time = http_results.get('avg_response_time', 0.0)
        
        # 判断成功标准
        expected_success_rate = getattr(expected_behavior, 'expected_success_rate', None) or 100.0
        expected_max_response_time = getattr(expected_behavior, 'expected_max_response_time', None) or 5.0
        
        # 主要判断：成功率和响应时间
        success_ok = success_rate >= expected_success_rate
        time_ok = avg_response_time <= expected_max_response_time
        
        if success_ok and time_ok:
            status = VerificationStatus.PASSED
            message = f"HTTP验证通过: 成功率{success_rate:.1f}% >= {expected_success_rate}%, 平均响应时间{avg_response_time:.3f}s <= {expected_max_response_time}s"
        else:
            status = VerificationStatus.FAILED
            issues = []
            if not success_ok:
                issues.append(f"成功率不足: {success_rate:.1f}% < {expected_success_rate}%")
            if not time_ok:
                issues.append(f"响应时间过长: {avg_response_time:.3f}s > {expected_max_response_time}s")
            message = f"HTTP验证失败: {'; '.join(issues)}"
        
        # 状态码分布详情
        status_details = []
        for code, count in status_codes.items():
            percentage = (count / total_requests * 100) if total_requests > 0 else 0
            status_details.append(f"{code}: {count}个请求 ({percentage:.1f}%)")
        
        return VerificationResult(
            test_name="HTTP状态码验证",
            case_id=case_id,
            status=status,
            expected_value=f"成功率>={expected_success_rate}%, 响应时间<={expected_max_response_time}s",
            actual_value=f"成功率{success_rate:.1f}%, 响应时间{avg_response_time:.3f}s",
            message=message,
            details={
                "status_codes": status_codes,
                "status_details": status_details,
                "total_requests": total_requests,
                "success_rate": success_rate,
                "avg_response_time": avg_response_time
            }
        )
    
    def compare_single_result(self, case_id: str, expected_behavior: ExpectedBehavior,
                            parsed_logs: Dict[str, List[LogEntry]], 
                            http_results: Dict = None) -> ComprehensiveResult:
        """
        比较单个测试用例的结果 - 多维度验证
        
        Args:
            case_id: 测试用例 ID
            expected_behavior: 期望行为
            parsed_logs: 解析后的日志数据
            http_results: HTTP测试结果 (包含状态码、响应时间等)
            
        Returns:
            综合验证结果
        """
        individual_results = []
        
        # 1. HTTP状态码验证 (主要指标 - 最可靠)
        if http_results:
            http_result = self._verify_http_status(case_id, expected_behavior, http_results)
            individual_results.append(http_result)
        
        # 2. 基本统计验证 (日志维度 - 可能有延迟)
        total_requests = sum(len(entries) for entries in parsed_logs.values())
        basic_result = self._verify_basic_metrics(
            case_id, expected_behavior, total_requests
        )
        individual_results.append(basic_result)
        
        # 2. 根据测试类型和配置进行具体验证
        
        # 路由验证
        if (expected_behavior.test_type == TestType.SINGLE_REQUEST or 
            expected_behavior.expected_destination):
            route_result = self._verify_routing(case_id, expected_behavior, parsed_logs)
            individual_results.append(route_result)
        
        # 流量分布验证
        if (expected_behavior.policy_type == PolicyType.TRAFFIC_SPLIT or
            expected_behavior.expected_distribution):
            dist_result = self._verify_traffic_distribution(
                case_id, expected_behavior, parsed_logs
            )
            individual_results.append(dist_result)
        
        # 熔断器验证
        if (expected_behavior.policy_type == PolicyType.CIRCUIT_BREAKER or
            expected_behavior.expected_trip_threshold or
            expected_behavior.expected_circuit_breaker_threshold):
            cb_result = self._verify_circuit_breaker(
                case_id, expected_behavior, parsed_logs
            )
            individual_results.append(cb_result)
        
        # 重试验证
        if (expected_behavior.policy_type == PolicyType.RETRY or
            expected_behavior.expected_retry_attempts or
            expected_behavior.expected_max_retries):
            retry_result = self._verify_retry(
                case_id, expected_behavior, parsed_logs
            )
            individual_results.append(retry_result)
        
        # 故障注入验证
        if (expected_behavior.policy_type == PolicyType.FAULT_INJECTION or
            expected_behavior.expected_fault_code or
            expected_behavior.expected_fault_rate):
            fault_result = self._verify_fault_injection(
                case_id, expected_behavior, parsed_logs
            )
            individual_results.append(fault_result)
        
        # 5. 性能指标验证
        performance_result = self._verify_performance_metrics(
            case_id, expected_behavior, parsed_logs
        )
        individual_results.append(performance_result)
        
        # 6. 计算综合状态（按策略类型定制必需维度）
        overall_status = self._calculate_overall_status_policy_aware(expected_behavior, individual_results)
        
        # 7. 生成指标摘要
        metrics = self._generate_metrics_summary(parsed_logs)
        
        # 8. 生成文字摘要
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
        # 代码级可调覆盖（优先级最高）
        if TRAFFIC_SPLIT_MARGIN_OVERRIDE is not None:
            margin_of_error = float(TRAFFIC_SPLIT_MARGIN_OVERRIDE)
        
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
        total_requests = distribution_result.get('total_requests', 0)
        
        # 动态容错：基于二项分布标准误差的 95% 置信区间
        # moe(p) = 1.96 * sqrt(p*(1-p)/n)
        effective_margin = margin_of_error
        if total_requests > 0 and expected_dist:
            import math
            dynamic_margins = []
            for p in expected_dist.values():
                p = max(0.0, min(1.0, float(p)))
                se = math.sqrt(p * (1.0 - p) / total_requests)
                moe = 1.96 * se
                dynamic_margins.append(moe)
            # 使用最保守（最大的）动态容错，并留少量缓冲
            dynamic_margin = max(dynamic_margins) if dynamic_margins else 0.0
            # 加 1% 缓冲，避免边界抖动
            effective_margin = max(margin_of_error, dynamic_margin + 0.01)
        
        # 使用（可能放宽的）容错进行验证
        weight_verification = self.log_parser.verify_weight_distribution(
            distribution_result, expected_dist, effective_margin
        )
        # 标注实际使用的容错
        weight_verification['configured_margin_of_error'] = margin_of_error
        weight_verification['effective_margin_of_error'] = effective_margin
        
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
    
    def _verify_retry(self, case_id: str, expected_behavior: ExpectedBehavior,
                     parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证重试行为，包括时间分析（支持Gateway日志）"""
        # 分离Gateway和Sidecar日志
        gateway_entries = []
        sidecar_entries = []
        all_entries = []
        
        for pod_name, entries in parsed_logs.items():
            for entry in entries:
                all_entries.append(entry)
                if hasattr(entry, 'log_source'):
                    if entry.log_source == "gateway" or "gateway" in pod_name.lower():
                        gateway_entries.append(entry)
                    else:
                        sidecar_entries.append(entry)
                else:
                    # 兼容老版本LogEntry
                    if "gateway" in pod_name.lower():
                        gateway_entries.append(entry)
                    else:
                        sidecar_entries.append(entry)
        
        if not all_entries:
            return VerificationResult(
                test_name="重试验证",
                case_id=case_id,
                status=VerificationStatus.FAILED,
                expected_value="重试行为",
                actual_value="无日志",
                message="未找到任何日志条目"
            )
        
        print(f"📊 重试验证 - Gateway日志: {len(gateway_entries)}条, Sidecar日志: {len(sidecar_entries)}条")
        
        # 优先使用Gateway日志进行重试分析
        primary_entries = gateway_entries if gateway_entries else all_entries
        
        # 分析重试模式
        # 1. 检查错误条目（可能触发重试）
        error_entries = [e for e in all_entries if e.is_error]
        success_entries = [e for e in all_entries if e.is_success]
        
        # 2. 分析响应时间分布，寻找重试延迟特征
        response_times = [e.request_time for e in all_entries if e.request_time > 0]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # 3. 检查是否有明显的重试延迟（比正常请求慢很多）
        if response_times:
            response_times.sort()
            p95_time = response_times[int(len(response_times) * 0.95)] if len(response_times) > 20 else max(response_times)
            p50_time = response_times[len(response_times) // 2]
            
            # 如果95%分位数比中位数大很多，可能有重试
            time_variance_ratio = p95_time / p50_time if p50_time > 0 else 1
        else:
            time_variance_ratio = 1
            p95_time = 0
            p50_time = 0
        
        # 4. 重试判断逻辑
        retry_detected = False
        retry_indicators = []
        
        # 检查响应时间分布异常（重试导致的延迟）
        if time_variance_ratio > 3:  # 95%分位数比中位数大3倍以上
            retry_detected = True
            retry_indicators.append(f"响应时间分布异常 (P95/P50={time_variance_ratio:.1f})")
        
        # 检查错误率与最终成功率的关系
        if error_entries and success_entries:
            initial_error_rate = len(error_entries) / len(all_entries)
            if 0.1 < initial_error_rate < 0.8:  # 有一定错误但不是全部失败，可能有重试成功
                retry_detected = True
                retry_indicators.append(f"部分错误后成功 (错误率{initial_error_rate:.1%})")
        
        # 检查期望的重试配置
        expected_max_retries = getattr(expected_behavior, 'expected_max_retries', None)
        expected_retry_timeout = getattr(expected_behavior, 'expected_retry_timeout', None)
        
        # 时间验证
        time_validation_passed = True
        time_message = ""
        
        if expected_retry_timeout and avg_response_time > 0:
            # 检查平均响应时间是否在预期范围内
            if avg_response_time > expected_retry_timeout * 1.5:  # 允许50%容错
                time_validation_passed = False
                time_message = f"响应时间超出预期 ({avg_response_time:.3f}s > {expected_retry_timeout * 1.5:.3f}s)"
            else:
                time_message = f"响应时间在预期范围内 ({avg_response_time:.3f}s)"
        
        # 综合判断
        if retry_detected and time_validation_passed:
            status = VerificationStatus.PASSED
            message = f"检测到重试行为: {', '.join(retry_indicators)}"
            if time_message:
                message += f"; {time_message}"
        elif retry_detected and not time_validation_passed:
            status = VerificationStatus.WARNING
            message = f"检测到重试但时间异常: {', '.join(retry_indicators)}; {time_message}"
        elif not retry_detected:
            status = VerificationStatus.WARNING
            message = f"未明确检测到重试行为，平均响应时间: {avg_response_time:.3f}s"
        else:
            status = VerificationStatus.FAILED
            message = "重试验证失败"
        
        return VerificationResult(
            test_name="重试验证",
            case_id=case_id,
            status=status,
            expected_value="重试行为",
            actual_value=f"{len(retry_indicators)} 个重试指标",
            message=message,
            details={
                'total_requests': len(all_entries),
                'error_requests': len(error_entries),
                'success_requests': len(success_entries),
                'avg_response_time': avg_response_time,
                'p95_response_time': p95_time,
                'p50_response_time': p50_time,
                'time_variance_ratio': time_variance_ratio,
                'retry_indicators': retry_indicators,
                'time_validation_passed': time_validation_passed,
                'expected_max_retries': expected_max_retries,
                'expected_retry_timeout': expected_retry_timeout
            }
        )
    
    def _verify_circuit_breaker(self, case_id: str, expected_behavior: ExpectedBehavior,
                              parsed_logs: Dict[str, List[LogEntry]]) -> VerificationResult:
        """验证熔断器行为，包括时间分析（支持Gateway日志）"""
        # 分离Gateway和Sidecar日志
        gateway_entries = []
        sidecar_entries = []
        all_entries = []
        
        for pod_name, entries in parsed_logs.items():
            for entry in entries:
                all_entries.append(entry)
                if hasattr(entry, 'log_source'):
                    if entry.log_source == "gateway" or "gateway" in pod_name.lower():
                        gateway_entries.append(entry)
                    else:
                        sidecar_entries.append(entry)
                else:
                    # 兼容老版本LogEntry
                    if "gateway" in pod_name.lower():
                        gateway_entries.append(entry)
                    else:
                        sidecar_entries.append(entry)
        
        if not all_entries:
            return VerificationResult(
                test_name="熔断器验证",
                case_id=case_id,
                status=VerificationStatus.FAILED,
                expected_value="熔断行为",
                actual_value="无日志",
                message="未找到任何日志条目"
            )
        
        print(f"📊 熔断器验证 - Gateway日志: {len(gateway_entries)}条, Sidecar日志: {len(sidecar_entries)}条")
        
        # 按时间排序，分析熔断时间模式
        all_entries.sort(key=lambda e: e.timestamp)
        gateway_entries.sort(key=lambda e: e.timestamp)
        sidecar_entries.sort(key=lambda e: e.timestamp)
        
        # 分析错误模式，寻找熔断特征（优先使用Gateway日志）
        primary_entries = gateway_entries if gateway_entries else all_entries
        error_entries = [e for e in primary_entries if e.is_error]
        success_entries = [e for e in primary_entries if e.is_success]
        
        # 检查熔断器相关的错误，利用response_flags
        circuit_breaker_errors = []
        upstream_overflow_errors = []  # UO标志
        upstream_connection_errors = []  # UH, UC, UF标志
        
        for entry in error_entries:
            if entry.status_code == 503:
                circuit_breaker_errors.append(entry)
                # 检查response_flags来识别具体的熔断类型
                if hasattr(entry, 'response_flags'):
                    if entry.response_flags == 'UO':
                        upstream_overflow_errors.append(entry)
                    elif entry.response_flags in ['UH', 'UC', 'UF']:
                        upstream_connection_errors.append(entry)
        
        print(f"🔍 熔断分析 - 503错误: {len(circuit_breaker_errors)}个, UO溢出: {len(upstream_overflow_errors)}个, 连接错误: {len(upstream_connection_errors)}个")
        
        # 计算错误率
        error_rate = len(error_entries) / len(all_entries)
        
        # 时间分析：检查熔断开启和恢复模式
        time_analysis = self._analyze_circuit_breaker_timing(all_entries, error_entries, circuit_breaker_errors)
        
        # 检查期望的熔断配置
        expected_trip_threshold = getattr(expected_behavior, 'expected_trip_threshold', None)
        expected_trip_timeout = getattr(expected_behavior, 'expected_trip_timeout', None)
        expected_recovery_time = getattr(expected_behavior, 'expected_recovery_time', None)
        
        # 时间验证
        time_validation_results = []
        
        # 验证熔断触发时间
        if expected_trip_timeout and time_analysis.get('trip_detection_time'):
            trip_time = time_analysis['trip_detection_time']
            if trip_time <= expected_trip_timeout * 1.2:  # 允许20%容错
                time_validation_results.append(f"熔断触发时间正常 ({trip_time:.3f}s)")
            else:
                time_validation_results.append(f"熔断触发时间过长 ({trip_time:.3f}s > {expected_trip_timeout * 1.2:.3f}s)")
        
        # 验证恢复时间
        if expected_recovery_time and time_analysis.get('recovery_time'):
            recovery_time = time_analysis['recovery_time']
            if recovery_time <= expected_recovery_time * 1.2:  # 允许20%容错
                time_validation_results.append(f"恢复时间正常 ({recovery_time:.3f}s)")
            else:
                time_validation_results.append(f"恢复时间过长 ({recovery_time:.3f}s > {expected_recovery_time * 1.2:.3f}s)")
        
        # 综合熔断判断逻辑
        circuit_breaker_detected = False
        cb_indicators = []
        
        # 检查503错误和错误率
        if circuit_breaker_errors and error_rate > 0.1:  # 超过 10% 错误率且有 503
            circuit_breaker_detected = True
            cb_indicators.append(f"{len(circuit_breaker_errors)} 个503错误")
        
        # 检查错误聚集模式（熔断特征）
        if time_analysis.get('error_clustering_detected'):
            circuit_breaker_detected = True
            cb_indicators.append("错误聚集模式")
        
        # 检查快速失败模式（熔断后的快速拒绝）
        if time_analysis.get('fast_fail_detected'):
            circuit_breaker_detected = True
            cb_indicators.append("快速失败模式")
        
        # 时间验证通过情况
        time_validation_passed = all("正常" in result for result in time_validation_results)
        
        # 综合判断
        if circuit_breaker_detected and time_validation_passed:
            status = VerificationStatus.PASSED
            message = f"检测到熔断行为: {', '.join(cb_indicators)}"
            if time_validation_results:
                message += f"; 时间验证: {', '.join(time_validation_results)}"
        elif circuit_breaker_detected and not time_validation_passed:
            status = VerificationStatus.WARNING
            message = f"检测到熔断但时间异常: {', '.join(cb_indicators)}; {', '.join(time_validation_results)}"
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
            actual_value=f"{error_rate:.2%} 错误率, {len(cb_indicators)} 个指标",
            message=message,
            details={
                'total_requests': len(all_entries),
                'error_requests': len(error_entries),
                'circuit_breaker_errors': len(circuit_breaker_errors),
                'error_rate': error_rate,
                'cb_indicators': cb_indicators,
                'time_analysis': time_analysis,
                'time_validation_results': time_validation_results,
                'time_validation_passed': time_validation_passed,
                'expected_trip_threshold': expected_trip_threshold,
                'expected_trip_timeout': expected_trip_timeout,
                'expected_recovery_time': expected_recovery_time
            }
        )
    
    def _analyze_circuit_breaker_timing(self, all_entries: List[LogEntry], 
                                       error_entries: List[LogEntry], 
                                       cb_errors: List[LogEntry]) -> Dict[str, Any]:
        """分析熔断器时间模式"""
        if not all_entries:
            return {}
        
        analysis = {}
        
        # 检测错误聚集（连续错误表示熔断触发）
        error_clustering_detected = False
        consecutive_errors = 0
        max_consecutive_errors = 0
        
        for entry in all_entries:
            if entry.is_error:
                consecutive_errors += 1
                max_consecutive_errors = max(max_consecutive_errors, consecutive_errors)
            else:
                consecutive_errors = 0
        
        if max_consecutive_errors >= 5:  # 连续5个以上错误
            error_clustering_detected = True
        
        analysis['error_clustering_detected'] = error_clustering_detected
        analysis['max_consecutive_errors'] = max_consecutive_errors
        
        # 检测快速失败（503错误响应时间很短）
        fast_fail_detected = False
        if cb_errors:
            cb_response_times = [e.request_time for e in cb_errors if e.request_time > 0]
            if cb_response_times:
                avg_cb_time = sum(cb_response_times) / len(cb_response_times)
                # 熔断器快速失败通常响应时间很短
                if avg_cb_time < 0.1:  # 小于100ms认为是快速失败
                    fast_fail_detected = True
                analysis['avg_cb_response_time'] = avg_cb_time
        
        analysis['fast_fail_detected'] = fast_fail_detected
        
        # 分析熔断触发时间（第一个错误到熔断开启的时间）
        if error_entries and cb_errors:
            try:
                from datetime import datetime
                # 将时间戳字符串转换为datetime对象
                error_times = []
                cb_times = []
                
                for e in error_entries:
                    try:
                        # 支持多种时间格式
                        if 'T' in e.timestamp:
                            time_obj = datetime.fromisoformat(e.timestamp.replace('Z', '+00:00'))
                        else:
                            time_obj = datetime.strptime(e.timestamp, '%Y-%m-%d %H:%M:%S')
                        error_times.append(time_obj)
                    except:
                        continue
                
                for e in cb_errors:
                    try:
                        if 'T' in e.timestamp:
                            time_obj = datetime.fromisoformat(e.timestamp.replace('Z', '+00:00'))
                        else:
                            time_obj = datetime.strptime(e.timestamp, '%Y-%m-%d %H:%M:%S')
                        cb_times.append(time_obj)
                    except:
                        continue
                
                if error_times and cb_times:
                    first_error_time = min(error_times)
                    first_cb_time = min(cb_times)
                    trip_detection_time = (first_cb_time - first_error_time).total_seconds()
                    analysis['trip_detection_time'] = max(0, trip_detection_time)
            except Exception as e:
                print(f"⚠️ 时间解析错误: {e}")
                analysis['trip_detection_time'] = 0
        
        # 分析恢复时间（最后一个熔断错误到第一个成功请求的时间）
        if cb_errors and all_entries:
            try:
                # 转换时间戳为datetime对象
                cb_times = []
                for e in cb_errors:
                    try:
                        if 'T' in e.timestamp:
                            time_obj = datetime.fromisoformat(e.timestamp.replace('Z', '+00:00'))
                        else:
                            time_obj = datetime.strptime(e.timestamp, '%Y-%m-%d %H:%M:%S')
                        cb_times.append((time_obj, e))
                    except:
                        continue
                
                if cb_times:
                    last_cb_time_obj, _ = max(cb_times, key=lambda x: x[0])
                    
                    # 找到熔断后的成功请求
                    success_times = []
                    for e in all_entries:
                        if e.is_success:
                            try:
                                if 'T' in e.timestamp:
                                    time_obj = datetime.fromisoformat(e.timestamp.replace('Z', '+00:00'))
                                else:
                                    time_obj = datetime.strptime(e.timestamp, '%Y-%m-%d %H:%M:%S')
                                if time_obj > last_cb_time_obj:
                                    success_times.append(time_obj)
                            except:
                                continue
                    
                    if success_times:
                        first_success_time = min(success_times)
                        recovery_time = (first_success_time - last_cb_time_obj).total_seconds()
                        analysis['recovery_time'] = recovery_time
            except Exception as e:
                print(f"⚠️ 恢复时间解析错误: {e}")
                analysis['recovery_time'] = 0
        
        return analysis
    
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
        """
        计算综合状态 - 任一维度通过即判定为通过；否则若有告警则为告警，否则失败。
        同时各维度详细状态会在报告中展示。
        """
        if not individual_results:
            return VerificationStatus.SKIPPED

        # 任一维度通过即合法
        if any(r.status == VerificationStatus.PASSED for r in individual_results):
            return VerificationStatus.PASSED
        # 其次若存在告警
        if any(r.status == VerificationStatus.WARNING for r in individual_results):
            return VerificationStatus.WARNING
        # 否则失败
        return VerificationStatus.FAILED

    def _calculate_overall_status_policy_aware(self, expected_behavior: ExpectedBehavior,
                                              individual_results: List[VerificationResult]) -> VerificationStatus:
        """
        基于策略类型的定制综合判定：
        - 路由: 只要 HTTP 状态验证通过即可认为通过（日志维度仅作参考）
        - 流量分布: 必须流量分布验证通过；HTTP 作为基础健康判断
        - 故障注入: 以 HTTP 目标故障码/成功率为主，日志辅助
        - 熔断/重试: 允许一定错误率，HTTP与性能/错误率验证结合
        """
        # 映射便于查找
        result_by_name = {r.test_name: r for r in individual_results}

        policy = expected_behavior.policy_type
        http_ok = result_by_name.get("HTTP状态码验证") and result_by_name["HTTP状态码验证"].status == VerificationStatus.PASSED
        dist_res = result_by_name.get("流量分布验证") or result_by_name.get("流量分布")
        route_res = result_by_name.get("路由验证")
        perf_res = result_by_name.get("性能指标验证")

        if policy.name.lower() == 'routing':
            # 路由验证必须有日志验证通过才能通过，HTTP验证通过不算
            route_ok = route_res and route_res.status == VerificationStatus.PASSED
            if route_ok:
                return VerificationStatus.PASSED
            elif http_ok and not route_ok:
                # HTTP通过但路由日志验证未通过，给警告
                return VerificationStatus.WARNING
            else:
                return VerificationStatus.FAILED

        if policy.name.lower() == 'traffic_split':
            # 必须分布验证通过
            if dist_res and dist_res.status == VerificationStatus.PASSED:
                return VerificationStatus.PASSED
            # 分布未通过但HTTP通过 → 警告
            if http_ok:
                return VerificationStatus.WARNING
            return VerificationStatus.FAILED

        if policy.name.lower() == 'retry':
            # 重试验证需要重试行为和时间验证都通过
            retry_res = result_by_name.get("重试验证")
            if retry_res and retry_res.status == VerificationStatus.PASSED:
                return VerificationStatus.PASSED
            elif retry_res and retry_res.status == VerificationStatus.WARNING:
                return VerificationStatus.WARNING
            elif http_ok:  # 重试验证失败但HTTP通过，给警告
                return VerificationStatus.WARNING
            else:
                return VerificationStatus.FAILED
        
        if policy.name.lower() == 'circuit_breaker':
            # 熔断验证需要熔断行为和时间验证都通过
            cb_res = result_by_name.get("熔断器验证")
            if cb_res and cb_res.status == VerificationStatus.PASSED:
                return VerificationStatus.PASSED
            elif cb_res and cb_res.status == VerificationStatus.WARNING:
                return VerificationStatus.WARNING
            elif http_ok:  # 熔断验证失败但HTTP通过，给警告
                return VerificationStatus.WARNING
            else:
                return VerificationStatus.FAILED
        
        if policy.name.lower() == 'fault_injection':
            # 故障注入优先HTTP，结合性能/错误率
            if http_ok:
                # 如果有性能指标，失败则警告
                if perf_res and perf_res.status == VerificationStatus.FAILED:
                    return VerificationStatus.WARNING
                return VerificationStatus.PASSED
            # HTTP不通过，若性能/其他有通过，给警告，否则失败
            if any(r.status == VerificationStatus.PASSED for r in individual_results):
                return VerificationStatus.WARNING
            return VerificationStatus.FAILED

        # 其它策略使用通用规则
        return self._calculate_overall_status(individual_results)
    
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
        """生成多维度验证摘要"""
        passed_count = sum(1 for r in individual_results if r.is_passed)
        total_count = len(individual_results)
        
        # 按验证类型分类
        http_results = [r for r in individual_results if r.test_name == "HTTP状态码验证"]
        basic_results = [r for r in individual_results if r.test_name == "基本指标验证"]
        other_results = [r for r in individual_results if r.test_name not in ["HTTP状态码验证", "基本指标验证"]]
        
        summary_parts = [
            f"验证完成: {passed_count}/{total_count} 项通过",
            f"总请求: {metrics['total_requests']}",
            f"成功率: {metrics['success_rate']:.2%}"
        ]
        
        # 添加多维度验证状态
        dimension_status = []
        if http_results:
            http_status = "✅" if http_results[0].is_passed else "❌"
            dimension_status.append(f"HTTP验证{http_status}")
        
        if basic_results:
            basic_status = "✅" if basic_results[0].is_passed else "❌"
            dimension_status.append(f"日志验证{basic_status}")
        
        if other_results:
            other_passed = sum(1 for r in other_results if r.is_passed)
            other_total = len(other_results)
            other_status = "✅" if other_passed == other_total else "⚠️" if other_passed > 0 else "❌"
            dimension_status.append(f"其他验证{other_status}")
        
        if dimension_status:
            summary_parts.append(f"多维度验证: {', '.join(dimension_status)}")
        
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
                         comparator: Optional[ResultComparator] = None,
                         http_results_dir: Optional[str] = None) -> List[ComprehensiveResult]:
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
    
    import os, json, glob

    def load_http_result(case_id: str) -> Optional[Dict[str, Any]]:
        if not http_results_dir:
            return None
        try:
            pattern = os.path.join(http_results_dir, f"{case_id}_http_result_*.json")
            files = glob.glob(pattern)
            if not files:
                return None
            latest = max(files, key=os.path.getctime)
            with open(latest, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('http_result')
        except Exception:
            return None

    for i, behavior in enumerate(expected_behaviors):
        case_id = f"case_{i+1:03d}"  # 默认生成 case_001, case_002...
        
        if case_id in logs_by_case:
            parsed_logs = logs_by_case[case_id]
            http_result = load_http_result(case_id)
            result = comparator.compare_single_result(case_id, behavior, parsed_logs, http_result)
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