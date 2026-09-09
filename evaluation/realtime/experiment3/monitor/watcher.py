#!/usr/bin/env python3
"""
配置变更监听器 - 监听Istio配置变更事件
"""

import os
import sys
import json
import time
import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import subprocess
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))

try:
    from kubernetes import client, config, watch
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False


class ConfigChangeEvent:
    """配置变更事件"""
    
    def __init__(self, event_type: str, resource_type: str, resource_name: str, 
                 namespace: str = "default", timestamp: datetime = None):
        self.event_type = event_type  # ADDED, MODIFIED, DELETED
        self.resource_type = resource_type  # VirtualService, DestinationRule, etc.
        self.resource_name = resource_name
        self.namespace = namespace
        self.timestamp = timestamp or datetime.now()
        self.event_id = f"{self.resource_type}_{self.resource_name}_{int(self.timestamp.timestamp())}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "namespace": self.namespace,
            "timestamp": self.timestamp.isoformat()
        }


class FileSystemWatcher(FileSystemEventHandler):
    """文件系统监听器"""
    
    def __init__(self, callback: Callable[[ConfigChangeEvent], None]):
        self.callback = callback
        self.last_modified = {}
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith(('.yaml', '.yml')):
            # 避免重复触发
            current_time = time.time()
            if event.src_path in self.last_modified:
                if current_time - self.last_modified[event.src_path] < 1.0:
                    return
            
            self.last_modified[event.src_path] = current_time
            
            # 解析文件名获取资源信息
            resource_info = self._parse_file_path(event.src_path)
            if resource_info:
                change_event = ConfigChangeEvent(
                    event_type="MODIFIED",
                    resource_type=resource_info["resource_type"],
                    resource_name=resource_info["resource_name"],
                    namespace=resource_info.get("namespace", "default")
                )
                self.callback(change_event)
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith(('.yaml', '.yml')):
            resource_info = self._parse_file_path(event.src_path)
            if resource_info:
                change_event = ConfigChangeEvent(
                    event_type="ADDED",
                    resource_type=resource_info["resource_type"],
                    resource_name=resource_info["resource_name"],
                    namespace=resource_info.get("namespace", "default")
                )
                self.callback(change_event)
    
    def on_deleted(self, event):
        if event.is_directory:
            return
        
        if event.src_path.endswith(('.yaml', '.yml')):
            resource_info = self._parse_file_path(event.src_path)
            if resource_info:
                change_event = ConfigChangeEvent(
                    event_type="DELETED",
                    resource_type=resource_info["resource_type"],
                    resource_name=resource_info["resource_name"],
                    namespace=resource_info.get("namespace", "default")
                )
                self.callback(change_event)
    
    def _parse_file_path(self, file_path: str) -> Optional[Dict[str, str]]:
        """从文件路径解析资源信息"""
        try:
            # 尝试从文件名推断资源类型
            filename = os.path.basename(file_path).lower()
            
            if "virtualservice" in filename or "virtual-service" in filename:
                resource_type = "VirtualService"
            elif "destinationrule" in filename or "destination-rule" in filename:
                resource_type = "DestinationRule"
            elif "gateway" in filename:
                resource_type = "Gateway"
            elif "service" in filename and "virtual" not in filename:
                resource_type = "Service"
            elif "authorizationpolicy" in filename:
                resource_type = "AuthorizationPolicy"
            else:
                # 尝试解析文件内容
                return self._parse_file_content(file_path)
            
            # 从文件名提取资源名称
            resource_name = filename.replace(".yaml", "").replace(".yml", "")
            resource_name = resource_name.replace("-", "")
            
            return {
                "resource_type": resource_type,
                "resource_name": resource_name,
                "namespace": "default"
            }
            
        except Exception as e:
            print(f"Error parsing file path {file_path}: {e}")
            return None
    
    def _parse_file_content(self, file_path: str) -> Optional[Dict[str, str]]:
        """从文件内容解析资源信息"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                doc = yaml.safe_load(f)
                
            if not doc:
                return None
            
            metadata = doc.get("metadata", {})
            kind = doc.get("kind", "")
            
            return {
                "resource_type": kind,
                "resource_name": metadata.get("name", ""),
                "namespace": metadata.get("namespace", "default")
            }
            
        except Exception as e:
            print(f"Error parsing file content {file_path}: {e}")
            return None


class KubernetesWatcher:
    """Kubernetes API监听器"""
    
    def __init__(self, callback: Callable[[ConfigChangeEvent], None], 
                 namespace: str = "default"):
        self.callback = callback
        self.namespace = namespace
        self.running = False
        self.watch_threads = []
        self.resource_types = [
            "virtualservices",
            "destinationrules", 
            "gateways",
            "authorizationpolicies",
            "services"
        ]
    
    def start(self):
        """启动Kubernetes监听"""
        if not KUBERNETES_AVAILABLE:
            print("Kubernetes client not available, skipping Kubernetes watcher")
            return
        
        try:
            # 加载kubeconfig
            config.load_kube_config()
            self.running = True
            
            # 为每种资源类型启动监听线程
            for resource_type in self.resource_types:
                thread = threading.Thread(
                    target=self._watch_resource,
                    args=(resource_type,),
                    daemon=True
                )
                thread.start()
                self.watch_threads.append(thread)
                
        except Exception as e:
            print(f"Error starting Kubernetes watcher: {e}")
    
    def stop(self):
        """停止Kubernetes监听"""
        self.running = False
        for thread in self.watch_threads:
            thread.join(timeout=1.0)
    
    def _watch_resource(self, resource_type: str):
        """监听特定资源类型"""
        try:
            v1 = client.CustomObjectsApi()
            group = "networking.istio.io"
            version = "v1alpha3"
            
            if resource_type == "services":
                # 服务使用标准API
                v1_core = client.CoreV1Api()
                w = watch.Watch()
                for event in w.stream(v1_core.list_namespaced_service, namespace=self.namespace):
                    if not self.running:
                        break
                    
                    self._handle_k8s_event(event, "Service")
            else:
                # Istio资源使用自定义API
                w = watch.Watch()
                for event in w.stream(v1.list_namespaced_custom_object,
                                    group=group,
                                    version=version,
                                    namespace=self.namespace,
                                    plural=resource_type):
                    if not self.running:
                        break
                    
                    self._handle_k8s_event(event, self._format_resource_type(resource_type))
                    
        except Exception as e:
            print(f"Error watching {resource_type}: {e}")
    
    def _handle_k8s_event(self, event: Dict[str, Any], resource_type: str):
        """处理Kubernetes事件"""
        try:
            event_type = event.get("type", "").upper()
            resource = event.get("object", {})
            metadata = resource.get("metadata", {})
            
            resource_name = metadata.get("name", "")
            namespace = metadata.get("namespace", self.namespace)
            
            if resource_name:
                change_event = ConfigChangeEvent(
                    event_type=event_type,
                    resource_type=resource_type,
                    resource_name=resource_name,
                    namespace=namespace
                )
                self.callback(change_event)
                
        except Exception as e:
            print(f"Error handling K8s event: {e}")
    
    def _format_resource_type(self, resource_type: str) -> str:
        """格式化资源类型名称"""
        type_map = {
            "virtualservices": "VirtualService",
            "destinationrules": "DestinationRule",
            "gateways": "Gateway",
            "authorizationpolicies": "AuthorizationPolicy"
        }
        return type_map.get(resource_type, resource_type)


class ConfigWatcher:
    """配置变更监听器主类"""
    
    def __init__(self, watch_paths: List[str] = None, namespace: str = "default"):
        self.watch_paths = watch_paths or []
        self.namespace = namespace
        self.observers = []
        self.kubernetes_watcher = None
        self.change_events = []
        self.callbacks = []
        self.running = False
    
    def add_callback(self, callback: Callable[[ConfigChangeEvent], None]):
        """添加变更回调函数"""
        self.callbacks.append(callback)
    
    def start(self):
        """启动监听"""
        self.running = True
        
        # 启动文件系统监听
        for watch_path in self.watch_paths:
            if os.path.exists(watch_path):
                observer = Observer()
                event_handler = FileSystemWatcher(self._handle_change_event)
                observer.schedule(event_handler, watch_path, recursive=True)
                observer.start()
                self.observers.append(observer)
                print(f"Started watching path: {watch_path}")
        
        # 启动Kubernetes API监听
        self.kubernetes_watcher = KubernetesWatcher(self._handle_change_event, self.namespace)
        self.kubernetes_watcher.start()
        
        print("Config watcher started")
    
    def stop(self):
        """停止监听"""
        self.running = False
        
        # 停止文件系统监听
        for observer in self.observers:
            observer.stop()
            observer.join()
        
        # 停止Kubernetes监听
        if self.kubernetes_watcher:
            self.kubernetes_watcher.stop()
        
        print("Config watcher stopped")
    
    def _handle_change_event(self, event: ConfigChangeEvent):
        """处理配置变更事件"""
        self.change_events.append(event)
        
        # 调用所有注册的回调函数
        for callback in self.callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Error in callback: {e}")
        
        print(f"Config change detected: {event.to_dict()}")
    
    def get_recent_events(self, duration_seconds: int = 300) -> List[ConfigChangeEvent]:
        """获取最近的变更事件"""
        cutoff_time = datetime.now().timestamp() - duration_seconds
        
        return [
            event for event in self.change_events 
            if event.timestamp.timestamp() > cutoff_time
        ]
    
    def clear_events(self):
        """清空事件历史"""
        self.change_events.clear()


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Istio配置变更监听器")
    parser.add_argument("--watch-paths", nargs="+", help="监听路径列表")
    parser.add_argument("--namespace", default="default", help="Kubernetes命名空间")
    parser.add_argument("--duration", type=int, default=300, help="监听持续时间（秒）")
    
    args = parser.parse_args()
    
    # 默认监听当前目录
    watch_paths = args.watch_paths or ["."]
    
    def print_event(event: ConfigChangeEvent):
        print(f"[{event.timestamp}] {event.event_type} {event.resource_type}/{event.resource_name}")
    
    watcher = ConfigWatcher(watch_paths, args.namespace)
    watcher.add_callback(print_event)
    
    try:
        watcher.start()
        print(f"Watching for {args.duration} seconds...")
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        watcher.stop()
        
        # 打印统计信息
        recent_events = watcher.get_recent_events(args.duration)
        print(f"\nDetected {len(recent_events)} config changes in the last {args.duration} seconds")


if __name__ == "__main__":
    main()
