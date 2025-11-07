import subprocess
from typing import List, Optional
from .env_detector import K8sEnvDetector

class PodLogFetcher:
    @staticmethod
    def get_pod_logs(pod_name: str, namespace: str = 'default', container: Optional[str] = None, tail_lines: int = 200, ssh_client=None) -> str:
        """
        获取指定 pod/container 的日志，自动检测环境。
        """
        cmd = [
            "kubectl", "logs", pod_name, "-n", namespace, "--tail", str(tail_lines)
        ]
        if container:
            cmd += ["-c", container]
        
        # 根据环境选择执行方式
        if ssh_client and K8sEnvDetector.should_use_ssh(ssh_client):
            # 使用 SSH
            cmd_str = ' '.join(cmd)
            output, error = ssh_client.run_command(cmd_str)
            if error:
                raise RuntimeError(f"获取日志失败: {error}")
            return output
        else:
            # 本地执行
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout
            else:
                raise RuntimeError(f"获取日志失败: {result.stderr}")

    @staticmethod
    def get_pods_by_label(label_selector: str, namespace: str = 'default', ssh_client=None) -> List[str]:
        """
        根据 label selector 获取 pod 名称列表，自动检测环境。
        """
        cmd = [
            "kubectl", "get", "pods", "-n", namespace, "-l", label_selector, "-o", "jsonpath={.items[*].metadata.name}"
        ]
        
        # 根据环境选择执行方式
        if ssh_client and K8sEnvDetector.should_use_ssh(ssh_client):
            # 使用 SSH
            cmd_str = ' '.join(cmd)
            output, error = ssh_client.run_command(cmd_str)
            if error:
                raise RuntimeError(f"获取 pod 列表失败: {error}")
            return output.strip().split()
        else:
            # 本地执行
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split()
            else:
                raise RuntimeError(f"获取 pod 列表失败: {result.stderr}")

    @staticmethod
    def get_pod_logs_via_ssh(ssh_client, pod_name: str, namespace: str = 'default', container: Optional[str] = None, tail_lines: int = 200) -> str:
        """
        通过 SSHClient 在远程主机上获取 pod/container 的日志（兼容性方法）。
        """
        return PodLogFetcher.get_pod_logs(pod_name, namespace, container, tail_lines, ssh_client)

    @staticmethod
    def get_pods_by_label_via_ssh(ssh_client, label_selector: str, namespace: str = 'default') -> List[str]:
        """
        通过 SSHClient 在远程主机上根据 label selector 获取 pod 名称列表（兼容性方法）。
        """
        return PodLogFetcher.get_pods_by_label(label_selector, namespace, ssh_client)
