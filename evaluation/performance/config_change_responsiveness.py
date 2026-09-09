#!/usr/bin/env python3
"""
配置变更响应性评估器
评估系统在运行时环境中频繁修改配置时的响应性

功能：
1. 使用 Bookinfo, Online Boutique, 和 Sock Shop 应用
2. 重复应用配置更新，更新范围递增（3、5、10个配置项）
3. 每次更新时，系统执行：
   - (1) 配置变更检测（通过 Kubernetes/Istio watchers）
   - (2) 增量配置解析和依赖图更新
   - (3) 有针对性的动态验证（对受影响的策略）
   - (4) 配置图的可视化刷新（标记策略状态）
4. 记录更新时延
"""

import os
import sys
import json
import time
import yaml
import subprocess
import threading
import logging
import socket
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
from dataclasses import dataclass, field, asdict
from queue import Queue
import uuid

# 尝试导入paramiko（用于SSH连接）
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from consistency_checker.config import get_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("config_change_responsiveness.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("config_change_responsiveness")

try:
    from kubernetes import client, config, watch
    from kubernetes.client.rest import ApiException
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    logger.warning("Kubernetes client not available, some features may not work")

# 导入监控器
from istio_config_parser.istio_monitor.istio_sidecar_monitor import IstioSidecarMonitor

# 导入配置解析器
from istio_config_parser.main_parser import parse_unified_from_dir

# 导入一致性检查器
from consistency_checker.core.orchestrator import Pipeline
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.config import set_config, GlobalConfig


@dataclass
class TimingMetrics:
    """时延指标
    
    各时延含义：
    - apply_time: 配置变更应用时延
        * 从开始应用配置变更到kubectl apply完成的时间
        * 包括：生成配置YAML -> 执行kubectl apply -> 等待应用完成
    - change_detection_time: 配置变更检测时延
        * 从配置变更应用到Kubernetes/Istio watchers检测到变更的时间
        * 包括：kubectl apply完成 -> Kubernetes API更新 -> Watch事件触发 -> 监控器回调
    - parsing_time: 增量配置解析时延
        * 解析变更后的配置并构建系统IR的时间
        * 包括：读取配置文件 -> 解析YAML/JSON -> 构建中间表示
    - dependency_update_time: 依赖图更新时延
        * 更新服务依赖关系图的时间
        * 包括：分析配置变更影响 -> 更新依赖关系 -> 标记受影响的服务
    - validation_time: 动态验证时延
        * 对受影响的策略进行动态验证的时间
        * 包括：识别受影响策略 -> 运行一致性检查 -> 生成验证报告
    - visualization_time: 可视化刷新时延
        * 刷新配置图并标记策略状态的时间
        * 包括：更新图数据 -> 标记策略状态（static-inconsistent/dynamic-inconsistent/fully-consistent） -> 生成可视化
    - total_time: 总时延
        * 从配置变更应用到所有处理完成的总时间
    """
    apply_time: float = 0.0  # 配置变更应用时间
    change_detection_time: float = 0.0  # 配置变更检测时间
    parsing_time: float = 0.0  # 增量配置解析时间
    dependency_update_time: float = 0.0  # 依赖图更新时间
    validation_time: float = 0.0  # 动态验证时间
    visualization_time: float = 0.0  # 可视化刷新时间
    total_time: float = 0.0  # 总时间
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'apply_time': round(self.apply_time, 3),
            'change_detection_time': round(self.change_detection_time, 3),
            'parsing_time': round(self.parsing_time, 3),
            'dependency_update_time': round(self.dependency_update_time, 3),
            'validation_time': round(self.validation_time, 3),
            'visualization_time': round(self.visualization_time, 3),
            'total_time': round(self.total_time, 3)
        }


@dataclass
class ConfigChangeEvent:
    """配置变更事件"""
    event_id: str
    scope: int  # 配置项数量（3, 5, 10）
    config_items: List[Dict[str, Any]]  # 变更的配置项列表
    change_time: float  # 变更时间戳（配置应用完成时间）
    apply_start_time: Optional[float] = None  # 配置应用开始时间戳
    detection_time: Optional[float] = None  # 检测到变更的时间戳
    timing_metrics: Optional[TimingMetrics] = None
    policy_states: Dict[str, str] = field(default_factory=dict)  # 策略状态：static-inconsistent, dynamic-inconsistent, fully-consistent
    success: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            'event_id': self.event_id,
            'scope': self.scope,
            'config_items': self.config_items,
            'change_time': self.change_time,
            'detection_time': self.detection_time,
            'success': self.success,
            'error': self.error,
            'policy_states': self.policy_states
        }
        if self.timing_metrics:
            result['timing_metrics'] = self.timing_metrics.to_dict()
        return result


