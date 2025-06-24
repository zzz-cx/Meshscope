import time

class FaultInjector:
    """
    用于在测试期间通过 SSH 在集群主机上模拟下游服务的故障。
    """
    def __init__(self, ssh_client):
        self.ssh_client = ssh_client
        print("🔧 FaultInjector initialized. (SSH模式)")

    def inject_http_fault(self, service_name, error_code=503):
        """
        为指定服务注入一个返回特定错误码的故障。
        
        这在实际实现中可能需要与 Kubernetes API 或服务网格的调试端点交互。
        例如，创建一个临时的 Istio FaultInjection 规则。
        """
        print(f"🔥 [INJECTING FAULT] 为服务 '{service_name}' 注入 HTTP {error_code} 故障...")
        # 这里假设有一个预定义的 YAML 文件用于注入故障
        yaml_path = f"/tmp/fault_injection_{service_name}_{error_code}.yaml"
        # 你可以根据实际情况动态生成 yaml 文件并上传到主机
        cmd = f"kubectl apply -f {yaml_path}"
        output, error = self.ssh_client.run_command(cmd)
        print(f"  - 注入故障输出: {output.strip()}")
        if error:
            print(f"  - 注入故障错误: {error.strip()}")

    def clear_faults(self, service_name):
        """
        清除为指定服务注入的所有故障。
        
        这在实际实现中需要删除之前创建的 Istio 规则。
        """
        print(f"🧹 [CLEARING FAULT] 清除服务 '{service_name}' 的所有故障...")
        # 假设故障注入规则名为 fault-injection-{service_name}
        rule_name = f"fault-injection-{service_name}"
        cmd = f"kubectl delete virtualservice {rule_name} --ignore-not-found"
        output, error = self.ssh_client.run_command(cmd)
        print(f"  - 清理故障输出: {output.strip()}")
        if error:
            print(f"  - 清理故障错误: {error.strip()}")

# Main block removed to convert this file into a library module. 