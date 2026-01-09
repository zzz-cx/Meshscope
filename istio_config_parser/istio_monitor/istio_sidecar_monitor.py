#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import hashlib
import logging
import argparse
import threading
import datetime
import shutil
from typing import Dict, List, Any, Optional, Set
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import queue
import yaml

try:
    from .istio_api import IstioAPI
    from kubernetes import client, config, watch
except ImportError as e:
    # 尝试相对导入
    try:
        import os
        sys.path.insert(0, os.path.dirname(__file__))
        from istio_api import IstioAPI
        from kubernetes import client, config, watch
    except ImportError as e2:
        print(f"错误: {str(e2)}")
        print("请确保已安装所有依赖:")
        print("pip install -r requirements.txt")
        sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("istio_sidecar_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("istio_sidecar_monitor")

class IstioConfigHandler(FileSystemEventHandler):
    """Istio 配置文件变更处理器"""
    
    def __init__(self, monitor):
        self.monitor = monitor
    
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.yaml', '.yml')):
            logger.info(f"检测到配置文件变更: {event.src_path}")
            self.monitor.request_update()

class IstioSidecarMonitor:
    """
    Istio 数据平面 Sidecar 配置监控器
    支持定期监控和即时更新两种模式
    """
    
    def __init__(self, 
                 interval: int = 1200,
                 output_dir: str = "./istio_sidecar_config",
                 namespace: str = "default",
                 config_types: List[str] = ["routes"],
                 use_vm: bool = True,
                 vm_host: Optional[str] = None,
                 vm_port: int = 22,
                 vm_user: str = "root",
                 vm_password: Optional[str] = None,
                 vm_key_file: Optional[str] = None,
                 k8s_host: Optional[str] = None,
                 k8s_token: Optional[str] = None,
                 callback = None):
        """
        初始化监控器
        
        参数:
            interval: 检查间隔（秒）
            output_dir: 配置输出目录
            namespace: 要监控的命名空间
            config_types: 要获取的配置类型列表
            use_vm: 是否通过虚拟机连接
            vm_host: 虚拟机主机名或 IP
            vm_port: 虚拟机 SSH 端口
            vm_user: 虚拟机用户名
            vm_password: 虚拟机密码
            vm_key_file: 虚拟机 SSH 密钥文件路径
            k8s_host: Kubernetes API 服务器地址
            k8s_token: Kubernetes API 认证 token
            callback: 配置变更时的回调函数
        """
        self.interval = interval
        self.output_dir = output_dir
        self.namespace = namespace
        self.config_types = config_types
        self.callback = callback
        self.running = False
        self.monitor_thread = None
        self.k8s_watch_thread = None
        self.last_config_hashes = {}
        self.selected_proxy = None
        self.update_queue = Queue()
        self.last_update_time = 0  # 添加最后更新时间记录
        self.k8s_host = k8s_host  # 保存 k8s_host 以供后续使用
        self.k8s_token = k8s_token  # 保存原始 token
        self.configuration = None  # 保存configuration实例
        
        # 确保输出目录存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 添加控制平面配置目录
        self.control_plane_dir = os.path.join(os.path.dirname(output_dir), "istio_control_config")
        if not os.path.exists(self.control_plane_dir):
            os.makedirs(self.control_plane_dir)
        
        # 初始化 API 客户端
        self.api = IstioAPI(
            host="localhost",
            port=8080,
            namespace="istio-system",
            use_vm=use_vm,
            vm_host=vm_host,
            vm_port=vm_port,
            vm_user=vm_user,
            vm_password=vm_password,
            vm_key_file=vm_key_file
        )
        
        # 初始化 Kubernetes 客户端
        self._init_k8s_client()

    def _reset_directory(self, directory_path: str) -> None:
        """清空并重建目录，确保本地配置与集群状态同步"""
        try:
            if os.path.exists(directory_path):
                shutil.rmtree(directory_path)
            os.makedirs(directory_path, exist_ok=True)
        except Exception as e:
            logger.error(f"重置目录 {directory_path} 失败: {str(e)}")

    def _init_k8s_client(self) -> None:
        """初始化 Kubernetes 客户端"""
        try:
            if self.k8s_host:
                configuration = client.Configuration()
                configuration.host = f"https://{self.k8s_host}:6443"
                configuration.verify_ssl = False
                configuration.debug = True
                
                if self.k8s_token:
                    # 确保token格式正确
                    token = self.k8s_token.strip()
                    if token.startswith("Bearer "):
                        token = token[7:]  # 移除 "Bearer " 前缀
                    configuration.api_key = {"authorization": token}
                    configuration.api_key_prefix = {"authorization": "Bearer"}
                    logger.info(f"已使用提供的 token 配置 Kubernetes 认证 (token长度: {len(token)})")
                else:
                    try:
                        with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
                            token = f.read().strip()
                            self.k8s_token = token
                            configuration.api_key = {"authorization": f"Bearer {token}"}
                            configuration.api_key_prefix = {"authorization": "Bearer"}
                            logger.info("已使用 ServiceAccount token 配置 Kubernetes 认证")
                    except Exception as e:
                        logger.warning(f"无法读取 ServiceAccount token: {str(e)}")
                
                self.configuration = configuration
                client.Configuration.set_default(configuration)
                self.k8s_client = client.CustomObjectsApi(client.ApiClient(configuration))
                logger.info("已使用指定配置初始化 Kubernetes 客户端")
            else:
                config.load_kube_config()
                self.k8s_client = client.CustomObjectsApi()
                logger.info("已从默认配置初始化 Kubernetes 客户端")
        except Exception as e:
            logger.error(f"初始化 Kubernetes 客户端失败: {str(e)}")
            self.k8s_client = None

    def _select_proxy(self) -> Optional[str]:
        """选择一个可用的代理"""
        try:
            proxies = self.api.get_proxies()
            for proxy in proxies:
                if self.namespace == "all" or proxy.endswith(f".{self.namespace}"):
                    logger.info(f"已选择代理: {proxy}")
                    return proxy
            logger.error(f"在命名空间 {self.namespace} 中未找到可用的代理")
            return None
        except Exception as e:
            logger.error(f"选择代理失败: {str(e)}")
            return None

    def update_now(self) -> Dict[str, Any]:
        """立即获取最新配置"""
        logger.info("开始即时更新配置")
        changes = {}
        
        try:
            # 1. 获取控制平面配置
            if self.k8s_client:
                try:
                    logger.info("获取控制平面配置")
                    control_plane_configs = self._get_control_plane_configs()
                    changes.update(control_plane_configs)
                except Exception as e:
                    logger.error(f"获取控制平面配置失败: {str(e)}")
            
            # 2. 获取数据平面配置
            if not self.selected_proxy:
                self.selected_proxy = self._select_proxy()
            
            if not self.selected_proxy:
                logger.error("未找到可用的代理")
                return changes
            
            # 获取配置
            for config_type in self.config_types:
                try:
                    logger.info(f"获取 {config_type} 配置")
                    config_data = self.api.get_proxy_config(self.selected_proxy, config_type)
                    config_hash = self._calculate_hash(config_data)
                    config_key = f"sidecar_{config_type}"
                    
                    # 检查配置是否有变化
                    if config_key not in self.last_config_hashes or self.last_config_hashes[config_key] != config_hash:
                        logger.info(f"{config_type} 配置已变更")
                        self.last_config_hashes[config_key] = config_hash
                        changes[config_key] = config_data
                        
                        # 保存配置
                        file_path = os.path.join(self.output_dir, f"{config_type}.json")
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"配置已保存到 {file_path}")
                        
                except Exception as e:
                    logger.error(f"获取 {config_type} 配置失败: {str(e)}")
            
            # 如果有变化且设置了回调函数，则调用回调
            if changes and self.callback:
                try:
                    self.callback(changes)
                except Exception as e:
                    logger.error(f"调用回调函数失败: {str(e)}")
            
            return changes
            
        except Exception as e:
            logger.error(f"即时更新配置失败: {str(e)}")
            return {}

    def _get_control_plane_configs(self) -> Dict[str, Any]:
        """获取控制平面配置"""
        changes = {}
        try:
            # 确保configuration被应用（有时会被重置）
            if self.configuration:
                client.Configuration.set_default(self.configuration)
                # 重新创建client以确保使用最新configuration
                self.k8s_client = client.CustomObjectsApi(client.ApiClient(self.configuration))
            
            # 处理 Istio 自定义资源
            istio_resources = [
                ("networking.istio.io", "v1alpha3", "virtualservices"),
                ("networking.istio.io", "v1alpha3", "destinationrules"),
                ("networking.istio.io", "v1alpha3", "gateways"),
                ("security.istio.io", "v1beta1", "authorizationpolicies"),
                ("networking.istio.io", "v1alpha3", "serviceentries"),
                ("networking.istio.io", "v1alpha3", "sidecars"),
                ("networking.istio.io", "v1alpha3", "workloadentries"),
                ("networking.istio.io", "v1alpha3", "workloadgroups"),
                ("networking.istio.io", "v1alpha3", "envoyfilters")
            ]
            
            # 处理 Istio 自定义资源
            for group, version, plural in istio_resources:
                try:
                    response = self.k8s_client.list_cluster_custom_object(
                        group=group,
                        version=version,
                        plural=plural
                    )
                    # 计算配置哈希
                    config_hash = self._calculate_hash(response)
                    config_key = f"control_plane_{plural}"
                    
                    # 检查配置是否有变化
                    if config_key not in self.last_config_hashes or self.last_config_hashes[config_key] != config_hash:
                        logger.info(f"控制平面 {plural} 配置已变更")
                        self.last_config_hashes[config_key] = config_hash
                        changes[config_key] = response
                        
                        # 为每种资源类型创建子目录
                        resource_dir = os.path.join(self.control_plane_dir, plural)
                        self._reset_directory(resource_dir)
                        
                        # 保存每个资源的 YAML 文件
                        for item in response.get('items', []):
                            metadata = item.get('metadata', {})
                            name = metadata.get('name', 'unknown')
                            namespace = metadata.get('namespace', 'default')
                            
                            # 创建命名空间子目录
                            ns_dir = os.path.join(resource_dir, namespace)
                            if not os.path.exists(ns_dir):
                                os.makedirs(ns_dir)
                            
                            # 保存为 YAML 文件
                            file_path = os.path.join(ns_dir, f"{name}.yaml")
                            with open(file_path, 'w', encoding='utf-8') as f:
                                yaml.dump(item, f, default_flow_style=False, allow_unicode=True)
                            logger.info(f"控制平面配置已保存到 {file_path}")
                        
                        # 同时保存完整的资源列表为 JSON（用于比较）
                        list_file = os.path.join(resource_dir, "list.json")
                        with open(list_file, 'w', encoding='utf-8') as f:
                            json.dump(response, f, ensure_ascii=False, indent=2)
                        
                except Exception as e:
                    logger.error(f"获取控制平面 {plural} 配置失败: {str(e)}")
                    continue
            
            # 处理 Kubernetes 核心服务资源
            try:
                # 创建 CoreV1Api 实例 - 使用相同的configuration
                if self.configuration:
                    api_client = client.ApiClient(self.configuration)
                else:
                    api_client = client.ApiClient()
                core_v1_api = client.CoreV1Api(api_client)
                
                # 获取所有命名空间的服务
                services = core_v1_api.list_service_for_all_namespaces()
                config_hash = self._calculate_hash(services)
                config_key = "core_services"
                
                if config_key not in self.last_config_hashes or self.last_config_hashes[config_key] != config_hash:
                    logger.info("核心服务配置已变更")
                    self.last_config_hashes[config_key] = config_hash
                    changes[config_key] = services
                    
                    # 保存服务配置
                    services_dir = os.path.join(self.control_plane_dir, "services")
                    self._reset_directory(services_dir)
                    
                    # 按命名空间组织服务
                    for service in services.items:
                        namespace = service.metadata.namespace
                        name = service.metadata.name
                        
                        # 创建命名空间子目录
                        ns_dir = os.path.join(services_dir, namespace)
                        if not os.path.exists(ns_dir):
                            os.makedirs(ns_dir)
                        
                        # 将服务对象转换为字典
                        service_dict = {
                            "apiVersion": "v1",
                            "kind": "Service",
                            "metadata": {
                                "name": service.metadata.name,
                                "namespace": service.metadata.namespace,
                                "labels": service.metadata.labels,
                                "annotations": service.metadata.annotations
                            },
                            "spec": {
                                "ports": [
                                    {
                                        "name": port.name,
                                        "port": port.port,
                                        "protocol": port.protocol,
                                        "targetPort": port.target_port
                                    } for port in service.spec.ports
                                ],
                                "selector": service.spec.selector,
                                "type": service.spec.type,
                                "clusterIP": service.spec.cluster_ip,
                                "sessionAffinity": service.spec.session_affinity
                            }
                        }
                        
                        # 保存为 YAML 文件
                        file_path = os.path.join(ns_dir, f"{name}.yaml")
                        with open(file_path, 'w', encoding='utf-8') as f:
                            yaml.dump(service_dict, f, default_flow_style=False, allow_unicode=True)
                        logger.info(f"服务配置已保存到 {file_path}")
                    
                    # 在保存 list.json 之前添加 datetime 处理
                    def _datetime_handler(obj):
                        if isinstance(obj, datetime.datetime):
                            return obj.isoformat()
                        return obj

                    # 修改保存 JSON 的代码
                    list_file = os.path.join(services_dir, "list.json")
                    with open(list_file, 'w', encoding='utf-8') as f:
                        json.dump([service.to_dict() for service in services.items], 
                                 f, ensure_ascii=False, indent=2, default=_datetime_handler)
                
            except Exception as e:
                logger.error(f"获取核心服务配置失败: {str(e)}")
            
        except Exception as e:
            logger.error(f"获取控制平面配置失败: {str(e)}")
        
        return changes

    def request_update(self) -> None:
        """请求更新配置（异步）"""
        current_time = time.time()
        # 检查距离上次更新是否已经超过5秒
        if current_time - self.last_update_time < 5:
            logger.info("更新请求太频繁，已忽略")
            return
            
        self.last_update_time = current_time
        self.update_queue.put(None)
        logger.info("已请求更新配置")

    def _refresh_k8s_token(self) -> None:
        """重新初始化 Kubernetes 客户端"""
        try:
            logger.info("重新初始化 Kubernetes 客户端")
            self._init_k8s_client()
        except Exception as e:
            logger.error(f"重新初始化 Kubernetes 客户端失败: {str(e)}")

    def _watch_k8s_resources(self):
        """监控 Kubernetes 资源变化"""
        if not self.k8s_client:
            logger.error("Kubernetes 客户端未初始化，无法监控资源变化")
            return
        
        while self.running:
            try:
                # 监控所有 Istio 相关资源
                resources = [
                    ("networking.istio.io", "v1alpha3", "virtualservices"),
                    ("networking.istio.io", "v1alpha3", "destinationrules"),
                    ("networking.istio.io", "v1alpha3", "gateways"),
                    ("security.istio.io", "v1beta1", "authorizationpolicies"),
                    ("networking.istio.io", "v1alpha3", "serviceentries"),
                    ("networking.istio.io", "v1alpha3", "sidecars"),
                    ("networking.istio.io", "v1alpha3", "workloadentries"),
                    ("networking.istio.io", "v1alpha3", "workloadgroups"),
                    ("networking.istio.io", "v1alpha3", "envoyfilters")
                ]
                
                for group, version, plural in resources:
                    w = watch.Watch()
                    try:
                        for event in w.stream(
                            self.k8s_client.list_cluster_custom_object,
                            group=group,
                            version=version,
                            plural=plural,
                            timeout_seconds=60
                        ):
                            if not self.running:
                                break
                            
                            event_type = event['type']
                            resource = event['object']
                            resource_name = resource['metadata']['name']
                            resource_namespace = resource['metadata'].get('namespace', 'default')
                            
                            # 记录详细的变更信息
                            logger.info(f"检测到 {plural} 变更: {event_type} {resource_namespace}/{resource_name}")
                            
                            # 如果是删除操作，记录被删除的资源详情
                            if event_type == 'DELETED':
                                logger.info(f"删除的资源详情: {json.dumps(resource, ensure_ascii=False, indent=2)}")
                            
                            # 触发配置更新
                            self.request_update()
                            
                    except client.rest.ApiException as e:
                        if e.status == 401:  # Unauthorized
                            logger.warning(f"认证失败，尝试重新初始化客户端，详细信息：{e.body}")
                            self._refresh_k8s_token()
                            time.sleep(5)
                            continue
                        else:
                            logger.error(f"监控 {plural} 资源时出错: {str(e)},详细信息：{e.body}")
                            if not self.running:
                                break
                            time.sleep(5)
                            continue
                    except Exception as e:
                        logger.error(f"监控 {plural} 资源时出错: {str(e)},详细信息：{e.body}")
                        if not self.running:
                            break
                        time.sleep(5)
                        continue
                    
                if not self.running:
                    break
                
            except Exception as e:
                logger.error(f"监控 Kubernetes 资源时出错: {str(e)}")
                if not self.running:
                    break
                time.sleep(5)

    def _calculate_hash(self, data: Any) -> str:
        """计算数据的哈希值"""
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data, sort_keys=True)
        else:
            data_str = str(data)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def _save_config(self, name: str, data: Any) -> None:
        """保存配置到文件"""
        file_path = os.path.join(self.output_dir, f"{name}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"配置已保存到 {file_path}")
    
    def _check_proxy_changes(self) -> Set[str]:
        """检查代理列表是否有变化，返回新增的代理"""
        try:
            current_proxies = set(self.api.get_proxies())
            new_proxies = current_proxies - self.proxies_cache
            removed_proxies = self.proxies_cache - current_proxies
            
            if new_proxies:
                logger.info(f"发现新增代理: {new_proxies}")
            
            if removed_proxies:
                logger.info(f"代理已移除: {removed_proxies}")
            
            self.proxies_cache = current_proxies
            return new_proxies
        except Exception as e:
            logger.error(f"检查代理变化失败: {str(e)}")
            return set()
    
    def _check_sidecar_config_changes(self) -> Dict[str, Any]:
        """
        检查 Sidecar 配置是否有变化
        
        返回:
            变化的配置项字典 {配置名: 新配置数据}
        """
        changes = {}
        
        try:
            # 检查代理列表变化
            new_proxies = self._check_proxy_changes()
            
            # 获取所有代理的配置
            for proxy_id in self.proxies_cache:
                # 只处理指定命名空间的代理
                if self.namespace != "all" and not proxy_id.endswith(f".{self.namespace}"):
                    continue
                
                # 为每个代理创建目录
                proxy_dir = os.path.join(self.output_dir, proxy_id)
                if not os.path.exists(proxy_dir):
                    os.makedirs(proxy_dir)
                
                # 获取每种类型的配置
                for config_type in self.config_types:
                    try:
                        logger.info(f"获取代理 {proxy_id} 的 {config_type} 配置")
                        config_data = self.api.get_proxy_config(proxy_id, config_type)
                        config_hash = self._calculate_hash(config_data)
                        config_key = f"{proxy_id}_{config_type}"
                        
                        if config_key not in self.last_config_hashes or self.last_config_hashes[config_key] != config_hash:
                            logger.info(f"代理 {proxy_id} 的 {config_type} 配置已变更")
                            self.last_config_hashes[config_key] = config_hash
                            changes[config_key] = config_data
                            
                            # 保存到代理专用目录
                            file_path = os.path.join(proxy_dir, f"{config_type}.json")
                            with open(file_path, 'w', encoding='utf-8') as f:
                                json.dump(config_data, f, ensure_ascii=False, indent=2)
                            logger.info(f"配置已保存到 {file_path}")
                    except Exception as e:
                        logger.error(f"获取代理 {proxy_id} 的 {config_type} 配置失败: {str(e)}")
        
        except Exception as e:
            logger.error(f"检查 Sidecar 配置失败: {str(e)}")
        
        return changes
    
    def _monitor_loop(self) -> None:
        """监控循环"""
        logger.info("开始监控 Istio Sidecar 配置")
        
        while self.running:
            try:
                start_time = time.time()
                
                # 检查是否有即时更新请求
                try:
                    # 使用非阻塞方式获取更新请求
                    if not self.update_queue.empty():
                        _ = self.update_queue.get_nowait()
                        self.update_now()
                except queue.Empty:
                    pass
                
                # 执行定期检查
                current_time = time.time()
                if current_time - self.last_update_time >= self.interval:
                    logger.info(f"检查 Sidecar 配置变更 - {datetime.datetime.now()}")
                    self.update_now()
                    self.last_update_time = current_time
                
                # 等待一小段时间
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"监控循环发生错误: {str(e)}")
                time.sleep(5)  # 出错后等待短暂时间再继续
        
        logger.info("停止监控 Istio Sidecar 配置")
    
    def start(self) -> None:
        """启动监控"""
        if self.running:
            logger.warning("监控器已在运行")
            return
        
        self.running = True
        
        # 启动 Kubernetes 资源监控
        if self.k8s_client:
            self.k8s_watch_thread = threading.Thread(target=self._watch_k8s_resources)
            self.k8s_watch_thread.daemon = True
            self.k8s_watch_thread.start()
            logger.info("已启动 Kubernetes 资源监控")
        
        # 启动定期检查线程
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info(f"监控器已启动，检查间隔: {self.interval} 秒")
    
    def stop(self) -> None:
        """停止监控"""
        if not self.running:
            logger.warning("监控器未在运行")
            return
        
        self.running = False
        
        # 停止监控线程
        if self.monitor_thread:
            self.monitor_thread.join(timeout=self.interval + 5)
        
        # 停止 Kubernetes 监控线程
        if self.k8s_watch_thread:
            self.k8s_watch_thread.join(timeout=5)
        
        logger.info("监控器已停止")
    
    def export_current_config(self) -> None:
        """导出当前 Sidecar 配置"""
        try:
            logger.info("导出当前 Istio Sidecar 配置")
            
            # 获取代理列表
            proxies = self.api.get_proxies()
            self.proxies_cache = set(proxies)
            
            # 导出每个代理的配置
            for proxy_id in proxies[0]:
                # 只处理指定命名空间的代理
                if self.namespace != "all" and not proxy_id.endswith(f".{self.namespace}"):
                    continue
                
                logger.info(f"导出代理 {proxy_id} 的配置")
                
                # 为每个代理创建目录
                proxy_dir = os.path.join(self.output_dir, proxy_id)
                if not os.path.exists(proxy_dir):
                    os.makedirs(proxy_dir)
                
                # 导出每种类型的配置
                for config_type in self.config_types:
                    try:
                        config_data = self.api.get_proxy_config(proxy_id, config_type)
                        
                        # 保存到代理专用目录
                        file_path = os.path.join(proxy_dir, f"{config_type}.json")
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f, ensure_ascii=False, indent=2)
                        
                        # 更新哈希值
                        self.last_config_hashes[f"{proxy_id}_{config_type}"] = self._calculate_hash(config_data)
                        
                        logger.info(f"已导出 {proxy_id} 的 {config_type} 配置到 {file_path}")
                    except Exception as e:
                        logger.error(f"导出代理 {proxy_id} 的 {config_type} 配置失败: {str(e)}")
            
            logger.info(f"Sidecar 配置已导出到 {self.output_dir}")
        except Exception as e:
            logger.error(f"导出 Sidecar 配置失败: {str(e)}")


