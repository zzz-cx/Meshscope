import subprocess
from typing import List, Optional

class PodLogFetcher:
    @staticmethod
    def get_pod_logs(pod_name: str, namespace: str = 'default', container: Optional[str] = None, tail_lines: int = 200) -> str:
        """
        本地获取指定 pod/container 的日志。
        """
        cmd = [
            "kubectl", "logs", pod_name, "-n", namespace, "--tail", str(tail_lines)
        ]
        if container:
            cmd += ["-c", container]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        else:
            raise RuntimeError(f"获取日志失败: {result.stderr}")

    @staticmethod
    def get_pods_by_label(label_selector: str, namespace: str = 'default') -> List[str]:
        """
        本地根据 label selector 获取 pod 名称列表。
        """
        cmd = [
            "kubectl", "get", "pods", "-n", namespace, "-l", label_selector, "-o", "jsonpath={.items[*].metadata.name}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip().split()
        else:
            raise RuntimeError(f"获取 pod 列表失败: {result.stderr}")

    @staticmethod
    def get_pod_logs_via_ssh(ssh_client, pod_name: str, namespace: str = 'default', container: Optional[str] = None, tail_lines: int = 200) -> str:
        """
        通过 SSHClient 在远程主机上获取 pod/container 的日志。
        """
        cmd = f"kubectl logs {pod_name} -n {namespace} --tail={tail_lines}"
        if container:
            cmd += f" -c {container}"
        output, error = ssh_client.run_command(cmd)
        if error:
            raise RuntimeError(f"获取日志失败: {error}")
        return output

    @staticmethod
    def get_pods_by_label_via_ssh(ssh_client, label_selector: str, namespace: str = 'default') -> List[str]:
        """
        通过 SSHClient 在远程主机上根据 label selector 获取 pod 名称列表。
        """
        cmd = f"kubectl get pods -n {namespace} -l {label_selector} -o jsonpath='{{.items[*].metadata.name}}'"
        output, error = ssh_client.run_command(cmd)
        if error:
            raise RuntimeError(f"获取 pod 列表失败: {error}")
        return output.strip().split()
