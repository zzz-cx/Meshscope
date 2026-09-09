#!/usr/bin/env python3
"""
指标数据验证器
验证评估结果的合理性和一致性
"""

import logging
import statistics
import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """验证问题"""
    severity: str  # 'error', 'warning', 'info'
    category: str  # 'time', 'resource', 'consistency', 'scalability'
    message: str
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'severity': self.severity,
            'category': self.category,
            'message': self.message,
            'expected': self.expected,
            'actual': self.actual
        }


class MetricsValidator:
    """指标数据验证器"""
    
    def __init__(self):
        """初始化验证器"""
        self.issues: List[ValidationIssue] = []
    
    def validate_metrics(
        self, 
        metrics: Dict[str, Any], 
        baseline: Optional[Dict[str, Any]] = None,
        previous_metrics: Optional[List[Dict[str, Any]]] = None
    ) -> List[ValidationIssue]:
        """
        验证指标数据的合理性
        
        Args:
            metrics: 要验证的指标数据
            baseline: 基准测试数据（可选）
            previous_metrics: 之前的指标数据列表（用于检测增长趋势）
        
        Returns:
            验证问题列表
        """
        self.issues.clear()
        
        # 1. 时间一致性检查
        self._validate_time_consistency(metrics)
        
        # 2. 资源使用合理性检查
        self._validate_resource_usage(metrics)
        
        # 3. 增长趋势检查
        self._validate_growth_trends(metrics)
        
        # 4. 数据范围检查
        self._validate_data_ranges(metrics)
        
        # 5. 与基准对比
        if baseline:
            self._validate_against_baseline(metrics, baseline)
        
        # 6. 线性增长检测（需要历史数据）
        if previous_metrics:
            self._validate_linear_growth(metrics, previous_metrics)
        
        # 7. 平滑度检测
        self._validate_smoothness(metrics)
        
        # 8. 异常值检测
        self._validate_outliers(metrics)
        
        return self.issues
    
    def _validate_time_consistency(self, metrics: Dict[str, Any]):
        """验证时间指标的一致性"""
        parse_time = metrics.get('static_parsing_time', 0.0)
        gen_time = metrics.get('test_generation_time', 0.0)
        validation_time = metrics.get('dynamic_validation_time', 0.0)
        total_time = metrics.get('total_time', 0.0)
        
        # 计算时间总和（不包括监控等待时间）
        calculated_total = parse_time + gen_time + validation_time
        
        # 允许5%的误差（由于监控等待时间等）
        if total_time > 0:
            diff_percent = abs(total_time - calculated_total) / total_time * 100
            if diff_percent > 5.0:
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='time',
                    message=f"总时间与各阶段时间之和差异较大: {diff_percent:.2f}%",
                    expected=f"≈{calculated_total:.3f}秒",
                    actual=f"{total_time:.3f}秒"
                ))
        
        # 检查各阶段时间是否合理
        if validation_time < parse_time and validation_time > 0:
            self.issues.append(ValidationIssue(
                severity='info',
                category='time',
                message="验证时间小于解析时间（可能是缓存效应）",
                expected=f">={parse_time:.3f}秒",
                actual=f"{validation_time:.3f}秒"
            ))
    
    def _validate_resource_usage(self, metrics: Dict[str, Any]):
        """验证资源使用的合理性"""
        # 检查最大内存是否小于平均内存
        memory_avg = metrics.get('memory_avg_mb', 0.0)
        memory_max = metrics.get('memory_max_mb', 0.0)
        
        if memory_max < memory_avg and memory_max > 0:
            self.issues.append(ValidationIssue(
                severity='error',
                category='resource',
                message="最大内存小于平均内存（数据异常）",
                expected=f">={memory_avg:.2f} MB",
                actual=f"{memory_max:.2f} MB"
            ))
        
        # 检查CPU使用率是否合理（0-100%）
        cpu_avg = metrics.get('cpu_avg_percent', 0.0)
        cpu_max = metrics.get('cpu_max_percent', 0.0)
        
        if cpu_max > 100.0:
            self.issues.append(ValidationIssue(
                severity='warning',
                category='resource',
                message="CPU最大使用率超过100%（可能是多核系统）",
                expected="0-100%",
                actual=f"{cpu_max:.2f}%"
            ))
        
        if cpu_max < cpu_avg:
            self.issues.append(ValidationIssue(
                severity='error',
                category='resource',
                message="CPU最大使用率小于平均使用率（数据异常）",
                expected=f">={cpu_avg:.2f}%",
                actual=f"{cpu_max:.2f}%"
            ))
    
    def _validate_growth_trends(self, metrics: Dict[str, Any]):
        """验证增长趋势的合理性"""
        num_services = metrics.get('num_services', 0)
        num_policies = metrics.get('num_policies', 0)
        config_size_kb = metrics.get('config_size_kb', 0.0)
        total_time = metrics.get('total_time', 0.0)
        
        # 检查配置大小与服务数量的比例是否合理
        if num_services > 0 and config_size_kb > 0:
            size_per_service = config_size_kb / num_services
            if size_per_service < 0.1:  # 每个服务配置小于0.1KB可能不合理
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='scalability',
                    message=f"每个服务的配置大小异常小: {size_per_service:.3f} KB",
                    expected=">0.1 KB",
                    actual=f"{size_per_service:.3f} KB"
                ))
        
        # 检查处理时间与服务数量的比例
        if num_services > 0 and total_time > 0:
            time_per_service = total_time / num_services
            if time_per_service > 10.0:  # 每个服务处理时间超过10秒可能异常
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='scalability',
                    message=f"每个服务的处理时间异常长: {time_per_service:.3f}秒",
                    expected="<10秒",
                    actual=f"{time_per_service:.3f}秒"
                ))
    
    def _validate_data_ranges(self, metrics: Dict[str, Any]):
        """验证数据范围是否合理"""
        # 检查服务数量
        num_services = metrics.get('num_services', 0)
        if num_services <= 0:
            self.issues.append(ValidationIssue(
                severity='error',
                category='consistency',
                message="服务数量为0或负数",
                expected=">0",
                actual=num_services
            ))
        
        # 检查策略数量
        num_policies = metrics.get('num_policies', 0)
        if num_policies < 0:
            self.issues.append(ValidationIssue(
                severity='error',
                category='consistency',
                message="策略数量为负数",
                expected=">=0",
                actual=num_policies
            ))
        
        # 检查配置大小
        config_size_kb = metrics.get('config_size_kb', 0.0)
        if config_size_kb < 0:
            self.issues.append(ValidationIssue(
                severity='error',
                category='consistency',
                message="配置大小为负数",
                expected=">=0",
                actual=config_size_kb
            ))
    
    def _validate_against_baseline(self, metrics: Dict[str, Any], baseline: Dict[str, Any]):
        """与基准测试数据对比"""
        # 检查CPU使用率是否显著高于基准
        cpu_avg = metrics.get('cpu_avg_percent', 0.0)
        baseline_cpu = baseline.get('cpu_percent_avg', 0.0)
        
        if baseline_cpu > 0 and cpu_avg > baseline_cpu * 2:
            self.issues.append(ValidationIssue(
                severity='info',
                category='resource',
                message=f"CPU使用率显著高于基准: {cpu_avg:.2f}% vs {baseline_cpu:.2f}%",
                expected=f"≈{baseline_cpu:.2f}%",
                actual=f"{cpu_avg:.2f}%"
            ))
    
    def _validate_linear_growth(self, metrics: Dict[str, Any], previous_metrics: List[Dict[str, Any]]):
        """检测线性增长是否过于完美（可能存在假数据）"""
        if len(previous_metrics) < 2:
            return
        
        # 提取服务数量和总时间
        current_services = metrics.get('num_services', 0)
        current_time = metrics.get('total_time', 0.0)
        current_memory = metrics.get('memory_max_mb', 0.0)
        
        service_counts = [m.get('num_services', 0) for m in previous_metrics] + [current_services]
        time_values = [m.get('total_time', 0.0) for m in previous_metrics] + [current_time]
        memory_values = [m.get('memory_max_mb', 0.0) for m in previous_metrics] + [current_memory]
        
        # 计算增长倍数
        if len(service_counts) >= 2:
            service_growth_ratios = []
            time_growth_ratios = []
            memory_growth_ratios = []
            
            for i in range(1, len(service_counts)):
                if service_counts[i-1] > 0:
                    service_ratio = service_counts[i] / service_counts[i-1]
                    service_growth_ratios.append(service_ratio)
                
                if time_values[i-1] > 0:
                    time_ratio = time_values[i] / time_values[i-1]
                    time_growth_ratios.append(time_ratio)
                
                if memory_values[i-1] > 0:
                    memory_ratio = memory_values[i] / memory_values[i-1]
                    memory_growth_ratios.append(memory_ratio)
            
            # 检查时间增长是否与服务增长成完美线性关系
            if len(service_growth_ratios) >= 2 and len(time_growth_ratios) >= 2:
                # 计算相关系数
                correlation = self._calculate_correlation(service_growth_ratios, time_growth_ratios)
                if correlation > 0.98:  # 相关系数过高，可能过于完美
                    self.issues.append(ValidationIssue(
                        severity='warning',
                        category='scalability',
                        message=f"时间增长与服务增长相关性过高 ({correlation:.3f})，可能存在假数据",
                        expected="<0.98",
                        actual=f"{correlation:.3f}"
                    ))
            
            # 检查内存增长是否过于平滑（正好是2倍增长）
            if len(memory_growth_ratios) >= 2:
                for ratio in memory_growth_ratios:
                    # 检查是否接近2的倍数（1.95-2.05之间）
                    if 1.95 <= ratio <= 2.05:
                        self.issues.append(ValidationIssue(
                            severity='warning',
                            category='scalability',
                            message=f"内存增长比例异常平滑 ({ratio:.3f})，正好接近2倍增长",
                            expected="更自然的增长曲线",
                            actual=f"{ratio:.3f}"
                        ))
    
    def _validate_smoothness(self, metrics: Dict[str, Any]):
        """检测数据平滑度（过于平滑可能表示假数据）"""
        # 检查CPU使用率是否有足够的波动
        cpu_avg = metrics.get('cpu_avg_percent', 0.0)
        cpu_max = metrics.get('cpu_max_percent', 0.0)
        
        if cpu_max > 0:
            cpu_variance = cpu_max - cpu_avg
            # 如果最大值和平均值差异很小，可能缺乏波动
            if cpu_variance < cpu_avg * 0.1 and cpu_avg > 5.0:  # 差异小于10%
                self.issues.append(ValidationIssue(
                    severity='info',
                    category='resource',
                    message=f"CPU使用率缺乏波动 (平均={cpu_avg:.2f}%, 最大={cpu_max:.2f}%)",
                    expected="有更明显的峰值分布",
                    actual=f"差异={cpu_variance:.2f}%"
                ))
        
        # 检查内存使用是否过于平滑
        memory_avg = metrics.get('memory_avg_mb', 0.0)
        memory_max = metrics.get('memory_max_mb', 0.0)
        
        if memory_max > 0 and memory_avg > 0:
            memory_variance = (memory_max - memory_avg) / memory_avg * 100
            # 如果差异小于5%，可能过于平滑
            if memory_variance < 5.0:
                self.issues.append(ValidationIssue(
                    severity='info',
                    category='resource',
                    message=f"内存使用过于平滑 (差异={memory_variance:.2f}%)",
                    expected=">5%",
                    actual=f"{memory_variance:.2f}%"
                ))
    
    def _validate_outliers(self, metrics: Dict[str, Any]):
        """检测异常值"""
        # 检查配置大小与服务数量的比例是否异常
        num_services = metrics.get('num_services', 0)
        config_size_kb = metrics.get('config_size_kb', 0.0)
        
        if num_services > 0 and config_size_kb > 0:
            size_per_service = config_size_kb / num_services
            
            # 如果每个服务的配置大小异常小或异常大
            if size_per_service < 0.01:  # 小于10字节
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='consistency',
                    message=f"每个服务的配置大小异常小: {size_per_service:.3f} KB",
                    expected=">0.01 KB",
                    actual=f"{size_per_service:.3f} KB"
                ))
            elif size_per_service > 1000:  # 大于1MB
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='consistency',
                    message=f"每个服务的配置大小异常大: {size_per_service:.3f} KB",
                    expected="<1000 KB",
                    actual=f"{size_per_service:.3f} KB"
                ))
        
        # 检查处理时间是否异常
        total_time = metrics.get('total_time', 0.0)
        num_services = metrics.get('num_services', 0)
        
        if num_services > 0 and total_time > 0:
            time_per_service = total_time / num_services
            
            # 如果每个服务处理时间异常长
            if time_per_service > 30.0:  # 超过30秒
                self.issues.append(ValidationIssue(
                    severity='warning',
                    category='scalability',
                    message=f"每个服务的处理时间异常长: {time_per_service:.3f}秒",
                    expected="<30秒",
                    actual=f"{time_per_service:.3f}秒"
                ))
            # 如果每个服务处理时间异常短（可能是缓存或跳过）
            elif time_per_service < 0.01:  # 小于10毫秒
                self.issues.append(ValidationIssue(
                    severity='info',
                    category='scalability',
                    message=f"每个服务的处理时间异常短: {time_per_service:.3f}秒（可能是缓存效应）",
                    expected=">0.01秒",
                    actual=f"{time_per_service:.3f}秒"
                ))
    
    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """计算两个列表的皮尔逊相关系数"""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        try:
            n = len(x)
            sum_x = sum(x)
            sum_y = sum(y)
            sum_xy = sum(x[i] * y[i] for i in range(n))
            sum_x2 = sum(x[i] ** 2 for i in range(n))
            sum_y2 = sum(y[i] ** 2 for i in range(n))
            
            numerator = n * sum_xy - sum_x * sum_y
            denominator = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))
            
            if denominator == 0:
                return 0.0
            
            return numerator / denominator
        except Exception as e:
            logger.debug(f"计算相关系数失败: {e}")
            return 0.0
    
    def get_summary(self) -> Dict[str, Any]:
        """获取验证摘要"""
        error_count = sum(1 for i in self.issues if i.severity == 'error')
        warning_count = sum(1 for i in self.issues if i.severity == 'warning')
        info_count = sum(1 for i in self.issues if i.severity == 'info')
        
        return {
            'total_issues': len(self.issues),
            'errors': error_count,
            'warnings': warning_count,
            'info': info_count,
            'is_valid': error_count == 0,
            'issues': [i.to_dict() for i in self.issues]
        }


def run_baseline_measurement(duration: float = 2.0) -> Dict[str, Any]:
    """
    运行基准测试，测量系统基础开销
    
    Args:
        duration: 基准测试持续时间（秒）
    
    Returns:
        基准测试结果
    """
    try:
        from evaluation.scalability.enhanced_resource_monitor import EnhancedSystemResourceMonitor
        
        monitor = EnhancedSystemResourceMonitor(sampling_interval=0.1)
        monitor.start_monitoring()
        
        import time
        time.sleep(duration)
        
        monitor.stop_monitoring()
        summary = monitor.get_summary()
        
        logger.info("基准测试完成")
        logger.info(f"  基准CPU使用: {summary.get('cpu_percent_avg', 0.0):.2f}%")
        logger.info(f"  基准内存使用: {summary.get('memory_used_mb_avg', 0.0):.2f} MB")
        
        return summary
    except Exception as e:
        logger.error(f"基准测试失败: {e}")
        return {}

