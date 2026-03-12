"""
K8s 环境检测工具
自动检测是否在 Kubernetes Pod 环境中运行
"""
import os
import subprocess
import socket
from typing import Optional

class K8sEnvDetector:
    """Kubernetes 环境检测器"""
    
    _is_in_k8s: Optional[bool] = None
    _kubectl_available: Optional[bool] = None
    
    @classmethod
    def is_in_kubernetes(cls) -> bool:
        """
        检测是否在 Kubernetes Pod 环境中运行
        
        检测方法：
        1. 检查是否存在 ServiceAccount token 文件
        2. 检查环境变量 KUBERNETES_SERVICE_HOST
        3. 检查是否能访问 Kubernetes API
        """
        if cls._is_in_k8s is not None:
            return cls._is_in_k8s
        
        # 方法1: 检查 ServiceAccount token 文件
        if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
            cls._is_in_k8s = True
            return True
        
        # 方法2: 检查环境变量
        if os.environ.get('KUBERNETES_SERVICE_HOST'):
            cls._is_in_k8s = True
            return True
        
        # 方法3: 检查是否能访问 Kubernetes API
        try:
            result = subprocess.run(
                ['kubectl', 'cluster-info'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                cls._is_in_k8s = True
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        cls._is_in_k8s = False
        return False
    
    @classmethod
    def is_kubectl_available(cls) -> bool:
        """检测 kubectl 命令是否可用"""
        if cls._kubectl_available is not None:
            return cls._kubectl_available
        
        try:
            result = subprocess.run(
                ['kubectl', 'version', '--client'],
                capture_output=True,
                text=True,
                timeout=5
            )
            cls._kubectl_available = (result.returncode == 0)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            cls._kubectl_available = False
        
        return cls._kubectl_available
    
    @classmethod
    def get_local_ip_addresses(cls) -> list:
        """获取本机IP地址列表"""
        local_ips = []
        try:
            # 获取主机名
            hostname = socket.gethostname()
            # 获取本机IP地址
            local_ip = socket.gethostbyname(hostname)
            local_ips.append(local_ip)
            
            # 获取所有网络接口的IP地址
            try:
                # 连接到一个远程地址来获取本机IP（不实际发送数据）
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                if local_ip not in local_ips:
                    local_ips.append(local_ip)
            except Exception:
                pass
            
            # 添加localhost相关地址
            local_ips.extend(['127.0.0.1', 'localhost', '::1'])
        except Exception:
            pass
        
        return local_ips
    
    @classmethod
    def is_host_local(cls, host: Optional[str]) -> bool:
        """判断主机地址是否为本机"""
        if not host:
            return True  # 如果没有指定主机，认为是本机
        
        # 标准化主机地址
        host = host.strip().lower()
        
        # 检查是否是localhost相关
        if host in ['localhost', '127.0.0.1', '::1', '0.0.0.0']:
            return True
        
        # 获取本机IP地址列表
        local_ips = cls.get_local_ip_addresses()
        
        # 检查主机地址是否在本机IP列表中
        if host in [ip.lower() for ip in local_ips]:
            return True
        
        # 尝试解析主机名
        try:
            resolved_ip = socket.gethostbyname(host)
            if resolved_ip in local_ips:
                return True
        except Exception:
            pass
        
        return False
    
    @classmethod
    def should_use_ssh(cls, ssh_client=None, use_vm: bool = True, vm_host: Optional[str] = None) -> bool:
        """
        判断是否应该使用 SSH
        
        新逻辑：
        - 如果主机地址和本机不一致，就使用SSH
        - 如果主机地址为本机或未指定，则检查kubectl是否可用
        """
        # 如果提供了vm_host，检查是否为本机
        if vm_host:
            if not cls.is_host_local(vm_host):
                # 主机地址和本机不一致，使用SSH
                return use_vm and ssh_client is not None
        
        # 如果主机地址为本机或未指定，检查kubectl是否可用
        # 如果在 K8s 环境中 或 kubectl 可用 -> 不使用 SSH
        if cls.is_in_kubernetes() or cls.is_kubectl_available():
            return False
        
        # 不在 K8s 环境中 且 kubectl 不可用 -> 使用 SSH（如果提供了 ssh_client 且 use_vm=True）
        return use_vm and ssh_client is not None
    
    @classmethod
    def reset_cache(cls):
        """重置缓存（用于测试）"""
        cls._is_in_k8s = None
        cls._kubectl_available = None

