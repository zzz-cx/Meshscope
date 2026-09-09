#!/usr/bin/env python3
"""
行为分析器模块
用于分析系统行为并检测与配置的不一致性
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Any, Tuple
import logging
from datetime import datetime, timedelta

class BehaviorAnalyzer:
    """行为分析器"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化行为分析器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 分析配置
        self.analysis_config = config.get('analysis', {})
        self.behavior_config = self.analysis_config.get('behavior_analysis', {})
        self.detection_config = self.analysis_config.get('detection_algorithms', {})
    
    async def analyze_behavior_change(self, 
                                    baseline_data: Dict[str, Any], 
                                    anomaly_data: Dict[str, Any],
                                    expected_detection: Dict[str, Any]) -> Dict[str, Any]:
        """分析行为变化并检测异常"""
        
        analysis_result = {
            "detection_success": False,
            "anomalies": [],
            "metrics": {},
            "analysis_details": {}
        }
        
        try:
            # 提取并处理数据
            baseline_metrics = self._extract_metrics(baseline_data)
            anomaly_metrics = self._extract_metrics(anomaly_data)
            
            analysis_result["metrics"] = {
                "baseline": baseline_metrics,
                "anomaly": anomaly_metrics
            }
            
            # 根据预期检测类型进行相应分析
            issue_type = expected_detection.get('issue_type', '')
            
            if issue_type == 'traffic_distribution_anomaly':
                anomalies = await self._analyze_traffic_distribution(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            elif issue_type == 'fault_injection_failure':
                anomalies = await self._analyze_fault_injection(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            elif issue_type == 'rate_limiting_failure':
                anomalies = await self._analyze_rate_limiting(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            elif issue_type == 'retry_policy_failure':
                anomalies = await self._analyze_retry_behavior(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            elif issue_type == 'circuit_breaker_failure':
                anomalies = await self._analyze_circuit_breaker(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            elif issue_type == 'timeout_policy_failure':
                anomalies = await self._analyze_timeout_behavior(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            else:
                anomalies = await self._generic_anomaly_detection(
                    baseline_metrics, anomaly_metrics, expected_detection
                )
            
            analysis_result["anomalies"] = anomalies
            analysis_result["detection_success"] = len(anomalies) > 0
            
        except Exception as e:
            self.logger.error(f"行为分析失败: {e}")
            analysis_result["error"] = str(e)
        
        return analysis_result
    
    def _extract_metrics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """从原始数据中提取关键指标"""
        metrics = {}
        
        # 提取请求数据
        requests = data.get('requests', [])
        if requests:
            df = pd.DataFrame(requests)
            
            # 基础指标
            metrics['total_requests'] = len(requests)
            metrics['success_rate'] = len(df[df['status_code'] < 400]) / len(df) if len(df) > 0 else 0
            metrics['error_rate'] = len(df[df['status_code'] >= 400]) / len(df) if len(df) > 0 else 0
            
            # 响应时间指标
            if 'response_time' in df.columns:
                response_times = pd.to_numeric(df['response_time'], errors='coerce').dropna()
                if not response_times.empty:
                    metrics['avg_response_time'] = response_times.mean()
                    metrics['p50_response_time'] = response_times.quantile(0.5)
                    metrics['p95_response_time'] = response_times.quantile(0.95)
                    metrics['p99_response_time'] = response_times.quantile(0.99)
            
            # 状态码分布
            status_distribution = df['status_code'].value_counts().to_dict()
            metrics['status_code_distribution'] = status_distribution
            
            # 版本分布（如果有）
            if 'upstream_service_version' in df.columns:
                version_distribution = df['upstream_service_version'].value_counts()
                total = version_distribution.sum()
                metrics['version_distribution'] = {
                    version: count/total for version, count in version_distribution.items()
                }
        
        # 提取Prometheus指标
        prometheus_data = data.get('prometheus_metrics', {})
        for metric_name, values in prometheus_data.items():
            if values:
                metrics[f'prometheus_{metric_name}'] = {
                    'avg': np.mean(values),
                    'max': np.max(values),
                    'min': np.min(values)
                }
        
        # 提取Envoy指标
        envoy_data = data.get('envoy_metrics', {})
        for metric_name, values in envoy_data.items():
            if values:
                metrics[f'envoy_{metric_name}'] = {
                    'sum': np.sum(values),
                    'avg': np.mean(values)
                }
        
        return metrics
    
    async def _analyze_traffic_distribution(self, 
                                          baseline: Dict[str, Any], 
                                          anomaly: Dict[str, Any],
                                          expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析流量分发异常"""
        anomalies = []
        
        # 获取基线和异常期间的版本分布
        baseline_dist = baseline.get('version_distribution', {})
        anomaly_dist = anomaly.get('version_distribution', {})
        
        if not baseline_dist or not anomaly_dist:
            return anomalies
        
        # 使用卡方检验检测分布变化
        algorithm_config = self.detection_config.get('traffic_distribution', {})
        significance_level = algorithm_config.get('significance_level', 0.05)
        
        # 准备数据进行卡方检验
        versions = set(baseline_dist.keys()) | set(anomaly_dist.keys())
        baseline_counts = [baseline_dist.get(v, 0) * baseline['total_requests'] for v in versions]
        anomaly_counts = [anomaly_dist.get(v, 0) * anomaly['total_requests'] for v in versions]
        
        # 执行卡方检验
        try:
            chi2_stat, p_value = stats.chisquare(anomaly_counts, baseline_counts)
            
            if p_value < significance_level:
                # 检测到显著差异
                anomaly_record = {
                    "type": "traffic_distribution_anomaly",
                    "severity": "high",
                    "description": "检测到流量分发与基线显著不同",
                    "details": {
                        "baseline_distribution": baseline_dist,
                        "anomaly_distribution": anomaly_dist,
                        "chi2_statistic": chi2_stat,
                        "p_value": p_value,
                        "significance_level": significance_level
                    },
                    "confidence": 1 - p_value,
                    "timestamp": datetime.now().isoformat()
                }
                
                # 计算偏差程度
                max_deviation = 0
                for version in versions:
                    baseline_pct = baseline_dist.get(version, 0)
                    anomaly_pct = anomaly_dist.get(version, 0)
                    deviation = abs(baseline_pct - anomaly_pct)
                    max_deviation = max(max_deviation, deviation)
                
                anomaly_record["details"]["max_deviation"] = max_deviation
                anomalies.append(anomaly_record)
                
                self.logger.info(f"检测到流量分发异常: 最大偏差 {max_deviation:.3f}")
                
        except Exception as e:
            self.logger.error(f"流量分发分析失败: {e}")
        
        return anomalies
    
    async def _analyze_fault_injection(self,
                                     baseline: Dict[str, Any],
                                     anomaly: Dict[str, Any], 
                                     expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析故障注入效果"""
        anomalies = []
        
        # 检查预期的故障注入指标
        expected_indicators = expected.get('detection_indicators', [])
        
        for indicator in expected_indicators:
            if 'delay_percentage' in indicator:
                # 分析延迟注入效果
                anomaly_found = self._check_delay_injection(baseline, anomaly, indicator)
                if anomaly_found:
                    anomalies.append(anomaly_found)
            
            elif 'abort_percentage' in indicator:
                # 分析错误注入效果
                anomaly_found = self._check_abort_injection(baseline, anomaly, indicator)
                if anomaly_found:
                    anomalies.append(anomaly_found)
        
        return anomalies
    
    def _check_delay_injection(self, baseline: Dict[str, Any], anomaly: Dict[str, Any], indicator: str) -> Dict[str, Any]:
        """检查延迟注入效果"""
        # 解析预期延迟百分比
        import re
        match = re.search(r'expected_delay_percentage:\s*(\d+)%', indicator)
        if not match:
            return None
        
        expected_delay_pct = int(match.group(1)) / 100
        
        # 获取响应时间数据
        baseline_avg_time = baseline.get('avg_response_time', 0)
        anomaly_avg_time = anomaly.get('avg_response_time', 0)
        
        # 预期注入2秒延迟后，平均响应时间应该显著增加
        expected_increase = 2000 * expected_delay_pct  # 毫秒
        actual_increase = anomaly_avg_time - baseline_avg_time
        
        # 如果实际增加量远小于预期，说明故障注入可能失效
        if actual_increase < expected_increase * 0.5:  # 允许50%的误差
            return {
                "type": "fault_injection_failure",
                "subtype": "delay_injection_ineffective",
                "severity": "high",
                "description": "延迟故障注入未按预期生效",
                "details": {
                    "expected_delay_percentage": expected_delay_pct,
                    "expected_time_increase_ms": expected_increase,
                    "actual_time_increase_ms": actual_increase,
                    "baseline_avg_time_ms": baseline_avg_time,
                    "anomaly_avg_time_ms": anomaly_avg_time
                },
                "confidence": 0.8,
                "timestamp": datetime.now().isoformat()
            }
        
        return None
    
    def _check_abort_injection(self, baseline: Dict[str, Any], anomaly: Dict[str, Any], indicator: str) -> Dict[str, Any]:
        """检查错误注入效果"""
        import re
        match = re.search(r'expected_abort_percentage:\s*(\d+)%', indicator)
        if not match:
            return None
        
        expected_abort_pct = int(match.group(1)) / 100
        
        # 获取错误率数据
        baseline_error_rate = baseline.get('error_rate', 0)
        anomaly_error_rate = anomaly.get('error_rate', 0)
        
        # 检查错误率是否按预期增加
        expected_error_rate = baseline_error_rate + expected_abort_pct
        
        if anomaly_error_rate < expected_error_rate * 0.5:  # 允许50%的误差
            return {
                "type": "fault_injection_failure",
                "subtype": "abort_injection_ineffective", 
                "severity": "high",
                "description": "错误故障注入未按预期生效",
                "details": {
                    "expected_abort_percentage": expected_abort_pct,
                    "baseline_error_rate": baseline_error_rate,
                    "expected_error_rate": expected_error_rate,
                    "actual_error_rate": anomaly_error_rate
                },
                "confidence": 0.8,
                "timestamp": datetime.now().isoformat()
            }
        
        return None
    
    async def _analyze_rate_limiting(self,
                                   baseline: Dict[str, Any],
                                   anomaly: Dict[str, Any],
                                   expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析限流策略效果"""
        anomalies = []
        
        # 检查429状态码（限流响应）的比例
        baseline_status = baseline.get('status_code_distribution', {})
        anomaly_status = anomaly.get('status_code_distribution', {})
        
        baseline_total = baseline.get('total_requests', 1)
        anomaly_total = anomaly.get('total_requests', 1)
        
        baseline_429_rate = baseline_status.get(429, 0) / baseline_total
        anomaly_429_rate = anomaly_status.get(429, 0) / anomaly_total
        
        # 如果异常期间429响应率显著低于基线，可能限流失效
        expected_indicators = expected.get('detection_indicators', [])
        for indicator in expected_indicators:
            if 'expected_429_rate' in indicator:
                import re
                match = re.search(r'expected_429_rate:\s*>\s*(\d+)%', indicator)
                if match:
                    expected_min_rate = int(match.group(1)) / 100
                    
                    if anomaly_429_rate < expected_min_rate:
                        anomaly_record = {
                            "type": "rate_limiting_failure",
                            "severity": "high", 
                            "description": "限流策略未按预期生效",
                            "details": {
                                "expected_min_429_rate": expected_min_rate,
                                "actual_429_rate": anomaly_429_rate,
                                "baseline_429_rate": baseline_429_rate
                            },
                            "confidence": 0.9,
                            "timestamp": datetime.now().isoformat()
                        }
                        anomalies.append(anomaly_record)
        
        return anomalies
    
    async def _analyze_retry_behavior(self,
                                    baseline: Dict[str, Any],
                                    anomaly: Dict[str, Any],
                                    expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析重试行为"""
        anomalies = []
        
        # 检查重试相关的Envoy指标
        baseline_retries = baseline.get('envoy_upstream_rq_retry', {}).get('sum', 0)
        anomaly_retries = anomaly.get('envoy_upstream_rq_retry', {}).get('sum', 0)
        
        # 在有故障的情况下，应该观察到重试
        baseline_error_rate = baseline.get('error_rate', 0)
        anomaly_error_rate = anomaly.get('error_rate', 0)
        
        # 如果错误率高但重试次数很少，可能重试策略失效
        if anomaly_error_rate > 0.1 and anomaly_retries < anomaly.get('total_requests', 0) * 0.1:
            anomaly_record = {
                "type": "retry_policy_failure",
                "severity": "medium",
                "description": "在高错误率情况下重试次数异常少",
                "details": {
                    "error_rate": anomaly_error_rate,
                    "retry_count": anomaly_retries,
                    "total_requests": anomaly.get('total_requests', 0),
                    "expected_retry_ratio": 0.1
                },
                "confidence": 0.7,
                "timestamp": datetime.now().isoformat()
            }
            anomalies.append(anomaly_record)
        
        return anomalies
    
    async def _analyze_circuit_breaker(self,
                                     baseline: Dict[str, Any],
                                     anomaly: Dict[str, Any], 
                                     expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析熔断器行为"""
        anomalies = []
        
        # 检查熔断器相关指标
        # 在高错误率情况下应该触发熔断
        anomaly_error_rate = anomaly.get('error_rate', 0)
        
        # 检查是否有熔断器弹出事件的指标
        ejection_events = anomaly.get('envoy_cluster_upstream_ejections', {}).get('sum', 0)
        
        # 如果错误率很高但没有熔断事件，可能熔断器失效
        if anomaly_error_rate > 0.8 and ejection_events == 0:
            anomaly_record = {
                "type": "circuit_breaker_failure",
                "severity": "high",
                "description": "高错误率下熔断器未触发",
                "details": {
                    "error_rate": anomaly_error_rate,
                    "ejection_events": ejection_events,
                    "expected_ejection_threshold": 0.8
                },
                "confidence": 0.8,
                "timestamp": datetime.now().isoformat()
            }
            anomalies.append(anomaly_record)
        
        return anomalies
    
    async def _analyze_timeout_behavior(self,
                                      baseline: Dict[str, Any],
                                      anomaly: Dict[str, Any],
                                      expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析超时行为"""
        anomalies = []
        
        # 检查响应时间分布
        anomaly_p99_time = anomaly.get('p99_response_time', 0)
        
        # 如果配置了3秒超时，但P99响应时间远大于3秒，说明超时可能失效
        configured_timeout = 3000  # 3秒，毫秒
        
        if anomaly_p99_time > configured_timeout * 1.5:  # 超过配置超时的1.5倍
            # 检查是否有超时相关的状态码
            status_dist = anomaly.get('status_code_distribution', {})
            timeout_responses = status_dist.get(504, 0) + status_dist.get(408, 0)
            
            if timeout_responses < anomaly.get('total_requests', 0) * 0.1:
                anomaly_record = {
                    "type": "timeout_policy_failure",
                    "severity": "medium",
                    "description": "响应时间超过配置超时但未触发超时机制",
                    "details": {
                        "configured_timeout_ms": configured_timeout,
                        "p99_response_time_ms": anomaly_p99_time,
                        "timeout_responses": timeout_responses,
                        "total_requests": anomaly.get('total_requests', 0)
                    },
                    "confidence": 0.7,
                    "timestamp": datetime.now().isoformat()
                }
                anomalies.append(anomaly_record)
        
        return anomalies
    
    async def _generic_anomaly_detection(self,
                                       baseline: Dict[str, Any],
                                       anomaly: Dict[str, Any],
                                       expected: Dict[str, Any]) -> List[Dict[str, Any]]:
        """通用异常检测"""
        anomalies = []
        
        # 使用统计方法检测显著变化
        threshold = self.behavior_config.get('anomaly_threshold', 0.15)
        
        # 检查关键指标的变化
        key_metrics = ['success_rate', 'error_rate', 'avg_response_time']
        
        for metric in key_metrics:
            baseline_value = baseline.get(metric, 0)
            anomaly_value = anomaly.get(metric, 0)
            
            if baseline_value > 0:
                change_ratio = abs(anomaly_value - baseline_value) / baseline_value
                
                if change_ratio > threshold:
                    anomaly_record = {
                        "type": "generic_behavior_anomaly",
                        "severity": "medium",
                        "description": f"指标 {metric} 发生显著变化",
                        "details": {
                            "metric": metric,
                            "baseline_value": baseline_value,
                            "anomaly_value": anomaly_value,
                            "change_ratio": change_ratio,
                            "threshold": threshold
                        },
                        "confidence": min(0.9, change_ratio),
                        "timestamp": datetime.now().isoformat()
                    }
                    anomalies.append(anomaly_record)
        
        return anomalies
