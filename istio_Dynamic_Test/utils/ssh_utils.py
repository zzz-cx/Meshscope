import paramiko
import subprocess
from .env_detector import K8sEnvDetector

class SSHClient:
    def __init__(self, hostname=None, username=None, password=None, key_filename=None, port=22):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.port = port
        self._use_ssh = K8sEnvDetector.should_use_ssh(self)

    def run_command(self, command):
        """
        执行命令，自动检测环境：
        - 如果在 K8s 环境中或 kubectl 可用，直接本地执行
        - 否则通过 SSH 执行
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
        
        # 使用 SSH 执行
        if not self.hostname:
            raise ValueError("SSH 配置不完整：需要提供 hostname")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self.hostname,
            port=self.port,
            username=self.username,
            password=self.password,
            key_filename=self.key_filename
        )
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        return output, error