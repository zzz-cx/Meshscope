import paramiko
import subprocess
import threading
from .env_detector import K8sEnvDetector

class SSHClient:
    def __init__(self, hostname=None, username=None, password=None, key_filename=None, port=22, reuse_connection=True):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.port = port
        self._use_ssh = K8sEnvDetector.should_use_ssh(self)
        self._reuse_connection = reuse_connection
        self._ssh_client = None
        self._lock = threading.Lock()  # 线程安全锁

    def _get_ssh_client(self):
        """获取或创建 SSH 客户端连接（支持连接复用）"""
        if not self._use_ssh:
            return None
        
        if not self.hostname:
            raise ValueError("SSH 配置不完整：需要提供 hostname")
        
        # 如果启用连接复用且连接已存在且活跃，直接返回
        if self._reuse_connection and self._ssh_client:
            try:
                # 检查连接是否仍然活跃
                transport = self._ssh_client.get_transport()
                if transport and transport.is_active():
                    return self._ssh_client
            except:
                # 连接已断开，需要重新创建
                self._ssh_client = None
        
        # 需要创建新连接
        with self._lock:
            # 双重检查，避免多线程重复创建
            if self._reuse_connection and self._ssh_client:
                try:
                    transport = self._ssh_client.get_transport()
                    if transport and transport.is_active():
                        return self._ssh_client
                except:
                    self._ssh_client = None
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                timeout=10  # 设置连接超时
            )
            
            if self._reuse_connection:
                self._ssh_client = ssh
            
            return ssh

    def run_command(self, command):
        """
        执行命令，自动检测环境：
        - 如果在 K8s 环境中或 kubectl 可用，直接本地执行
        - 否则通过 SSH 执行（支持连接复用）
        """
        # 如果不需要 SSH，直接本地执行
        if not self._use_ssh:
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True
                )
                return result.stdout, result.stderr
            except Exception as e:
                return "", str(e)
        
        # 使用 SSH 执行（支持连接复用）
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(command)
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            # 如果未启用连接复用，立即关闭连接
            if not self._reuse_connection:
                ssh.close()
            
            return output, error
        except Exception as e:
            # 如果出错，关闭连接并重新创建
            if self._reuse_connection and self._ssh_client == ssh:
                try:
                    ssh.close()
                except:
                    pass
                self._ssh_client = None
            return "", str(e)

    def close(self):
        """显式关闭 SSH 连接"""
        if self._ssh_client:
            try:
                self._ssh_client.close()
            except:
                pass
            self._ssh_client = None

    def __del__(self):
        """析构函数，确保连接被关闭"""
        self.close()