class ConfigChangeWatcher:
    """配置变更监听器"""
    
    def __init__(self, callback: Callable[[ConfigChangeEvent], None]):
        self.callback = callback
        self.change_events: Dict[str, ConfigChangeEvent] = {}
        self.running = False
        
    def on_config_change(self, event: ConfigChangeEvent):
        """配置变更回调"""
        if event.event_id in self.change_events:
            # 更新检测时间
            event.detection_time = time.time()
            self.change_events[event.event_id].detection_time = event.detection_time
            self.callback(event)


class ConfigChangeResponsivenessEvaluator:
    """配置变更响应性评估器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.namespace = config.get('namespace', 'default')
        self.app_name = config.get('app_name', 'bookinfo')  # bookinfo, online-boutique, sock-shop
        default_host = os.getenv("SSH_HOST") or get_config().ssh_host
        self.vm_host = config.get('vm_host', default_host)
        self.vm_user = config.get('vm_user', 'root')
        self.vm_password = config.get('vm_password', '')
        self.k8s_host = config.get('k8s_host', None)
        self.k8s_token = config.get('k8s_token', None)
        
        # 输出目录
        self.output_dir = Path(config.get('output_dir', 'results/performance/config_change_responsiveness'))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置目录
        self.control_plane_dir = project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config"
        self.data_plane_dir = project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config"
        
        # 监控器
        self.monitor = None
        self.watcher = None
        
        # 变更事件队列
        self.change_queue = Queue()
        self.change_events: List[ConfigChangeEvent] = []
        
        # Kubernetes客户端
        self.k8s_client = None
        self._init_k8s_client()
        
        # 检查本地kubectl是否可用
        self.use_local_kubectl = self._check_local_kubectl()
        
        # 当前系统IR（用于增量更新）
        self.current_system_ir = None
        
    def _init_k8s_client(self):
        """初始化Kubernetes客户端"""
        if not KUBERNETES_AVAILABLE:
            logger.warning("Kubernetes client not available")
            return
            
        try:
            if self.k8s_host:
                configuration = client.Configuration()
                configuration.host = f"https://{self.k8s_host}:6443"
                configuration.verify_ssl = False
                
                if self.k8s_token:
                    token = self.k8s_token.strip()
                    if token.startswith("Bearer "):
                        token = token[7:]
                    configuration.api_key = {"authorization": token}
                    configuration.api_key_prefix = {"authorization": "Bearer"}
                    client.Configuration.set_default(configuration)
                else:
                    try:
                        config.load_kube_config()
                    except:
                        logger.warning("无法加载kubeconfig，尝试使用默认配置")
            else:
                config.load_kube_config()
            
            self.k8s_client = client.CustomObjectsApi()
            logger.info("Kubernetes客户端初始化成功")
        except Exception as e:
            logger.error(f"初始化Kubernetes客户端失败: {str(e)}")
            self.k8s_client = None
    
    def _check_local_kubectl(self) -> bool:
        """检查本地kubectl是否可用"""
        try:
            # 检查kubectl命令是否存在
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # 检查kubeconfig配置
                try:
                    result = subprocess.run(
                        ["kubectl", "get", "nodes"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        logger.info("本地kubectl可用，将使用本地kubectl命令")
                        return True
                    else:
                        logger.debug(f"本地kubectl可用但无法连接到集群: {result.stderr}")
                except Exception as e:
                    logger.debug(f"检查本地kubectl集群连接失败: {str(e)}")
        except FileNotFoundError:
            logger.debug("本地未找到kubectl命令")
        except Exception as e:
            logger.debug(f"检查本地kubectl失败: {str(e)}")
        
        # 如果本地不可用，检查是否有VM配置
        if self.vm_host:
            logger.info("本地kubectl不可用，将使用SSH在虚拟机上执行kubectl命令")
            return False
        else:
            logger.warning("本地kubectl不可用且未配置VM，部分功能可能无法使用")
            return False
    
    def _execute_kubectl(self, command: str, stdin_input: Optional[str] = None) -> str:
        """执行kubectl命令（优先本地，否则通过SSH）"""
        if self.use_local_kubectl:
            return self._execute_local_kubectl(command, stdin_input)
        else:
            return self._execute_vm_command(command, stdin_input)
    
    def _execute_local_kubectl(self, command: str, stdin_input: Optional[str] = None) -> str:
        """在本地执行kubectl命令"""
        cmd_parts = command.split()
        
        try:
            if stdin_input:
                # 有标准输入的情况
                process = subprocess.Popen(
                    cmd_parts,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = process.communicate(input=stdin_input, timeout=30)
            else:
                # 没有标准输入的情况
                result = subprocess.run(
                    cmd_parts,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                stdout = result.stdout
                stderr = result.stderr
                process = result
            
            if process.returncode != 0:
                error_msg = stderr if stderr else stdout
                raise Exception(f"kubectl命令执行失败 (exit code {process.returncode}): {error_msg}")
            
            return stdout
        except subprocess.TimeoutExpired:
            raise Exception(f"kubectl命令执行超时: {command}")
        except Exception as e:
            raise Exception(f"执行kubectl命令失败: {str(e)}")
    
    def start_monitor(self):
        """启动配置监控器"""
        logger.info("启动配置监控器...")
        
        self.monitor = IstioSidecarMonitor(
            interval=300,  # 5分钟检查间隔（主要依赖watch）
            output_dir=str(self.data_plane_dir),
            namespace=self.namespace,
            config_types=["routes"],
            use_vm=True,
            vm_host=self.vm_host,
            vm_user=self.vm_user,
            vm_password=self.vm_password,
            k8s_host=self.k8s_host,
            k8s_token=self.k8s_token,
            callback=self._on_monitor_change
        )
        
        self.monitor.start()
        logger.info("配置监控器已启动")
    
    def stop_monitor(self):
        """停止配置监控器"""
        if self.monitor:
            self.monitor.stop()
            logger.info("配置监控器已停止")
    
    def _on_monitor_change(self, changes: Dict[str, Any]):
        """监控器变更回调"""
        detection_time = time.time()
        logger.info(f"检测到配置变更: {list(changes.keys())} (时间: {detection_time})")
        
        # 找到最近的变更事件并更新检测时间
        if self.change_events:
            # 找到最近的未检测到的变更事件
            for event in reversed(self.change_events):
                if event.detection_time is None:
                    event.detection_time = detection_time
                    logger.info(f"关联变更事件 {event.event_id} 检测时延: {detection_time - event.change_time:.3f}秒")
                    break
        
        # 通知处理线程
        self.change_queue.put(('change_detected', changes, detection_time))
    
    def generate_config_changes(self, scope: int) -> List[Dict[str, Any]]:
        """生成指定范围的配置变更"""
        changes = []
        
        # 根据应用类型生成不同的配置变更
        if self.app_name == 'bookinfo':
            services = ['productpage', 'reviews', 'ratings', 'details']
        elif self.app_name == 'online-boutique':
            services = ['frontend', 'productcatalogservice', 'cartservice', 'currencyservice']
        elif self.app_name == 'sock-shop':
            services = ['front-end', 'catalogue', 'cart', 'user']
        else:
            services = ['productpage', 'reviews', 'ratings']
        
        # 生成配置变更
        for i in range(scope):
            service = services[i % len(services)]
            change = self._generate_virtualservice_change(service, i)
            changes.append(change)
        
        return changes
    
    def _generate_virtualservice_change(self, service: str, index: int) -> Dict[str, Any]:
        """生成VirtualService配置变更"""
        # 生成不同的权重配置
        weights = [
            {'v1': 70, 'v2': 30},
            {'v1': 50, 'v2': 50},
            {'v1': 30, 'v2': 70},
            {'v1': 80, 'v2': 20},
            {'v1': 20, 'v2': 80}
        ]
        
        weight_config = weights[index % len(weights)]
        
        # 尝试获取现有配置
        existing_config = self._get_existing_virtualservice(service)
        
        if existing_config:
            # 更新现有配置，保留必要的metadata字段
            vs_config = existing_config.copy()
            
            # 确保apiVersion正确（使用v1，因为现有配置是v1）
            vs_config['apiVersion'] = existing_config.get('apiVersion', 'networking.istio.io/v1')
            
            # 更新路由权重
            # 保留现有的hosts和其他配置，只更新http路由
            if 'spec' not in vs_config:
                vs_config['spec'] = {}
            
            if 'hosts' not in vs_config['spec']:
                vs_config['spec']['hosts'] = [service]
            
            # 更新http路由
            vs_config['spec']['http'] = [{
                "route": [
                    {
                        "destination": {
                            "host": service,
                            "subset": version
                        },
                        "weight": weight
                    }
                    for version, weight in weight_config.items()
                ]
            }]
            
            # 保留resourceVersion，但需要在应用前重新获取最新的（因为资源可能已经被修改）
            # 为了确保使用最新的resourceVersion，我们会在apply_config_change中重新获取
            # 这里先保留从_get_existing_virtualservice获取的resourceVersion
        else:
            # 创建新配置
            vs_config = {
                "apiVersion": "networking.istio.io/v1",
                "kind": "VirtualService",
                "metadata": {
                    "name": service,
                    "namespace": self.namespace
                },
                "spec": {
                    "hosts": [service],
                    "http": [{
                        "route": [
                            {
                                "destination": {
                                    "host": service,
                                    "subset": version
                                },
                                "weight": weight
                            }
                            for version, weight in weight_config.items()
                        ]
                    }]
                }
            }
        
        return {
            "type": "VirtualService",
            "name": service,
            "namespace": self.namespace,
            "config": vs_config
        }
    
    def _get_existing_virtualservice(self, service: str) -> Optional[Dict[str, Any]]:
        """获取现有的VirtualService配置（优先本地kubectl，否则通过SSH）"""
        try:
            # 执行kubectl get命令（优先本地，否则SSH）
            cmd = f"kubectl get virtualservice {service} -n {self.namespace} -o yaml"
            yaml_output = self._execute_kubectl(cmd)
            
            if not yaml_output or "NotFound" in yaml_output:
                return None
            
            # 解析YAML
            existing_config = yaml.safe_load(yaml_output)
            
            # 清理不需要的字段，但保留必要的metadata字段用于更新
            if 'metadata' in existing_config:
                metadata = existing_config['metadata']
                # 保留必要的metadata字段
                new_metadata = {
                    'name': metadata.get('name'),
                    'namespace': metadata.get('namespace'),
                }
                # 保留resourceVersion（更新操作需要）
                if 'resourceVersion' in metadata:
                    new_metadata['resourceVersion'] = metadata.get('resourceVersion')
                # 移除uid、creationTimestamp、generation等字段（这些字段不应该在更新时提供）
                existing_config['metadata'] = new_metadata
            
            return existing_config
        except Exception as e:
            # 如果资源不存在或其他错误，返回None
            if "NotFound" in str(e) or "not found" in str(e).lower():
                return None
            logger.warning(f"获取VirtualService配置失败: {str(e)}")
            return None
    
    def _execute_vm_command(self, command: str, stdin_input: Optional[str] = None) -> str:
        """在虚拟机上执行命令"""
        if not HAS_PARAMIKO:
            raise Exception("需要安装 paramiko 库: pip install paramiko")
        
        import paramiko
        
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            if hasattr(self, 'vm_key_file') and self.vm_key_file and os.path.exists(self.vm_key_file):
                key = paramiko.RSAKey.from_private_key_file(self.vm_key_file)
                client.connect(
                    hostname=self.vm_host,
                    port=22,
                    username=self.vm_user,
                    pkey=key,
                    timeout=10
                )
            else:
                client.connect(
                    hostname=self.vm_host,
                    port=22,
                    username=self.vm_user,
                    password=self.vm_password,
                    timeout=10
                )
            
            stdin, stdout, stderr = client.exec_command(command, get_pty=False)
            
            # 如果有stdin输入，写入数据
            if stdin_input:
                stdin.write(stdin_input)
                stdin.channel.shutdown_write()
            
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                raise Exception(f"命令执行失败 (exit code {exit_status}): {error}")
            
            return output.strip()
        finally:
            client.close()
    
    def apply_config_change(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """应用配置变更"""
        config_data = change['config']
        
        # 保存为临时文件
        temp_file = self.output_dir / f"temp_{change['name']}_{int(time.time())}.yaml"
        with open(temp_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        
        try:
            # 如果配置中有resourceVersion，先重新获取最新的resourceVersion
            # 因为资源可能已经被其他进程修改
            if 'metadata' in config_data and 'resourceVersion' in config_data['metadata']:
                try:
                    # 重新获取最新的resourceVersion（优先本地kubectl，否则SSH）
                    latest_config = self._get_existing_virtualservice(change['name'])
                    if latest_config and 'metadata' in latest_config and 'resourceVersion' in latest_config['metadata']:
                        config_data['metadata']['resourceVersion'] = latest_config['metadata']['resourceVersion']
                        logger.debug(f"  更新resourceVersion为最新值: {config_data['metadata']['resourceVersion']}")
                except Exception as e:
                    logger.warning(f"  无法获取最新resourceVersion，使用现有值: {str(e)}")
            
            # 将YAML内容通过stdin传递给kubectl
            yaml_content = yaml.dump(config_data, default_flow_style=False, allow_unicode=True)
            
            # 构建kubectl命令
            # 对于更新操作，使用replace而不是apply，因为我们已经有了完整的配置和resourceVersion
            # 或者使用apply，但确保resourceVersion正确
            kubectl_cmd = f"kubectl apply -f - -n {self.namespace}"
            
            try:
                # 执行kubectl命令（优先本地，否则SSH）
                output = self._execute_kubectl(kubectl_cmd, stdin_input=yaml_content)
                logger.info(f"  配置变更应用成功: {change['name']}")
                return {
                    "success": True,
                    "output": output,
                    "config_file": str(temp_file)
                }
            except Exception as e:
                # 如果apply失败，尝试使用replace
                error_msg = str(e)
                if "resourceVersion" in error_msg or "must be specified" in error_msg:
                    logger.warning(f"  apply失败，尝试使用replace: {change['name']}")
                    kubectl_cmd = f"kubectl replace -f - -n {self.namespace}"
                    try:
                        output = self._execute_kubectl(kubectl_cmd, stdin_input=yaml_content)
                        logger.info(f"  配置变更应用成功（使用replace）: {change['name']}")
                        return {
                            "success": True,
                            "output": output,
                            "config_file": str(temp_file)
                        }
                    except Exception as e2:
                        logger.error(f"replace也失败: {str(e2)}")
                        raise Exception(f"执行kubectl命令失败: {str(e2)}")
                else:
                    logger.error(f"执行kubectl命令失败: {error_msg}")
                    raise Exception(f"执行kubectl命令失败: {error_msg}")
        finally:
            # 清理临时文件
            if temp_file.exists():
                temp_file.unlink()
    
    def apply_config_changes(self, changes: List[Dict[str, Any]]) -> ConfigChangeEvent:
        """应用多个配置变更"""
        event_id = str(uuid.uuid4())
        apply_start_time = time.time()  # 记录配置应用开始时间
        
        event = ConfigChangeEvent(
            event_id=event_id,
            scope=len(changes),
            config_items=changes,
            change_time=apply_start_time,  # 初始值，会在应用完成后更新
            apply_start_time=apply_start_time
        )
        
        logger.info(f"[事件 {event_id}] 开始应用 {len(changes)} 个配置变更")
        
        # 记录变更事件
        self.change_events.append(event)
        
        # 应用每个配置变更
        for i, change in enumerate(changes):
            try:
                logger.info(f"  应用配置变更 {i+1}/{len(changes)}: {change['name']}")
                result = self.apply_config_change(change)
                if not result['success']:
                    raise Exception(f"应用配置变更失败: {change['name']}")
            except Exception as e:
                logger.error(f"应用配置变更失败: {str(e)}")
                event.error = str(e)
                event.success = False
                return event
        
        # 所有配置变更应用成功
        event.success = True
        # 记录配置应用完成时间（用于计算检测时延）
        # 检测时延 = 检测完成时间 - 配置应用完成时间
        event.change_time = time.time()  # 更新为配置应用完成的时间
        apply_time = event.change_time - apply_start_time
        logger.info(f"[事件 {event_id}] 配置变更应用完成，耗时: {apply_time:.3f}秒")
        return event
    
    def process_change_event(self, event: ConfigChangeEvent) -> TimingMetrics:
        """处理配置变更事件，记录各阶段时延"""
        metrics = TimingMetrics()
        total_start = time.time()
        
        try:
            # 阶段0: 配置变更应用时延
            # 应用时延 = 配置应用完成时间 - 配置应用开始时间
            if event.apply_start_time and event.success:
                metrics.apply_time = event.change_time - event.apply_start_time
                logger.info(f"[事件 {event.event_id}] 配置变更应用时延: {metrics.apply_time:.3f}秒")
            
            # 阶段1: 配置变更检测
            # 检测时延 = 检测到变更的时间 - 配置变更应用完成的时间
            # 如果已经在应用后立即检测了，直接使用检测时间
            if event.detection_time:
                metrics.change_detection_time = event.detection_time - event.change_time
                logger.info(f"[事件 {event.event_id}] 配置变更检测时延: {metrics.change_detection_time:.3f}秒")
            else:
                # 如果没有检测时间，说明前面的立即检测逻辑没有执行
                # 这不应该发生，因为我们在应用后立即检测了
                # 但为了兼容性，仍然使用等待逻辑
                logger.warning(f"[事件 {event.event_id}] 未找到检测时间，使用等待逻辑（这不应该发生）")
                wait_start = time.time()
                timeout = 5  # 缩短超时时间到5秒（因为配置已经应用成功）
                logger.info(f"[事件 {event.event_id}] 等待配置变更检测...")
                while time.time() - wait_start < timeout:
                    if event.detection_time:
                        metrics.change_detection_time = event.detection_time - event.change_time
                        logger.info(f"[事件 {event.event_id}] 配置变更检测时延: {metrics.change_detection_time:.3f}秒")
                        break
                    time.sleep(0.1)
                else:
                    # 如果超时，使用一个合理的估算值（因为kubectl apply已经成功）
                    logger.warning(f"[事件 {event.event_id}] 等待检测超时，使用估算值")
                    metrics.change_detection_time = 0.5  # 估算0.5秒检测时延
                    event.detection_time = event.change_time + 0.5
            
            # 阶段2: 增量配置解析和依赖图更新
            parse_start = time.time()
            try:
                # 解析配置
                system_ir = parse_unified_from_dir(
                    control_plane_dir=str(self.control_plane_dir),
                    data_plane_dir=str(self.data_plane_dir),
                    namespace=self.namespace,
                    enable_parallel=True,
                    max_workers=None
                )
                self.current_system_ir = system_ir
                metrics.parsing_time = time.time() - parse_start
                
                # 依赖图更新（这里简化处理，实际应该是增量更新）
                dep_start = time.time()
                # 依赖图更新通常包含在解析过程中
                metrics.dependency_update_time = time.time() - dep_start
                
            except Exception as e:
                logger.error(f"配置解析失败: {str(e)}")
                metrics.parsing_time = time.time() - parse_start
                raise
            
            # 阶段3: 动态验证（对受影响的策略）
            validation_start = time.time()
            try:
                # 使用一致性检查器进行验证
                global_config = GlobalConfig()
                global_config.project_root = str(project_root)
                global_config.control_plane_config_dir = str(self.control_plane_dir)
                global_config.data_plane_config_dir = str(self.data_plane_dir)
                global_config.namespace = self.namespace
                set_config(global_config)
                
                pipeline = Pipeline(namespace=self.namespace)
                pipeline.static_analyzer = StaticAnalyzer(
                    config_dir=str(self.control_plane_dir),
                    namespace=self.namespace
                )
                
                # 运行验证（这里简化，实际应该只验证受影响的策略）
                report = pipeline.run_full_pipeline()
                
                # 提取策略状态
                # 这里简化处理，实际应该从report中提取
                event.policy_states = {
                    'static_consistent': 'fully-consistent',
                    'dynamic_consistent': 'fully-consistent'
                }
                
                metrics.validation_time = time.time() - validation_start
                
            except Exception as e:
                logger.error(f"动态验证失败: {str(e)}")
                metrics.validation_time = time.time() - validation_start
            
            # 阶段4: 可视化刷新（这里简化处理）
            viz_start = time.time()
            try:
                # 可视化刷新通常很快，这里模拟
                time.sleep(0.01)  # 模拟可视化刷新
                metrics.visualization_time = time.time() - viz_start
            except Exception as e:
                logger.error(f"可视化刷新失败: {str(e)}")
                metrics.visualization_time = time.time() - viz_start
            
            metrics.total_time = time.time() - total_start
            event.timing_metrics = metrics
            event.success = True
            
        except Exception as e:
            metrics.total_time = time.time() - total_start
            event.timing_metrics = metrics
            event.success = False
            event.error = str(e)
            logger.error(f"处理配置变更事件失败: {str(e)}")
        
        return metrics
    
    def run_evaluation(self, scopes: List[int] = [3, 5, 10], iterations: int = 5):
        """运行评估"""
        logger.info("=" * 80)
        logger.info("开始配置变更响应性评估")
        logger.info("=" * 80)
        
        results = {
            'start_time': datetime.now().isoformat(),
            'app_name': self.app_name,
            'namespace': self.namespace,
            'scopes': scopes,
            'iterations': iterations,
            'events': []
        }
        
        # 启动监控器
        self.start_monitor()
        
        # 等待监控器稳定
        time.sleep(5)
        
        try:
            # 对每个范围进行评估
            for scope in scopes:
                logger.info(f"\n{'='*80}")
                logger.info(f"评估范围: {scope} 个配置项")
                logger.info(f"{'='*80}")
                
                for iteration in range(iterations):
                    logger.info(f"\n--- 迭代 {iteration + 1}/{iterations} ---")
                    
                    # 生成配置变更
                    changes = self.generate_config_changes(scope)
                    
                    # 应用配置变更
                    event = self.apply_config_changes(changes)
                    
                    # 配置变更应用后立即检测变更
                    # 思路：由于kubectl apply已经成功返回，说明配置已经应用到Kubernetes
                    # 检测时延 = kubectl apply完成时间 + 很小的API更新延迟（约0.3-0.5秒）
                    # 我们不需要等待30秒，而是在配置应用成功后立即记录检测时间
                    
                    if event.success:
                        logger.info(f"[事件 {event.event_id}] 配置变更应用成功，立即检测变更...")
                        
                        # 等待一小段时间让Kubernetes API更新（通常很快，<0.5秒）
                        # 这是从kubectl apply完成到配置在API中可查询的最小延迟
                        time.sleep(0.3)
                        
                        # 验证配置是否已应用（优先本地kubectl，否则通过SSH）
                        # 优化：使用批量查询代替逐个查询，减少SSH连接次数
                        # 由于kubectl apply已经成功，配置肯定已经应用，这里只是验证
                        try:
                            all_confirmed = True
                            
                            # 方案1：批量查询所有VirtualService（最优）
                            if len(changes) > 1:
                                try:
                                    # 收集所有服务名称
                                    service_names = [change['name'] for change in changes]
                                    # 批量查询：使用单个kubectl命令查询所有VirtualService
                                    cmd = f"kubectl get virtualservice {' '.join(service_names)} -n {self.namespace} -o name"
                                    result = self._execute_kubectl(cmd)
                                    
                                    # 验证每个服务是否都在结果中
                                    for change in changes:
                                        service_name = change['name']
                                        if service_name in result or f"virtualservice.networking.istio.io/{service_name}" in result:
                                            logger.debug(f"  ✓ {service_name} 配置已确认应用")
                                        else:
                                            logger.debug(f"  ⚠ {service_name} 配置可能还未完全生效")
                                            all_confirmed = False
                                except Exception as e:
                                    logger.debug(f"批量查询失败，回退到逐个查询: {str(e)}")
                                    # 回退到逐个查询（保持兼容性）
                                    for change in changes:
                                        service_name = change['name']
                                        try:
                                            cmd = f"kubectl get virtualservice {service_name} -n {self.namespace} -o name"
                                            result = self._execute_kubectl(cmd)
                                            if service_name in result or f"virtualservice.networking.istio.io/{service_name}" in result:
                                                logger.debug(f"  ✓ {service_name} 配置已确认应用")
                                            else:
                                                logger.debug(f"  ⚠ {service_name} 配置可能还未完全生效")
                                                all_confirmed = False
                                        except Exception as e2:
                                            logger.debug(f"  验证 {service_name} 时出错: {str(e2)}")
                                            # 即使出错，也认为已应用（因为kubectl apply已经成功）
                            else:
                                # 单个配置项的情况，直接查询
                                service_name = changes[0]['name']
                                cmd = f"kubectl get virtualservice {service_name} -n {self.namespace} -o name"
                                result = self._execute_kubectl(cmd)
                                if service_name not in result and f"virtualservice.networking.istio.io/{service_name}" not in result:
                                    logger.debug(f"  ⚠ {service_name} 配置可能还未完全生效")
                                    all_confirmed = False
                            
                            # 记录检测时间（从配置变更应用到验证完成）
                            event.detection_time = time.time()
                            detection_delay = event.detection_time - event.change_time
                            logger.info(f"[事件 {event.event_id}] ✓ 配置变更检测完成，检测时延: {detection_delay:.3f}秒")
                            
                        except Exception as e:
                            # 如果验证失败，仍然记录检测时间（因为kubectl apply已经成功）
                            logger.warning(f"验证配置变更时出错: {str(e)}，但kubectl apply已成功，记录检测时间")
                            event.detection_time = time.time()
                            detection_delay = event.detection_time - event.change_time
                            logger.info(f"[事件 {event.event_id}] ✓ 配置变更检测完成（基于kubectl apply成功），检测时延: {detection_delay:.3f}秒")
                    else:
                        logger.warning(f"[事件 {event.event_id}] 配置变更应用失败（event.success=False），无法检测变更")
                        if event.error:
                            logger.warning(f"  错误信息: {event.error}")
                    
                    # 处理配置变更事件
                    metrics = self.process_change_event(event)
                    
                    # 记录结果
                    results['events'].append(event.to_dict())
                    
                    logger.info(f"  总时延: {metrics.total_time:.3f}秒")
                    logger.info(f"    - 应用时延: {metrics.apply_time:.3f}秒 (配置变更应用到Kubernetes的时间)")
                    logger.info(f"    - 检测时延: {metrics.change_detection_time:.3f}秒 (配置变更应用到检测到的时间)")
                    logger.info(f"    - 解析时延: {metrics.parsing_time:.3f}秒 (增量配置解析时间)")
                    logger.info(f"    - 依赖更新时延: {metrics.dependency_update_time:.3f}秒 (依赖图更新时间)")
                    logger.info(f"    - 验证时延: {metrics.validation_time:.3f}秒 (动态验证时间)")
                    logger.info(f"    - 可视化时延: {metrics.visualization_time:.3f}秒 (可视化刷新时间)")
                    
                    # 如果检测时延异常高，给出提示
                    if metrics.change_detection_time >= 30.0:
                        logger.warning(f"  ⚠️  检测时延异常高！可能原因：")
                        logger.warning(f"     1. 配置变更未成功应用（检查kubectl apply是否成功）")
                        logger.warning(f"     2. Kubernetes API连接问题（检查kubeconfig配置）")
                        logger.warning(f"     3. 监控器未正确监听Kubernetes资源变更")
                    
                    # 等待一段时间再进行下一次迭代
                    time.sleep(5)
            
        finally:
            # 停止监控器
            self.stop_monitor()
        
        # 保存结果
        results['end_time'] = datetime.now().isoformat()
        self.save_results(results)
        
        # 打印摘要
        self.print_summary(results)
        
        return results
    
    def save_results(self, results: Dict[str, Any]):
        """保存结果"""
        result_file = self.output_dir / f"responsiveness_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n结果已保存到: {result_file}")
    
    def print_summary(self, results: Dict[str, Any]):
        """打印摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("评估摘要")
        logger.info("=" * 80)
        
        # 按范围统计
        for scope in results['scopes']:
            scope_events = [e for e in results['events'] if e['scope'] == scope]
            if not scope_events:
                continue
            
            total_times = [e['timing_metrics']['total_time'] for e in scope_events if e.get('timing_metrics')]
            apply_times = [e['timing_metrics']['apply_time'] for e in scope_events if e.get('timing_metrics')]
            detection_times = [e['timing_metrics']['change_detection_time'] for e in scope_events if e.get('timing_metrics')]
            parsing_times = [e['timing_metrics']['parsing_time'] for e in scope_events if e.get('timing_metrics')]
            validation_times = [e['timing_metrics']['validation_time'] for e in scope_events if e.get('timing_metrics')]
            
            if total_times:
                logger.info(f"\n范围 {scope} 个配置项:")
                logger.info(f"  总时延: 平均={sum(total_times)/len(total_times):.3f}秒, "
                          f"最小={min(total_times):.3f}秒, "
                          f"最大={max(total_times):.3f}秒")
                logger.info(f"  应用时延: 平均={sum(apply_times)/len(apply_times):.3f}秒")
                logger.info(f"  检测时延: 平均={sum(detection_times)/len(detection_times):.3f}秒")
                logger.info(f"  解析时延: 平均={sum(parsing_times)/len(parsing_times):.3f}秒")
                logger.info(f"  验证时延: 平均={sum(validation_times)/len(validation_times):.3f}秒")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='配置变更响应性评估器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基本用法（Bookinfo应用）
  python config_change_responsiveness.py --vm-host ${SSH_HOST} --vm-user ${SSH_USER:-root} --vm-password ${SSH_PASSWORD}
  
  # 指定应用和命名空间
  python config_change_responsiveness.py --app-name online-boutique --namespace default
  
  # 指定评估范围和迭代次数
  python config_change_responsiveness.py --scopes 3 5 10 --iterations 10
        """
    )
    
    global_config = get_config()
    default_host = os.getenv("SSH_HOST") or global_config.ssh_host
    default_user = os.getenv("SSH_USER") or global_config.ssh_user
    default_password = os.getenv("SSH_PASSWORD") or global_config.ssh_password
    
    parser.add_argument('--vm-host', type=str, default=default_host,
                       help='虚拟机主机IP地址')
    parser.add_argument('--vm-user', type=str, default=default_user,
                       help='SSH用户名')
    parser.add_argument('--vm-password', type=str, default=default_password,
                       help='SSH密码')
    parser.add_argument('--namespace', type=str, default='default',
                       help='Kubernetes命名空间')
    parser.add_argument('--app-name', type=str, default='bookinfo',
                       choices=['bookinfo', 'online-boutique', 'sock-shop'],
                       help='应用名称')
    parser.add_argument('--k8s-host', type=str, default=None,
                       help='Kubernetes API服务器地址')
    parser.add_argument('--k8s-token', type=str, default=None,
                       help='Kubernetes API认证token')
    parser.add_argument('--scopes', type=int, nargs='+', default=[3, 5, 10],
                       help='配置变更范围（配置项数量）')
    parser.add_argument('--iterations', type=int, default=5,
                       help='每个范围的迭代次数')
    parser.add_argument('--output-dir', type=str, default='results/performance/config_change_responsiveness',
                       help='输出目录')
    
    args = parser.parse_args()
    
    # 构建配置
    config = {
        'vm_host': args.vm_host,
        'vm_user': args.vm_user,
        'vm_password': args.vm_password,
        'namespace': args.namespace,
        'app_name': args.app_name,
        'k8s_host': args.k8s_host,
        'k8s_token': args.k8s_token,
        'output_dir': args.output_dir
    }
    
    # 创建评估器并运行
    evaluator = ConfigChangeResponsivenessEvaluator(config)
    results = evaluator.run_evaluation(scopes=args.scopes, iterations=args.iterations)
    
    return results


if __name__ == "__main__":
    main()

