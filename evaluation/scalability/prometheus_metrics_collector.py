#!/usr/bin/env python3
"""
Prometheus指标收集器
用于从Prometheus收集Kubernetes集群的内存和资源使用指标
"""

import time
import logging
import subprocess
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import statistics

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class KubernetesMemoryMetrics:
    """Kubernetes集群内存指标"""
    timestamp: float
    namespace: str
    total_pod_memory_mb: float  # 所有Pod的总内存使用（MB）
    total_pod_memory_requests_mb: float  # 所有Pod的内存请求总量（MB）
    total_pod_memory_limits_mb: float  # 所有Pod的内存限制总量（MB）
    pod_count: int  # Pod数量
    pod_memory_details: List[Dict[str, Any]] = None  # 每个Pod的内存详情
    
    def __post_init__(self):
        if self.pod_memory_details is None:
            self.pod_memory_details = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'namespace': self.namespace,
            'total_pod_memory_mb': round(self.total_pod_memory_mb, 2),
            'total_pod_memory_requests_mb': round(self.total_pod_memory_requests_mb, 2),
            'total_pod_memory_limits_mb': round(self.total_pod_memory_limits_mb, 2),
            'pod_count': self.pod_count,
            'pod_memory_details': self.pod_memory_details
        }


class PrometheusMetricsCollector:
    """Prometheus指标收集器"""
    
    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        namespace: Optional[str] = None
    ):
        """
        初始化Prometheus指标收集器
        
        Args:
            prometheus_url: Prometheus服务器URL
            namespace: Kubernetes命名空间（可选，用于过滤）
        """
        self.prometheus_url = prometheus_url.rstrip('/')
        self.namespace = namespace
        
        if not REQUESTS_AVAILABLE:
            logger.warning("requests库未安装，无法使用Prometheus API")
    
    def query_prometheus(self, query: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """
        查询Prometheus API
        
        Args:
            query: PromQL查询语句
            timeout: 超时时间（秒）
            
        Returns:
            查询结果，如果失败则返回None
        """
        if not REQUESTS_AVAILABLE:
            return None
        
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {
                'query': query
            }
            
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Prometheus查询失败: HTTP {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Prometheus查询异常: {e}")
            return None
    
    def get_pod_memory_usage(self, namespace: Optional[str] = None) -> Optional[KubernetesMemoryMetrics]:
        """
        获取Pod内存使用情况（通过Prometheus）
        
        Args:
            namespace: Kubernetes命名空间，如果为None则使用self.namespace
            
        Returns:
            Kubernetes内存指标，如果失败则返回None
        """
        target_namespace = namespace or self.namespace
        
        # Prometheus查询：获取所有Pod的内存使用
        # 使用container_memory_working_set_bytes指标（实际内存使用）
        if target_namespace:
            query = f'sum(container_memory_working_set_bytes{{namespace="{target_namespace}"}}) by (namespace)'
        else:
            query = 'sum(container_memory_working_set_bytes) by (namespace)'
        
        result = self.query_prometheus(query)
        if not result:
            return None
        
        try:
            data = result.get('data', {})
            results = data.get('result', [])
            
            total_memory_bytes = 0.0
            namespace_memory = {}
            
            for item in results:
                metric = item.get('metric', {})
                ns = metric.get('namespace', '')
                value = float(item.get('value', [0, '0'])[1])
                
                if target_namespace and ns == target_namespace:
                    total_memory_bytes = value
                    namespace_memory[ns] = value
                elif not target_namespace:
                    namespace_memory[ns] = value
                    total_memory_bytes += value
            
            # 转换为MB
            total_memory_mb = total_memory_bytes / (1024 * 1024)
            
            # 获取Pod详情（通过kubectl，因为Prometheus可能没有Pod级别的详细信息）
            pod_details = self._get_pod_memory_details_via_kubectl(target_namespace)
            
            return KubernetesMemoryMetrics(
                timestamp=time.time(),
                namespace=target_namespace or 'all',
                total_pod_memory_mb=total_memory_mb,
                total_pod_memory_requests_mb=sum(p.get('memory_requests_mb', 0) for p in pod_details),
                total_pod_memory_limits_mb=sum(p.get('memory_limits_mb', 0) for p in pod_details),
                pod_count=len(pod_details),
                pod_memory_details=pod_details
            )
        except Exception as e:
            logger.error(f"解析Prometheus内存指标失败: {e}")
            return None
    
    def _get_pod_memory_details_via_kubectl(self, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        通过kubectl获取Pod内存详情（包括requests和limits）
        
        Args:
            namespace: Kubernetes命名空间
            
        Returns:
            Pod内存详情列表
        """
        pod_details = []
        
        try:
            # 构建kubectl命令
            cmd = ["kubectl", "get", "pods", "-o", "json"]
            if namespace:
                cmd.extend(["-n", namespace])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.warning(f"kubectl命令执行失败: {result.stderr}")
                return pod_details
            
            pods_data = json.loads(result.stdout)
            
            for pod in pods_data.get('items', []):
                pod_name = pod.get('metadata', {}).get('name', '')
                pod_namespace = pod.get('metadata', {}).get('namespace', '')
                
                # 获取容器资源请求和限制
                containers = pod.get('spec', {}).get('containers', [])
                total_requests_mb = 0.0
                total_limits_mb = 0.0
                
                for container in containers:
                    resources = container.get('resources', {})
                    requests = resources.get('requests', {})
                    limits = resources.get('limits', {})
                    
                    # 解析内存请求
                    memory_request = requests.get('memory', '0')
                    if memory_request:
                        total_requests_mb += self._parse_memory_string(memory_request)
                    
                    # 解析内存限制
                    memory_limit = limits.get('memory', '0')
                    if memory_limit:
                        total_limits_mb += self._parse_memory_string(memory_limit)
                
                # 获取实际内存使用（从Pod状态）
                actual_memory_mb = 0.0
                container_statuses = pod.get('status', {}).get('containerStatuses', [])
                for status in container_statuses:
                    # 注意：Pod状态中通常不包含内存使用，需要通过metrics-server或Prometheus获取
                    # 这里先设为0，实际值从Prometheus获取
                    pass
                
                pod_details.append({
                    'pod_name': pod_name,
                    'namespace': pod_namespace,
                    'memory_requests_mb': total_requests_mb,
                    'memory_limits_mb': total_limits_mb,
                    'actual_memory_mb': actual_memory_mb  # 需要从Prometheus获取
                })
        
        except Exception as e:
            logger.warning(f"获取Pod内存详情失败: {e}")
        
        return pod_details
    
    def _parse_memory_string(self, memory_str: str) -> float:
        """
        解析Kubernetes内存字符串（如 "512Mi", "1Gi"）为MB
        
        Args:
            memory_str: 内存字符串
            
        Returns:
            内存大小（MB）
        """
        if not memory_str or memory_str == '0':
            return 0.0
        
        memory_str = memory_str.strip().upper()
        
        # 移除单位并转换
        if memory_str.endswith('KI'):
            return float(memory_str[:-2]) / 1024
        elif memory_str.endswith('MI'):
            return float(memory_str[:-2])
        elif memory_str.endswith('GI'):
            return float(memory_str[:-2]) * 1024
        elif memory_str.endswith('TI'):
            return float(memory_str[:-2]) * 1024 * 1024
        elif memory_str.endswith('K'):
            return float(memory_str[:-1]) / 1024
        elif memory_str.endswith('M'):
            return float(memory_str[:-1])
        elif memory_str.endswith('G'):
            return float(memory_str[:-1]) * 1024
        elif memory_str.endswith('T'):
            return float(memory_str[:-1]) * 1024 * 1024
        else:
            # 假设是字节
            try:
                return float(memory_str) / (1024 * 1024)
            except ValueError:
                return 0.0
    
    def get_cluster_memory_usage(self) -> Optional[Dict[str, Any]]:
        """
        获取整个集群的内存使用情况
        
        Returns:
            集群内存使用情况字典
        """
        # 查询集群总内存
        query = 'sum(container_memory_working_set_bytes)'
        result = self.query_prometheus(query)
        
        if not result:
            return None
        
        try:
            data = result.get('data', {})
            results = data.get('result', [])
            
            if results:
                total_memory_bytes = float(results[0].get('value', [0, '0'])[1])
                total_memory_mb = total_memory_bytes / (1024 * 1024)
                
                return {
                    'timestamp': time.time(),
                    'total_cluster_memory_mb': total_memory_mb,
                    'query_result': results
                }
        except Exception as e:
            logger.error(f"解析集群内存指标失败: {e}")
        
        return None