def config_changed_callback(changes):
    """配置变更回调函数示例"""
    print(f"\nSidecar 配置变更通知 - {datetime.datetime.now()}")
    print(f"变更项数量: {len(changes)}")
    for key in changes.keys():
        print(f"  - {key}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Istio Sidecar 配置监控工具",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
示例用法:
  python istio_sidecar_monitor.py --vm-host 192.168.1.100 --vm-user root --vm-password yourpassword
  python istio_sidecar_monitor.py --vm-host 192.168.1.100 --vm-user root --vm-key-file /path/to/key --namespace default
  python istio_sidecar_monitor.py --vm-host 192.168.1.100 --update-now
参数说明:
  --vm-host         (必填) 虚拟机主机名或IP
  --vm-user         (可选) 虚拟机用户名，默认root
  --vm-password     (可选) 虚拟机密码
  --vm-key-file     (可选) 虚拟机SSH密钥文件
  --namespace       (可选) 监控的命名空间，默认default
  --config-types    (可选) 获取的配置类型，默认routes
  --update-now      (可选) 立即更新配置后退出
  --export-only     (可选) 仅导出当前配置后退出
        """
    )
    parser.add_argument("--interval", type=int, default=1200, help="检查间隔（秒）")
    parser.add_argument("--output-dir", default="./istio_sidecar_config", help="配置输出目录")
    parser.add_argument("--namespace", default="default", help="要监控的命名空间，使用 'all' 监控所有命名空间")
    parser.add_argument("--config-types", default="routes", help="要获取的配置类型，用逗号分隔")
    parser.add_argument("--vm-host", help="虚拟机主机")
    parser.add_argument("--vm-port", type=int, default=22, help="虚拟机 SSH 端口")
    parser.add_argument("--vm-user", default="root", help="虚拟机用户名")
    parser.add_argument("--vm-password", help="虚拟机密码")
    parser.add_argument("--vm-key-file", help="虚拟机 SSH 密钥文件")
    parser.add_argument("--k8s-host", help="Kubernetes API 服务器地址")
    parser.add_argument("--k8s-token", help="Kubernetes API 认证 token")
    parser.add_argument("--export-only", action="store_true", help="仅导出当前配置，不启动监控")
    parser.add_argument("--update-now", action="store_true", help="立即更新配置")

    args = parser.parse_args()

    # 检查是否在 K8s 环境中
    try:
        from utils.env_detector import K8sEnvDetector
        is_in_k8s = K8sEnvDetector.is_in_kubernetes() or K8sEnvDetector.is_kubectl_available()
    except:
        # 简单检测
        is_in_k8s = os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token') or os.environ.get('KUBERNETES_SERVICE_HOST')
    
    # 如果不在 K8s 环境中且未提供 SSH 配置，则报错
    if not is_in_k8s and not args.vm_host:
        parser.print_help()
        print("\n错误：不在 K8s 环境中时，--vm-host 是必填参数，请指定虚拟机主机名或IP。")
        print("提示：如果在 K8s Pod 中运行或本地有 kubectl 配置，则不需要 SSH 配置。")
        sys.exit(1)

    # 解析配置类型
    config_types = args.config_types.split(',')

    # 创建监控器
    monitor = IstioSidecarMonitor(
        interval=args.interval,
        output_dir=args.output_dir,
        namespace=args.namespace,
        config_types=config_types,
        use_vm=True,
        vm_host=args.vm_host,
        vm_port=args.vm_port,
        vm_user=args.vm_user,
        vm_password=args.vm_password,
        vm_key_file=args.vm_key_file,
        k8s_host=args.k8s_host,
        k8s_token=args.k8s_token,
        callback=config_changed_callback
    )
    
    # 如果是立即更新模式
    if args.update_now:
        monitor.update_now()
        return
    
    # 如果是仅导出模式
    if args.export_only:
        monitor.export_current_config()
        return
    
    try:
        # 启动监控
        monitor.start()
        
        print("监控器已启动")
        print("- 按 Enter 键立即更新配置")
        print("- 按 Ctrl+C 停止监控")
        
        # 等待用户输入或中断
        while True:
            try:
                # 使用超时等待，这样既可以响应用户输入，也可以响应 Ctrl+C
                user_input = input()
                monitor.request_update()
            except EOFError:
                time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n用户中断，停止监控")
    
    finally:
        # 停止监控
        monitor.stop()


if __name__ == "__main__":
    main()