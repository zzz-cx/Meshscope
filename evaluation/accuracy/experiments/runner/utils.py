#!/usr/bin/env python3
"""
实验工具类
公共工具：配置部署、日志收集、指标统计
"""

import subprocess
import json
import yaml
import time
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import tempfile
import os

class ExperimentUtils:
    """实验工具类"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化工具类"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 环境配置
        self.environment_config = config.get('environment', {})
        self.cluster_config = self.environment_config.get('cluster_config', {})
        
        # 监控配置
        self.monitoring_config = self.environment_config.get('monitoring', {})
    
    def check_environment(self) -> Dict[str, bool]:
        """检查实验环境"""
        environment_status = {
            "kubectl": False,
            "istioctl": False,
            "kube_linter": False,
            "kubeval": False,
            "kubernetes_cluster": False,
            "istio_installed": False,
            "test_app_deployed": False
        }
        
        try:
            # 检查kubectl
            result = subprocess.run(["kubectl", "version", "--client"], 
                                  capture_output=True, text=True)
            environment_status["kubectl"] = result.returncode == 0
            
            # 检查istioctl
            result = subprocess.run(["istioctl", "version"], 
                                  capture_output=True, text=True)
            environment_status["istioctl"] = result.returncode == 0
            
            # 检查kube-linter
            result = subprocess.run(["kube-linter", "version"], 
                                  capture_output=True, text=True)
            environment_status["kube_linter"] = result.returncode == 0
            
            # 检查kubeval
            result = subprocess.run(["kubeval", "--version"], 
                                  capture_output=True, text=True)
            environment_status["kubeval"] = result.returncode == 0
            
            # 检查Kubernetes集群连接
            result = subprocess.run(["kubectl", "get", "nodes"], 
                                  capture_output=True, text=True)
            environment_status["kubernetes_cluster"] = result.returncode == 0
            
            # 检查Istio安装
            result = subprocess.run(["kubectl", "get", "pods", "-n", "istio-system"], 
                                  capture_output=True, text=True)
            environment_status["istio_installed"] = "istiod" in result.stdout
            
            # 检查测试应用部署
            test_app = self.cluster_config.get('test_app', 'bookinfo')
            result = subprocess.run(["kubectl", "get", "pods", "-l", f"app={test_app}"], 
                                  capture_output=True, text=True)
            environment_status["test_app_deployed"] = test_app in result.stdout
            
        except Exception as e:
            self.logger.error(f"检查环境时发生错误: {e}")
        
        return environment_status
    
    def deploy_config(self, config_file: str) -> bool:
        """部署配置文件"""
        try:
            self.logger.info(f"部署配置文件: {config_file}")
            
            result = subprocess.run(
                ["kubectl", "apply", "-f", config_file],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"配置部署成功: {config_file}")
                return True
            else:
                self.logger.error(f"配置部署失败: {config_file}, {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"部署配置时发生异常: {e}")
            return False
    
    def delete_config(self, config_file: str) -> bool:
        """删除配置文件"""
        try:
            self.logger.info(f"删除配置文件: {config_file}")
            
            result = subprocess.run(
                ["kubectl", "delete", "-f", config_file, "--ignore-not-found"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"配置删除成功: {config_file}")
                return True
            else:
                self.logger.warning(f"配置删除警告: {config_file}, {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"删除配置时发生异常: {e}")
            return False
    
    def wait_for_config_propagation(self, timeout: int = 60) -> bool:
        """等待配置传播"""
        self.logger.info(f"等待配置传播，超时时间: {timeout}秒")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 检查Istio配置状态
                result = subprocess.run(
                    ["istioctl", "proxy-status"],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0 and "SYNCED" in result.stdout:
                    self.logger.info("配置传播完成")
                    return True
                
                time.sleep(5)
                
            except Exception as e:
                self.logger.error(f"检查配置传播状态时发生错误: {e}")
                time.sleep(5)
        
        self.logger.warning("配置传播超时")
        return False
    
    def collect_logs(self, namespace: str = "default", duration: int = 60) -> Dict[str, Any]:
        """收集日志"""
        logs = {
            "namespace": namespace,
            "duration": duration,
            "pod_logs": {},
            "events": [],
            "collection_time": datetime.now().isoformat()
        }
        
        try:
            # 收集Pod日志
            result = subprocess.run([
                "kubectl", "get", "pods", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                pod_names = result.stdout.strip().split()
                
                for pod_name in pod_names:
                    pod_logs = self._collect_pod_logs(pod_name, namespace, duration)
                    logs["pod_logs"][pod_name] = pod_logs
            
            # 收集事件
            logs["events"] = self._collect_events(namespace)
            
        except Exception as e:
            self.logger.error(f"收集日志时发生错误: {e}")
        
        return logs
    
    def _collect_pod_logs(self, pod_name: str, namespace: str, duration: int) -> List[str]:
        """收集单个Pod的日志"""
        try:
            result = subprocess.run([
                "kubectl", "logs", pod_name, "-n", namespace,
                "--since", f"{duration}s", "--tail", "100"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            else:
                return []
                
        except Exception as e:
            self.logger.error(f"收集Pod {pod_name} 日志时发生错误: {e}")
            return []
    
    def _collect_events(self, namespace: str) -> List[Dict[str, Any]]:
        """收集事件"""
        events = []
        
        try:
            result = subprocess.run([
                "kubectl", "get", "events", "-n", namespace, "-o", "json"
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
            self.logger.error(f"收集事件时发生错误: {e}")
        
        return events
    
    def collect_metrics(self, duration: int = 60) -> Dict[str, Any]:
        """收集监控指标"""
        metrics = {
            "duration": duration,
            "prometheus_metrics": {},
            "kubernetes_metrics": {},
            "collection_time": datetime.now().isoformat()
        }
        
        try:
            # 收集Prometheus指标
            metrics["prometheus_metrics"] = self._collect_prometheus_metrics()
            
            # 收集Kubernetes指标
            metrics["kubernetes_metrics"] = self._collect_kubernetes_metrics()
            
        except Exception as e:
            self.logger.error(f"收集指标时发生错误: {e}")
        
        return metrics
    
    def _collect_prometheus_metrics(self) -> Dict[str, Any]:
        """收集Prometheus指标"""
        prometheus_metrics = {}
        
        try:
            prometheus_url = self.monitoring_config.get('prometheus', {}).get('url', 'http://localhost:9090')
            
            # 定义要收集的指标查询
            queries = {
                "istio_requests_total": 'sum(rate(istio_requests_total[1m])) by (source_app, destination_service_name, response_code)',
                "istio_request_duration_milliseconds": 'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket[1m])) by (le, destination_service_name))',
                "envoy_cluster_upstream_rq_retry": 'sum(rate(envoy_cluster_upstream_rq_retry[1m])) by (envoy_cluster_name)',
                "envoy_cluster_upstream_rq_timeout": 'sum(rate(envoy_cluster_upstream_rq_timeout[1m])) by (envoy_cluster_name)'
            }
            
            for metric_name, query in queries.items():
                try:
                    result = subprocess.run([
                        "curl", "-s", f"{prometheus_url}/api/v1/query",
                        "-G", "--data-urlencode", f"query={query}"
                    ], capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                        prometheus_metrics[metric_name] = data.get('data', {}).get('result', [])
                        
                except Exception as e:
                    self.logger.error(f"收集Prometheus指标 {metric_name} 失败: {e}")
                    
        except Exception as e:
            self.logger.error(f"收集Prometheus指标时发生错误: {e}")
        
        return prometheus_metrics
    
    def _collect_kubernetes_metrics(self) -> Dict[str, Any]:
        """收集Kubernetes指标"""
        k8s_metrics = {
            "pod_status": {},
            "service_status": {},
            "deployment_status": {}
        }
        
        try:
            # 收集Pod状态
            result = subprocess.run([
                "kubectl", "get", "pods", "-o", "json"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                pods_data = json.loads(result.stdout)
                for pod in pods_data.get('items', []):
                    pod_name = pod.get('metadata', {}).get('name', '')
                    pod_status = pod.get('status', {}).get('phase', '')
                    k8s_metrics["pod_status"][pod_name] = pod_status
            
            # 收集Service状态
            result = subprocess.run([
                "kubectl", "get", "services", "-o", "json"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                services_data = json.loads(result.stdout)
                for service in services_data.get('items', []):
                    service_name = service.get('metadata', {}).get('name', '')
                    service_type = service.get('spec', {}).get('type', '')
                    k8s_metrics["service_status"][service_name] = service_type
            
            # 收集Deployment状态
            result = subprocess.run([
                "kubectl", "get", "deployments", "-o", "json"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                deployments_data = json.loads(result.stdout)
                for deployment in deployments_data.get('items', []):
                    deployment_name = deployment.get('metadata', {}).get('name', '')
                    ready_replicas = deployment.get('status', {}).get('readyReplicas', 0)
                    desired_replicas = deployment.get('spec', {}).get('replicas', 0)
                    k8s_metrics["deployment_status"][deployment_name] = {
                        "ready": ready_replicas,
                        "desired": desired_replicas
                    }
                    
        except Exception as e:
            self.logger.error(f"收集Kubernetes指标时发生错误: {e}")
        
        return k8s_metrics
    
    def cleanup_environment(self, config_files: List[str]):
        """清理实验环境"""
        self.logger.info("清理实验环境")
        
        # 删除所有测试配置
        for config_file in config_files:
            self.delete_config(config_file)
        
        # 等待清理完成
        time.sleep(10)
        
        self.logger.info("环境清理完成")
    
    def save_experiment_data(self, data: Dict[str, Any], filename: str):
        """保存实验数据"""
        try:
            # 确保输出目录存在
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 保存数据
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            
            self.logger.info(f"实验数据已保存到: {filename}")
            
        except Exception as e:
            self.logger.error(f"保存实验数据时发生错误: {e}")
    
    def load_experiment_data(self, filename: str) -> Optional[Dict[str, Any]]:
        """加载实验数据"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.logger.info(f"实验数据已从 {filename} 加载")
            return data
            
        except Exception as e:
            self.logger.error(f"加载实验数据时发生错误: {e}")
            return None
    
    def generate_timestamp(self) -> str:
        """生成时间戳"""
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def create_temp_config(self, config_content: str) -> str:
        """创建临时配置文件"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                temp_file.write(config_content)
                return temp_file.name
                
        except Exception as e:
            self.logger.error(f"创建临时配置文件时发生错误: {e}")
            return None
    
    def cleanup_temp_file(self, temp_file_path: str):
        """清理临时文件"""
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                self.logger.debug(f"临时文件已删除: {temp_file_path}")
                
        except Exception as e:
            self.logger.error(f"删除临时文件时发生错误: {e}")
    
    def validate_config_file(self, config_file: str) -> bool:
        """验证配置文件格式"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                yaml.safe_load_all(f)
            
            self.logger.debug(f"配置文件格式验证通过: {config_file}")
            return True
            
        except yaml.YAMLError as e:
            self.logger.error(f"配置文件格式错误: {config_file}, {e}")
            return False
        except Exception as e:
            self.logger.error(f"验证配置文件时发生错误: {e}")
            return False
    
    def get_config_info(self, config_file: str) -> Dict[str, Any]:
        """获取配置文件信息"""
        config_info = {
            "file_path": config_file,
            "file_size": 0,
            "resource_count": 0,
            "resource_types": [],
            "namespaces": set(),
            "validation_status": False
        }
        
        try:
            # 获取文件大小
            config_info["file_size"] = os.path.getsize(config_file)
            
            # 解析配置文件
            with open(config_file, 'r', encoding='utf-8') as f:
                documents = list(yaml.safe_load_all(f))
            
            config_info["resource_count"] = len(documents)
            
            for doc in documents:
                if doc and isinstance(doc, dict):
                    # 获取资源类型
                    kind = doc.get('kind', '')
                    if kind:
                        config_info["resource_types"].append(kind)
                    
                    # 获取命名空间
                    namespace = doc.get('metadata', {}).get('namespace', 'default')
                    config_info["namespaces"].add(namespace)
            
            # 转换set为list
            config_info["namespaces"] = list(config_info["namespaces"])
            
            # 验证配置文件
            config_info["validation_status"] = self.validate_config_file(config_file)
            
        except Exception as e:
            self.logger.error(f"获取配置文件信息时发生错误: {e}")
        
        return config_info
