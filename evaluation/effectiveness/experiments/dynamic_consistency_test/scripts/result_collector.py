#!/usr/bin/env python3
"""
结果收集器模块
用于收集监控数据、日志和指标
"""

import asyncio
import aiohttp
import subprocess
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging
import re

class ResultCollector:
    """结果收集器"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化结果收集器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 监控配置
        self.monitoring_config = config['environment']['monitoring']
        self.prometheus_url = self.monitoring_config.get('prometheus', {}).get('url', 'http://localhost:9090')
        self.jaeger_url = self.monitoring_config.get('jaeger', {}).get('url', 'http://localhost:16686')
    
    async def collect_metrics(self, start_time: datetime, duration: int) -> Dict[str, Any]:
        """收集指定时间段的所有监控数据"""
        end_time = start_time + timedelta(seconds=duration)
        
        self.logger.info(f"收集监控数据: {start_time} 到 {end_time}")
        
        collected_data = {
            "collection_period": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration
            },
            "prometheus_metrics": {},
            "envoy_metrics": {},
            "jaeger_traces": [],
            "envoy_access_logs": [],
            "requests": []
        }
        
        try:
            # 并行收集不同类型的数据
            tasks = [
                self._collect_prometheus_metrics(start_time, end_time),
                self._collect_envoy_access_logs(start_time, end_time),
                self._collect_jaeger_traces(start_time, end_time),
                self._collect_kubernetes_events(start_time, end_time)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理收集结果
            if not isinstance(results[0], Exception):
                collected_data["prometheus_metrics"] = results[0]
            
            if not isinstance(results[1], Exception):
                collected_data["envoy_access_logs"] = results[1]
                collected_data["requests"] = self._parse_requests_from_logs(results[1])
            
            if not isinstance(results[2], Exception):
                collected_data["jaeger_traces"] = results[2]
            
            if not isinstance(results[3], Exception):
                collected_data["kubernetes_events"] = results[3]
            
        except Exception as e:
            self.logger.error(f"收集监控数据时发生异常: {e}")
        
        return collected_data
    
    async def _collect_prometheus_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """收集Prometheus指标"""
        metrics_config = self.config.get('data_collection', {}).get('prometheus_metrics', [])
        prometheus_data = {}
        
        async with aiohttp.ClientSession() as session:
            for metric_name in metrics_config:
                try:
                    # 构建Prometheus查询
                    query = self._build_prometheus_query(metric_name)
                    
                    # 查询范围数据
                    params = {
                        'query': query,
                        'start': start_time.timestamp(),
                        'end': end_time.timestamp(),
                        'step': '15s'  # 15秒间隔
                    }
                    
                    async with session.get(f"{self.prometheus_url}/api/v1/query_range", 
                                         params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            prometheus_data[metric_name] = self._process_prometheus_response(data)
                        else:
                            self.logger.warning(f"Prometheus查询失败: {metric_name}, 状态码: {response.status}")
                
                except Exception as e:
                    self.logger.error(f"收集Prometheus指标 {metric_name} 失败: {e}")
        
        return prometheus_data
    
    def _build_prometheus_query(self, metric_name: str) -> str:
        """构建Prometheus查询语句"""
        # 根据指标名称构建相应的查询
        if metric_name == "istio_requests_total":
            return 'sum(rate(istio_requests_total[1m])) by (source_app, destination_service_name, response_code)'
        elif metric_name == "istio_request_duration_milliseconds":
            return 'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket[1m])) by (le, destination_service_name))'
        elif metric_name == "envoy_cluster_upstream_rq_retry":
            return 'sum(rate(envoy_cluster_upstream_rq_retry[1m])) by (envoy_cluster_name)'
        elif metric_name == "envoy_cluster_upstream_rq_timeout":
            return 'sum(rate(envoy_cluster_upstream_rq_timeout[1m])) by (envoy_cluster_name)'
        elif metric_name == "envoy_http_ratelimit_rate_limited":
            return 'sum(rate(envoy_http_ratelimit_rate_limited[1m])) by (envoy_http_conn_manager_prefix)'
        else:
            return metric_name  # 默认直接使用指标名称
    
    def _process_prometheus_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """处理Prometheus响应数据"""
        processed_data = []
        
        if data.get('status') == 'success' and 'data' in data:
            result = data['data']['result']
            
            for series in result:
                metric_info = {
                    'metric': series.get('metric', {}),
                    'values': []
                }
                
                for timestamp, value in series.get('values', []):
                    metric_info['values'].append({
                        'timestamp': timestamp,
                        'value': float(value) if value != 'NaN' else 0
                    })
                
                processed_data.append(metric_info)
        
        return processed_data
    
    async def _collect_envoy_access_logs(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """收集Envoy访问日志"""
        access_logs = []
        
        try:
            # 获取Istio代理Pod列表
            result = subprocess.run([
                "kubectl", "get", "pods", "-l", "security.istio.io/tlsMode=istio", 
                "-o", "jsonpath={.items[*].metadata.name}"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                pod_names = result.stdout.strip().split()
                
                # 为每个Pod收集日志
                for pod_name in pod_names[:5]:  # 限制处理Pod数量
                    pod_logs = await self._collect_pod_envoy_logs(pod_name, start_time, end_time)
                    access_logs.extend(pod_logs)
            
        except Exception as e:
            self.logger.error(f"收集Envoy访问日志失败: {e}")
        
        return access_logs
    
    async def _collect_pod_envoy_logs(self, pod_name: str, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """收集单个Pod的Envoy日志"""
        logs = []
        
        try:
            # 使用kubectl logs获取日志
            since_time = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            result = subprocess.run([
                "kubectl", "logs", pod_name, "-c", "istio-proxy",
                "--since-time", since_time, "--tail", "1000"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                log_lines = result.stdout.strip().split('\n')
                
                for line in log_lines:
                    if line.strip():
                        log_entry = self._parse_envoy_log_line(line, pod_name)
                        if log_entry and self._is_log_in_timerange(log_entry, start_time, end_time):
                            logs.append(log_entry)
            
        except Exception as e:
            self.logger.error(f"收集Pod {pod_name} 日志失败: {e}")
        
        return logs
    
    def _parse_envoy_log_line(self, log_line: str, pod_name: str) -> Optional[Dict[str, Any]]:
        """解析Envoy日志行"""
        try:
            # 尝试解析JSON格式日志
            if log_line.startswith('{'):
                log_data = json.loads(log_line)
                return {
                    'pod_name': pod_name,
                    'timestamp': log_data.get('start_time'),
                    'method': log_data.get('method'),
                    'path': log_data.get('path'),
                    'status_code': log_data.get('response_code'),
                    'response_time': log_data.get('duration'),
                    'upstream_service_time': log_data.get('upstream_service_time'),
                    'bytes_received': log_data.get('bytes_received'),
                    'bytes_sent': log_data.get('bytes_sent'),
                    'user_agent': log_data.get('user_agent'),
                    'x_forwarded_for': log_data.get('x_forwarded_for'),
                    'upstream_host': log_data.get('upstream_host'),
                    'response_flags': log_data.get('response_flags')
                }
            else:
                # 解析文本格式日志 (简化实现)
                # 实际应根据具体的日志格式进行解析
                return self._parse_text_log_line(log_line, pod_name)
                
        except Exception as e:
            self.logger.debug(f"解析日志行失败: {e}")
            return None
    
    def _parse_text_log_line(self, log_line: str, pod_name: str) -> Optional[Dict[str, Any]]:
        """解析文本格式的Envoy日志"""
        # 简化的文本日志解析
        # 实际实现需要根据具体的日志格式进行调整
        
        # 示例格式: [2024-01-01T12:00:00.000Z] "GET /productpage HTTP/1.1" 200 - 0 1234 100 - "curl/7.68.0" "uuid" "productpage" "upstream_host"
        pattern = r'\[([^\]]+)\] "(\w+) ([^"]+) [^"]+" (\d+) [^"]+ (\d+) (\d+) (\d+) [^"]+ "([^"]*)" "([^"]*)" "([^"]*)" "([^"]*)"'
        
        match = re.match(pattern, log_line)
        if match:
            return {
                'pod_name': pod_name,
                'timestamp': match.group(1),
                'method': match.group(2),
                'path': match.group(3),
                'status_code': int(match.group(4)),
                'response_time': int(match.group(6)),
                'bytes_received': int(match.group(5)),
                'bytes_sent': int(match.group(7)),
                'user_agent': match.group(8),
                'request_id': match.group(9),
                'service': match.group(10),
                'upstream_host': match.group(11)
            }
        
        return None
    
    def _is_log_in_timerange(self, log_entry: Dict[str, Any], start_time: datetime, end_time: datetime) -> bool:
        """检查日志条目是否在指定时间范围内"""
        try:
            log_timestamp_str = log_entry.get('timestamp', '')
            if not log_timestamp_str:
                return False
            
            # 解析时间戳
            log_timestamp = datetime.fromisoformat(log_timestamp_str.replace('Z', '+00:00'))
            
            return start_time <= log_timestamp <= end_time
            
        except Exception:
            return False
    
    def _parse_requests_from_logs(self, envoy_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从Envoy日志中提取请求信息"""
        requests = []
        
        for log_entry in envoy_logs:
            if log_entry.get('method') and log_entry.get('status_code'):
                request_info = {
                    'timestamp': log_entry.get('timestamp'),
                    'method': log_entry.get('method'),
                    'path': log_entry.get('path'),
                    'status_code': log_entry.get('status_code'),
                    'response_time': log_entry.get('response_time', 0),
                    'upstream_service_time': log_entry.get('upstream_service_time', 0),
                    'pod_name': log_entry.get('pod_name'),
                    'upstream_host': log_entry.get('upstream_host'),
                    'user_agent': log_entry.get('user_agent')
                }
                
                # 尝试从upstream_host提取服务版本信息
                upstream_host = log_entry.get('upstream_host', '')
                if upstream_host:
                    # 简单的版本提取逻辑，实际可能需要更复杂的解析
                    if 'v1' in upstream_host:
                        request_info['upstream_service_version'] = 'v1'
                    elif 'v2' in upstream_host:
                        request_info['upstream_service_version'] = 'v2'
                    elif 'v3' in upstream_host:
                        request_info['upstream_service_version'] = 'v3'
                
                requests.append(request_info)
        
        return requests
    
    async def _collect_jaeger_traces(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """收集Jaeger追踪数据"""
        traces = []
        
        try:
            # 简化实现：通过Jaeger API查询traces
            start_micros = int(start_time.timestamp() * 1000000)
            end_micros = int(end_time.timestamp() * 1000000)
            
            async with aiohttp.ClientSession() as session:
                params = {
                    'service': 'productpage',  # 主要服务
                    'start': start_micros,
                    'end': end_micros,
                    'limit': 100
                }
                
                async with session.get(f"{self.jaeger_url}/api/traces", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        traces = data.get('data', [])
        
        except Exception as e:
            self.logger.error(f"收集Jaeger追踪数据失败: {e}")
        
        return traces
    
    async def _collect_kubernetes_events(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """收集Kubernetes事件"""
        events = []
        
        try:
            result = subprocess.run([
                "kubectl", "get", "events", "-o", "json",
                "--field-selector", "involvedObject.kind=Pod"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                events_data = json.loads(result.stdout)
                
                for event in events_data.get('items', []):
                    event_time_str = event.get('firstTimestamp') or event.get('eventTime')
                    if event_time_str:
                        event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
                        
                        if start_time <= event_time <= end_time:
                            events.append({
                                'timestamp': event_time_str,
                                'type': event.get('type'),
                                'reason': event.get('reason'),
                                'message': event.get('message'),
                                'object_name': event.get('involvedObject', {}).get('name'),
                                'object_kind': event.get('involvedObject', {}).get('kind'),
                                'namespace': event.get('involvedObject', {}).get('namespace')
                            })
        
        except Exception as e:
            self.logger.error(f"收集Kubernetes事件失败: {e}")
        
        return events
    
    async def export_collected_data(self, data: Dict[str, Any], output_path: str):
        """导出收集的数据"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            
            self.logger.info(f"数据已导出到: {output_path}")
            
        except Exception as e:
            self.logger.error(f"导出数据失败: {e}")
