#!/usr/bin/env python3
"""
Envoy 访问日志解析工具

主要功能：
1. 解析 Envoy access log 条目
2. 统计请求分布（pod 命中数量）
3. 提取状态码、响应时间等指标
4. 验证权重分布是否符合预期
"""

import re
import json
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict, Counter
import statistics

@dataclass
class LogEntry:
    """单条访问日志条目"""
    timestamp: str
    method: str
    path: str
    protocol: str
    status_code: int
    response_size: int
    request_time: float
    upstream_host: str
    user_agent: str
    x_forwarded_for: str
    request_id: str
    pod_name: str
    raw_log: str
    
    @property
    def is_success(self) -> bool:
        """判断请求是否成功"""
        return 200 <= self.status_code < 400
    
    @property
    def is_error(self) -> bool:
        """判断请求是否错误"""
        return self.status_code >= 400

class EnvoyLogParser:
    """Envoy 访问日志解析器"""
    
    # 默认的 Envoy access log 格式正则表达式
    # 格式: [%START_TIME%] "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %PROTOCOL%" 
    #       %RESPONSE_CODE% %RESPONSE_FLAGS% %BYTES_RECEIVED% %BYTES_SENT% %DURATION% 
    #       %RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)% "%REQ(X-FORWARDED-FOR)%" "%REQ(USER-AGENT)%" 
    #       "%REQ(X-REQUEST-ID)%" "%REQ(:AUTHORITY)%" "%UPSTREAM_HOST%"
    DEFAULT_LOG_PATTERN = re.compile(
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\w+)\s+(?P<path>[^\s]+)\s+(?P<protocol>[^"]+)"\s+'
        r'(?P<status_code>\d+)\s+(?P<response_flags>[^\s]+)\s+'
        r'(?P<bytes_received>\d+)\s+(?P<bytes_sent>\d+)\s+(?P<duration>\d+)\s+'
        r'(?P<upstream_service_time>[^\s]+)\s+'
        r'"(?P<x_forwarded_for>[^"]*)"\s+'
        r'"(?P<user_agent>[^"]*)"\s+'
        r'"(?P<request_id>[^"]*)"\s+'
        r'"(?P<authority>[^"]*)"\s+'
        r'"(?P<upstream_host>[^"]*)"'
    )
    
    # 简化的日志格式（只包含关键信息）
    SIMPLE_LOG_PATTERN = re.compile(
        r'(?P<method>GET|POST|PUT|DELETE|HEAD|OPTIONS)\s+'
        r'(?P<path>/[^\s]*)\s+'
        r'HTTP/[^\s]+.*?'
        r'(?P<status_code>[1-5]\d{2})'
    )
    
    def __init__(self, custom_pattern: Optional[str] = None):
        """
        初始化日志解析器
        
        Args:
            custom_pattern: 自定义正则表达式模式
        """
        if custom_pattern:
            self.log_pattern = re.compile(custom_pattern)
        else:
            self.log_pattern = self.DEFAULT_LOG_PATTERN
    
    def parse_log_entry(self, log_line: str, pod_name: str = "") -> Optional[LogEntry]:
        """
        解析单条访问日志
        
        Args:
            log_line: 日志行内容
            pod_name: 所属 pod 名称
            
        Returns:
            LogEntry 对象或 None（解析失败）
        """
        try:
            # 尝试标准格式解析
            match = self.log_pattern.match(log_line.strip())
            if match:
                data = match.groupdict()
                return LogEntry(
                    timestamp=data.get('timestamp', ''),
                    method=data.get('method', ''),
                    path=data.get('path', ''),
                    protocol=data.get('protocol', ''),
                    status_code=int(data.get('status_code', 0)),
                    response_size=int(data.get('bytes_sent', 0)),
                    request_time=float(data.get('duration', 0)) / 1000.0,  # 转换为秒
                    upstream_host=data.get('upstream_host', ''),
                    user_agent=data.get('user_agent', ''),
                    x_forwarded_for=data.get('x_forwarded_for', ''),
                    request_id=data.get('request_id', ''),
                    pod_name=pod_name,
                    raw_log=log_line
                )
            
            # 尝试简化格式解析
            match = self.SIMPLE_LOG_PATTERN.search(log_line)
            if match:
                data = match.groupdict()
                return LogEntry(
                    timestamp=datetime.now().isoformat(),
                    method=data.get('method', ''),
                    path=data.get('path', ''),
                    protocol='HTTP/1.1',
                    status_code=int(data.get('status_code', 0)),
                    response_size=0,
                    request_time=0.0,
                    upstream_host='',
                    user_agent='',
                    x_forwarded_for='',
                    request_id='',
                    pod_name=pod_name,
                    raw_log=log_line
                )
                
        except (ValueError, AttributeError) as e:
            print(f"⚠️ 解析日志失败: {e}")
            return None
        
        return None
    
    def parse_logs_batch(self, logs_dict: Dict[str, str]) -> Dict[str, List[LogEntry]]:
        """
        批量解析多个 pod 的日志
        
        Args:
            logs_dict: {pod_name: log_content} 格式的日志字典
            
        Returns:
            {pod_name: [LogEntry]} 格式的解析结果
        """
        parsed_logs = {}
        
        for pod_name, log_content in logs_dict.items():
            entries = []
            
            if not log_content or log_content.startswith('[ERROR]'):
                print(f"⚠️ Pod {pod_name} 日志为空或有错误")
                parsed_logs[pod_name] = entries
                continue
            
            lines = log_content.strip().split('\n')
            for line in lines:
                if line.strip():  # 跳过空行
                    entry = self.parse_log_entry(line, pod_name)
                    if entry:
                        entries.append(entry)
            
            parsed_logs[pod_name] = entries
            print(f"📊 Pod {pod_name}: 解析到 {len(entries)} 条访问日志")
        
        return parsed_logs
    
    def analyze_distribution(self, parsed_logs: Dict[str, List[LogEntry]], 
                           service_name: str) -> Dict[str, any]:
        """
        分析请求分布情况
        
        Args:
            parsed_logs: 解析后的日志数据
            service_name: 服务名称
            
        Returns:
            分布分析结果
        """
        total_requests = 0
        pod_distribution = Counter()
        version_distribution = Counter()
        status_code_distribution = Counter()
        response_times = []
        
        # 统计各个指标
        for pod_name, entries in parsed_logs.items():
            request_count = len(entries)
            total_requests += request_count
            pod_distribution[pod_name] = request_count
            
            # 从 pod 名称提取版本信息（例如：reviews-v2-xxx -> v2）
            version = self._extract_version_from_pod(pod_name)
            if version:
                version_distribution[version] += request_count
            
            # 统计状态码和响应时间
            for entry in entries:
                status_code_distribution[entry.status_code] += 1
                if entry.request_time > 0:
                    response_times.append(entry.request_time)
        
        # 计算百分比
        pod_percentages = {}
        version_percentages = {}
        
        if total_requests > 0:
            for pod, count in pod_distribution.items():
                pod_percentages[pod] = count / total_requests
            
            for version, count in version_distribution.items():
                version_percentages[version] = count / total_requests
        
        # 计算响应时间统计
        response_time_stats = {}
        if response_times:
            response_time_stats = {
                'avg': statistics.mean(response_times),
                'median': statistics.median(response_times),
                'min': min(response_times),
                'max': max(response_times),
                'p95': self._percentile(response_times, 95),
                'p99': self._percentile(response_times, 99)
            }
        
        return {
            'service_name': service_name,
            'total_requests': total_requests,
            'pod_distribution': dict(pod_distribution),
            'pod_percentages': pod_percentages,
            'version_distribution': dict(version_distribution),
            'version_percentages': version_percentages,
            'status_code_distribution': dict(status_code_distribution),
            'response_time_stats': response_time_stats,
            'success_rate': self._calculate_success_rate(status_code_distribution),
            'error_rate': self._calculate_error_rate(status_code_distribution)
        }
    
    def verify_weight_distribution(self, distribution_result: Dict[str, any], 
                                 expected_weights: Dict[str, float],
                                 margin_of_error: float = 0.1) -> Dict[str, any]:
        """
        验证权重分布是否符合预期
        
        Args:
            distribution_result: analyze_distribution 的结果
            expected_weights: 期望的权重分布 {version: weight}
            margin_of_error: 容错率
            
        Returns:
            验证结果
        """
        version_percentages = distribution_result.get('version_percentages', {})
        total_requests = distribution_result.get('total_requests', 0)
        
        verification_results = {}
        overall_passed = True
        
        for version, expected_weight in expected_weights.items():
            actual_percentage = version_percentages.get(version, 0.0)
            deviation = abs(actual_percentage - expected_weight)
            passed = deviation <= margin_of_error
            
            if not passed:
                overall_passed = False
            
            verification_results[version] = {
                'expected_weight': expected_weight,
                'actual_percentage': actual_percentage,
                'deviation': deviation,
                'passed': passed,
                'request_count': distribution_result['version_distribution'].get(version, 0)
            }
        
        return {
            'overall_passed': overall_passed,
            'total_requests': total_requests,
            'margin_of_error': margin_of_error,
            'version_results': verification_results,
            'summary': self._generate_weight_summary(verification_results, overall_passed)
        }
    
    def _extract_version_from_pod(self, pod_name: str) -> Optional[str]:
        """从 pod 名称提取版本信息"""
        # 匹配模式：servicename-v1-xxx, servicename-v2-xxx
        match = re.search(r'-v(\d+)-', pod_name)
        if match:
            return f"v{match.group(1)}"
        
        # 匹配模式：servicename-v1, servicename-v2  
        match = re.search(r'-v(\d+)$', pod_name)
        if match:
            return f"v{match.group(1)}"
        
        return None
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """计算百分位数"""
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        index = (percentile / 100.0) * (len(sorted_data) - 1)
        
        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))
    
    def _calculate_success_rate(self, status_distribution: Counter) -> float:
        """计算成功率"""
        total = sum(status_distribution.values())
        if total == 0:
            return 0.0
        
        success_count = sum(count for status, count in status_distribution.items() 
                          if 200 <= status < 400)
        return success_count / total
    
    def _calculate_error_rate(self, status_distribution: Counter) -> float:
        """计算错误率"""
        return 1.0 - self._calculate_success_rate(status_distribution)
    
    def _generate_weight_summary(self, version_results: Dict[str, Dict], 
                                overall_passed: bool) -> str:
        """生成权重验证摘要"""
        # 构建详细的分布信息
        distribution_details = []
        for version, result in version_results.items():
            request_count = result['request_count']
            actual_percentage = result['actual_percentage']
            expected_weight = result['expected_weight']
            status = "✅" if result['passed'] else "❌"
            
            distribution_details.append(
                f"{status} {version}: {request_count}个请求 "
                f"({actual_percentage:.1%}, 期望{expected_weight:.1%})"
            )
        
        distribution_summary = " | ".join(distribution_details)
        
        if overall_passed:
            return f"✅ 权重分布验证通过 - {distribution_summary}"
        else:
            failed_versions = [v for v, r in version_results.items() if not r['passed']]
            return f"❌ 权重分布验证失败 - {distribution_summary} (偏差超出容错范围: {', '.join(failed_versions)})"

# 工具函数
def parse_logs_from_files(log_files: List[str], parser: Optional[EnvoyLogParser] = None) -> Dict[str, List[LogEntry]]:
    """
    从文件中解析日志
    
    Args:
        log_files: 日志文件路径列表
        parser: 日志解析器实例
        
    Returns:
        解析结果
    """
    if parser is None:
        parser = EnvoyLogParser()
    
    logs_dict = {}
    
    for file_path in log_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 从文件名提取 pod 名称
            import os
            filename = os.path.basename(file_path)
            pod_name = filename.replace('.log', '').split('_')[-1]  # 假设格式为 case_001_reviews_v2_pod-name.log
            
            logs_dict[pod_name] = content
            
        except Exception as e:
            print(f"⚠️ 读取日志文件 {file_path} 失败: {e}")
    
    return parser.parse_logs_batch(logs_dict) 