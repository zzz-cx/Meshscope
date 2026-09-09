#!/usr/bin/env python3
"""
动态检测方法实现
仅进行运行时流量验证与行为分析
"""

import asyncio
import aiohttp
import subprocess
import json
import time
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path
import logging
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

class DynamicOnlyDetector:
    """动态检测器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化动态检测器"""
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 环境配置
        self.cluster_config = self.config.get('environment', {}).get('cluster_config', {})
        self.ingress_url = self.cluster_config.get('ingress_url', 'http://localhost')
        self.test_app = self.cluster_config.get('test_app', 'bookinfo')
        
        # 监控配置
        self.monitoring_config = self.config.get('environment', {}).get('monitoring', {})
        self.prometheus_url = self.monitoring_config.get('prometheus', {}).get('url', 'http://localhost:9090')
        
        # 检测配置
        self.detection_config = self.config.get('detection', {})
        self.traffic_config = self.detection_config.get('traffic_generation', {})
        self.analysis_config = self.detection_config.get('behavior_analysis', {})
    
    async def detect_faults(self, config_files: List[str]) -> Dict[str, Any]:
        """检测配置文件中的故障"""
        detection_result = {
            "method": "dynamic_only",
            "start_time": datetime.now().isoformat(),
            "config_files": config_files,
            "detected_faults": [],
            "summary": {
                "total_files": len(config_files),
                "files_with_faults": 0,
                "total_faults": 0,
                "fault_types": {}
            }
        }
        
        try:
            # 应用配置到测试环境
            await self._apply_configs(config_files)
            
            # 等待配置生效
            await asyncio.sleep(10)
            
            # 收集基线数据
            baseline_data = await self._collect_baseline_data()
            
            # 生成测试流量
            await self._generate_test_traffic()
            
            # 收集运行时数据
            runtime_data = await self._collect_runtime_data()
            
            # 分析行为异常
            for config_file in config_files:
                file_faults = await self._analyze_config_behavior(config_file, baseline_data, runtime_data)
                detection_result["detected_faults"].extend(file_faults)
            
            # 计算统计信息
            detection_result["summary"]["files_with_faults"] = len(set(
                fault["config_file"] for fault in detection_result["detected_faults"]
            ))
            detection_result["summary"]["total_faults"] = len(detection_result["detected_faults"])
            
            # 统计故障类型
            for fault in detection_result["detected_faults"]:
                fault_type = fault["fault_type"]
                detection_result["summary"]["fault_types"][fault_type] = \
                    detection_result["summary"]["fault_types"].get(fault_type, 0) + 1
            
        except Exception as e:
            self.logger.error(f"动态检测过程中发生错误: {e}")
            detection_result["error"] = str(e)
        
        finally:
            # 清理配置
            await self._cleanup_configs(config_files)
        
        detection_result["end_time"] = datetime.now().isoformat()
        return detection_result
    
    async def _apply_configs(self, config_files: List[str]):
        """应用配置到测试环境"""
        self.logger.info("应用配置到测试环境")
        
        for config_file in config_files:
            try:
                result = subprocess.run(
                    ["kubectl", "apply", "-f", config_file],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.logger.info(f"配置应用成功: {config_file}")
                else:
                    self.logger.error(f"配置应用失败: {config_file}, {result.stderr}")
                    
            except Exception as e:
                self.logger.error(f"应用配置时发生异常: {e}")
    
    async def _collect_baseline_data(self) -> Dict[str, Any]:
        """收集基线数据"""
        self.logger.info("收集基线数据")
        
        baseline_duration = 60  # 1分钟基线数据收集
        
        # 生成少量基线流量
        await self._generate_traffic(duration=baseline_duration, qps=1)
        
        # 收集指标
        baseline_data = await self._collect_metrics(baseline_duration)
        
        return baseline_data
    
    async def _generate_test_traffic(self):
        """生成测试流量"""
        self.logger.info("生成测试流量")
        
        test_duration = 180  # 3分钟测试流量
        test_qps = self.traffic_config.get('qps', 5)
        
        await self._generate_traffic(duration=test_duration, qps=test_qps)
    
    async def _generate_traffic(self, duration: int, qps: int):
        """生成指定持续时间和QPS的流量"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            # 创建多个并发请求任务
            for i in range(qps):
                task = asyncio.create_task(
                    self._traffic_worker(session, duration)
                )
                tasks.append(task)
            
            # 等待所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _traffic_worker(self, session: aiohttp.ClientSession, duration: int):
        """单个流量工作器"""
        start_time = time.time()
        request_count = 0
        
        while time.time() - start_time < duration:
            try:
                # 发送请求到测试应用
                url = f"{self.ingress_url}/productpage"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    request_count += 1
                    
                    # 记录请求结果
                    self.logger.debug(f"请求 {request_count}: {response.status}")
                
                # 控制请求频率
                await asyncio.sleep(1.0 / 5)  # 每个worker每秒5个请求
                
            except Exception as e:
                self.logger.error(f"流量生成错误: {e}")
                await asyncio.sleep(1)
        
        self.logger.info(f"流量工作器完成，共发送 {request_count} 个请求")
    
    async def _collect_runtime_data(self) -> Dict[str, Any]:
        """收集运行时数据"""
        self.logger.info("收集运行时数据")
        
        collection_duration = 120  # 2分钟数据收集
        
        runtime_data = await self._collect_metrics(collection_duration)
        
        return runtime_data
    
    async def _collect_metrics(self, duration: int) -> Dict[str, Any]:
        """收集监控指标"""
        metrics_data = {
            "collection_duration": duration,
            "prometheus_metrics": {},
            "envoy_metrics": {},
            "kubernetes_events": []
        }
        
        try:
            # 收集Prometheus指标
            metrics_data["prometheus_metrics"] = await self._collect_prometheus_metrics()
            
            # 收集Envoy指标
            metrics_data["envoy_metrics"] = await self._collect_envoy_metrics()
            
            # 收集Kubernetes事件
            metrics_data["kubernetes_events"] = await self._collect_kubernetes_events()
            
        except Exception as e:
            self.logger.error(f"收集指标时发生错误: {e}")
        
        return metrics_data
    
    async def _collect_prometheus_metrics(self) -> Dict[str, Any]:
        """收集Prometheus指标"""
        prometheus_data = {}
        
        async with aiohttp.ClientSession() as session:
            # 定义要收集的指标
            metrics_queries = {
                "istio_requests_total": 'sum(rate(istio_requests_total[1m])) by (source_app, destination_service_name, response_code)',
                "istio_request_duration_milliseconds": 'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket[1m])) by (le, destination_service_name))',
                "envoy_cluster_upstream_rq_retry": 'sum(rate(envoy_cluster_upstream_rq_retry[1m])) by (envoy_cluster_name)',
                "envoy_cluster_upstream_rq_timeout": 'sum(rate(envoy_cluster_upstream_rq_timeout[1m])) by (envoy_cluster_name)',
                "envoy_http_ratelimit_rate_limited": 'sum(rate(envoy_http_ratelimit_rate_limited[1m])) by (envoy_http_conn_manager_prefix)'
            }
            
            for metric_name, query in metrics_queries.items():
                try:
                    params = {
                        'query': query,
                        'time': int(time.time())
                    }
                    
                    async with session.get(f"{self.prometheus_url}/api/v1/query", params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            prometheus_data[metric_name] = data.get('data', {}).get('result', [])
                        else:
                            self.logger.warning(f"Prometheus查询失败: {metric_name}")
                            
                except Exception as e:
                    self.logger.error(f"收集Prometheus指标 {metric_name} 失败: {e}")
        
        return prometheus_data
    
    async def _collect_envoy_metrics(self) -> Dict[str, Any]:
        """收集Envoy指标"""
        envoy_data = {}
        
        try:
            # 获取Envoy代理Pod列表
            result = subprocess.run([
                "kubectl", "get", "pods", "-l", "security.istio.io/tlsMode=istio",
                "-o", "jsonpath={.items[*].metadata.name}"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                pod_names = result.stdout.strip().split()
                
                # 收集每个Pod的Envoy指标
                for pod_name in pod_names[:3]:  # 限制处理Pod数量
                    pod_metrics = await self._collect_pod_envoy_metrics(pod_name)
                    envoy_data[pod_name] = pod_metrics
                    
        except Exception as e:
            self.logger.error(f"收集Envoy指标失败: {e}")
        
        return envoy_data
    
    async def _collect_pod_envoy_metrics(self, pod_name: str) -> Dict[str, Any]:
        """收集单个Pod的Envoy指标"""
        pod_metrics = {}
        
        try:
            # 通过kubectl port-forward访问Envoy管理接口
            # 这里简化实现，实际应该通过port-forward或直接访问
            result = subprocess.run([
                "kubectl", "exec", pod_name, "-c", "istio-proxy",
                "--", "curl", "-s", "localhost:15000/stats"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                # 解析Envoy统计信息
                stats_lines = result.stdout.strip().split('\n')
                for line in stats_lines:
                    if ':' in line:
                        metric_name, value = line.split(':', 1)
                        pod_metrics[metric_name.strip()] = value.strip()
                        
        except Exception as e:
            self.logger.error(f"收集Pod {pod_name} Envoy指标失败: {e}")
        
        return pod_metrics
    
    async def _collect_kubernetes_events(self) -> List[Dict[str, Any]]:
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
                    events.append({
                        'timestamp': event.get('firstTimestamp'),
                        'type': event.get('type'),
                        'reason': event.get('reason'),
                        'message': event.get('message'),
                        'object_name': event.get('involvedObject', {}).get('name')
                    })
                    
        except Exception as e:
            self.logger.error(f"收集Kubernetes事件失败: {e}")
        
        return events
    
    async def _analyze_config_behavior(self, config_file: str, baseline_data: Dict[str, Any], 
                                     runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析配置行为"""
        faults = []
        
        try:
            # 分析流量分发异常
            traffic_faults = await self._analyze_traffic_distribution(config_file, baseline_data, runtime_data)
            faults.extend(traffic_faults)
            
            # 分析错误率异常
            error_faults = await self._analyze_error_rates(config_file, baseline_data, runtime_data)
            faults.extend(error_faults)
            
            # 分析响应时间异常
            latency_faults = await self._analyze_response_latency(config_file, baseline_data, runtime_data)
            faults.extend(latency_faults)
            
            # 分析重试行为异常
            retry_faults = await self._analyze_retry_behavior(config_file, baseline_data, runtime_data)
            faults.extend(retry_faults)
            
            # 分析熔断器行为异常
            circuit_breaker_faults = await self._analyze_circuit_breaker_behavior(config_file, baseline_data, runtime_data)
            faults.extend(circuit_breaker_faults)
            
            # 分析限流行为异常
            rate_limit_faults = await self._analyze_rate_limit_behavior(config_file, baseline_data, runtime_data)
            faults.extend(rate_limit_faults)
            
        except Exception as e:
            self.logger.error(f"分析配置行为时发生错误: {e}")
        
        return faults
    
    async def _analyze_traffic_distribution(self, config_file: str, baseline_data: Dict[str, Any], 
                                          runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析流量分发异常"""
        faults = []
        
        try:
            # 从Prometheus指标中提取流量分发数据
            baseline_metrics = baseline_data.get('prometheus_metrics', {})
            runtime_metrics = runtime_data.get('prometheus_metrics', {})
            
            # 分析请求分布
            baseline_requests = baseline_metrics.get('istio_requests_total', [])
            runtime_requests = runtime_metrics.get('istio_requests_total', [])
            
            # 检查是否有明显的流量分发异常
            if self._detect_traffic_anomaly(baseline_requests, runtime_requests):
                fault = {
                    "config_file": config_file,
                    "fault_type": "traffic_distribution_anomaly",
                    "severity": "high",
                    "description": "检测到流量分发异常",
                    "details": {
                        "baseline_requests": len(baseline_requests),
                        "runtime_requests": len(runtime_requests),
                        "anomaly_type": "unexpected_traffic_pattern"
                    },
                    "confidence": 0.8,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析流量分发时发生错误: {e}")
        
        return faults
    
    async def _analyze_error_rates(self, config_file: str, baseline_data: Dict[str, Any], 
                                 runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析错误率异常"""
        faults = []
        
        try:
            # 分析5xx错误率
            baseline_5xx_rate = self._calculate_error_rate(baseline_data, '5xx')
            runtime_5xx_rate = self._calculate_error_rate(runtime_data, '5xx')
            
            # 如果运行时错误率显著高于基线
            if runtime_5xx_rate > baseline_5xx_rate * 2:
                fault = {
                    "config_file": config_file,
                    "fault_type": "error_rate_anomaly",
                    "severity": "high",
                    "description": f"错误率异常升高: {runtime_5xx_rate:.2%}",
                    "details": {
                        "baseline_5xx_rate": baseline_5xx_rate,
                        "runtime_5xx_rate": runtime_5xx_rate,
                        "increase_factor": runtime_5xx_rate / baseline_5xx_rate if baseline_5xx_rate > 0 else float('inf')
                    },
                    "confidence": 0.85,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析错误率时发生错误: {e}")
        
        return faults
    
    async def _analyze_response_latency(self, config_file: str, baseline_data: Dict[str, Any], 
                                      runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析响应时间异常"""
        faults = []
        
        try:
            # 分析P95响应时间
            baseline_p95 = self._calculate_p95_latency(baseline_data)
            runtime_p95 = self._calculate_p95_latency(runtime_data)
            
            # 如果运行时延迟显著高于基线
            if runtime_p95 > baseline_p95 * 1.5:
                fault = {
                    "config_file": config_file,
                    "fault_type": "latency_anomaly",
                    "severity": "medium",
                    "description": f"响应时间异常升高: {runtime_p95:.2f}ms",
                    "details": {
                        "baseline_p95_latency": baseline_p95,
                        "runtime_p95_latency": runtime_p95,
                        "increase_factor": runtime_p95 / baseline_p95 if baseline_p95 > 0 else float('inf')
                    },
                    "confidence": 0.75,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析响应时间时发生错误: {e}")
        
        return faults
    
    async def _analyze_retry_behavior(self, config_file: str, baseline_data: Dict[str, Any], 
                                    runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析重试行为异常"""
        faults = []
        
        try:
            # 分析重试指标
            baseline_retries = self._calculate_retry_rate(baseline_data)
            runtime_retries = self._calculate_retry_rate(runtime_data)
            
            # 如果重试率异常
            if runtime_retries > baseline_retries * 3:
                fault = {
                    "config_file": config_file,
                    "fault_type": "retry_behavior_anomaly",
                    "severity": "medium",
                    "description": f"重试率异常升高: {runtime_retries:.2%}",
                    "details": {
                        "baseline_retry_rate": baseline_retries,
                        "runtime_retry_rate": runtime_retries,
                        "increase_factor": runtime_retries / baseline_retries if baseline_retries > 0 else float('inf')
                    },
                    "confidence": 0.7,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析重试行为时发生错误: {e}")
        
        return faults
    
    async def _analyze_circuit_breaker_behavior(self, config_file: str, baseline_data: Dict[str, Any], 
                                              runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析熔断器行为异常"""
        faults = []
        
        try:
            # 分析熔断器弹出事件
            baseline_ejections = self._calculate_circuit_breaker_ejections(baseline_data)
            runtime_ejections = self._calculate_circuit_breaker_ejections(runtime_data)
            
            # 如果熔断器频繁弹出
            if runtime_ejections > baseline_ejections * 2:
                fault = {
                    "config_file": config_file,
                    "fault_type": "circuit_breaker_anomaly",
                    "severity": "high",
                    "description": f"熔断器频繁弹出: {runtime_ejections} 次",
                    "details": {
                        "baseline_ejections": baseline_ejections,
                        "runtime_ejections": runtime_ejections,
                        "increase_factor": runtime_ejections / baseline_ejections if baseline_ejections > 0 else float('inf')
                    },
                    "confidence": 0.8,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析熔断器行为时发生错误: {e}")
        
        return faults
    
    async def _analyze_rate_limit_behavior(self, config_file: str, baseline_data: Dict[str, Any], 
                                         runtime_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分析限流行为异常"""
        faults = []
        
        try:
            # 分析限流指标
            baseline_rate_limited = self._calculate_rate_limit_hits(baseline_data)
            runtime_rate_limited = self._calculate_rate_limit_hits(runtime_data)
            
            # 如果限流过于频繁
            if runtime_rate_limited > baseline_rate_limited * 5:
                fault = {
                    "config_file": config_file,
                    "fault_type": "rate_limit_anomaly",
                    "severity": "medium",
                    "description": f"限流过于频繁: {runtime_rate_limited} 次",
                    "details": {
                        "baseline_rate_limited": baseline_rate_limited,
                        "runtime_rate_limited": runtime_rate_limited,
                        "increase_factor": runtime_rate_limited / baseline_rate_limited if baseline_rate_limited > 0 else float('inf')
                    },
                    "confidence": 0.75,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
                
        except Exception as e:
            self.logger.error(f"分析限流行为时发生错误: {e}")
        
        return faults
    
    def _detect_traffic_anomaly(self, baseline_requests: List[Any], runtime_requests: List[Any]) -> bool:
        """检测流量异常"""
        # 简化的流量异常检测逻辑
        baseline_count = len(baseline_requests)
        runtime_count = len(runtime_requests)
        
        # 如果运行时请求数量显著偏离基线
        if baseline_count > 0:
            ratio = runtime_count / baseline_count
            return ratio < 0.5 or ratio > 2.0
        
        return runtime_count > 0
    
    def _calculate_error_rate(self, data: Dict[str, Any], error_type: str) -> float:
        """计算错误率"""
        prometheus_metrics = data.get('prometheus_metrics', {})
        requests_data = prometheus_metrics.get('istio_requests_total', [])
        
        total_requests = 0
        error_requests = 0
        
        for request in requests_data:
            if 'value' in request:
                count = float(request['value'])
                total_requests += count
                
                # 检查响应码
                metric = request.get('metric', {})
                response_code = metric.get('response_code', '')
                
                if error_type == '5xx' and response_code.startswith('5'):
                    error_requests += count
                elif error_type == '4xx' and response_code.startswith('4'):
                    error_requests += count
        
        return error_requests / total_requests if total_requests > 0 else 0
    
    def _calculate_p95_latency(self, data: Dict[str, Any]) -> float:
        """计算P95延迟"""
        prometheus_metrics = data.get('prometheus_metrics', {})
        latency_data = prometheus_metrics.get('istio_request_duration_milliseconds', [])
        
        if latency_data:
            # 提取P95延迟值
            for metric in latency_data:
                if 'value' in metric:
                    return float(metric['value'])
        
        return 0
    
    def _calculate_retry_rate(self, data: Dict[str, Any]) -> float:
        """计算重试率"""
        prometheus_metrics = data.get('prometheus_metrics', {})
        retry_data = prometheus_metrics.get('envoy_cluster_upstream_rq_retry', [])
        
        total_retries = 0
        for retry in retry_data:
            if 'value' in retry:
                total_retries += float(retry['value'])
        
        # 简化的重试率计算
        return min(total_retries / 100, 1.0)  # 假设最多100个请求
    
    def _calculate_circuit_breaker_ejections(self, data: Dict[str, Any]) -> int:
        """计算熔断器弹出次数"""
        envoy_metrics = data.get('envoy_metrics', {})
        
        total_ejections = 0
        for pod_name, pod_metrics in envoy_metrics.items():
            # 查找熔断器相关指标
            for metric_name, value in pod_metrics.items():
                if 'outlier_detection' in metric_name and 'ejections' in metric_name:
                    try:
                        total_ejections += int(value)
                    except (ValueError, TypeError):
                        continue
        
        return total_ejections
    
    def _calculate_rate_limit_hits(self, data: Dict[str, Any]) -> int:
        """计算限流命中次数"""
        prometheus_metrics = data.get('prometheus_metrics', {})
        rate_limit_data = prometheus_metrics.get('envoy_http_ratelimit_rate_limited', [])
        
        total_hits = 0
        for hit in rate_limit_data:
            if 'value' in hit:
                total_hits += int(float(hit['value']))
        
        return total_hits
    
    async def _cleanup_configs(self, config_files: List[str]):
        """清理配置"""
        self.logger.info("清理测试配置")
        
        for config_file in config_files:
            try:
                result = subprocess.run(
                    ["kubectl", "delete", "-f", config_file, "--ignore-not-found"],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.logger.info(f"配置清理成功: {config_file}")
                else:
                    self.logger.warning(f"配置清理警告: {config_file}")
                    
            except Exception as e:
                self.logger.error(f"清理配置时发生异常: {e}")
        
        # 等待清理完成
        await asyncio.sleep(5)
