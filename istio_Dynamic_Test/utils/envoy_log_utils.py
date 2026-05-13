import subprocess
import yaml
import tempfile
import os
from typing import Optional
import time
import json
from .env_detector import K8sEnvDetector

class EnvoyLogEnabler:
    @staticmethod
    def check_access_log_enabled(deployment: str, ssh_client=None, namespace: str = 'default') -> bool:
        """
        检查deployment是否已经启用了access log配置
        如果已经配置，返回True，避免重复patch和restart
        """
        cmd = f"kubectl get deployment {deployment} -n {namespace} -o jsonpath='{{.spec.template.metadata.annotations}}'"
        
        if ssh_client and K8sEnvDetector.should_use_ssh(ssh_client):
            output, error = ssh_client.run_command(cmd)
        else:
            result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            output, error = result.stdout, result.stderr
        
        if output and "proxy.istio.io/config" in output:
            # 检查是否包含access log配置
            if "accessLogFile" in output or "accessLogFormat" in output:
                return True
        return False
    
    @staticmethod
    def check_pods_ready(deployment: str, ssh_client=None, namespace: str = 'default', timeout: int = 30) -> bool:
        """
        快速检查deployment的pods是否ready，而不是等待完整的rollout
        如果pod已经ready，可以提前返回
        """
        use_ssh = ssh_client and K8sEnvDetector.should_use_ssh(ssh_client)
        
        # 获取deployment的replicas数量
        replicas_cmd = f"kubectl get deployment {deployment} -n {namespace} -o jsonpath='{{.spec.replicas}}'"
        if use_ssh:
            replicas_output, _ = ssh_client.run_command(replicas_cmd)
        else:
            result = subprocess.run(replicas_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            replicas_output = result.stdout
        
        try:
            expected_replicas = int(replicas_output.strip() or "1")
        except:
            expected_replicas = 1
        
        # 检查ready pods数量
        for i in range(timeout // 2):  # 每2秒检查一次
            ready_cmd = f"kubectl get deployment {deployment} -n {namespace} -o jsonpath='{{.status.readyReplicas}}'"
            if use_ssh:
                ready_output, _ = ssh_client.run_command(ready_cmd)
            else:
                result = subprocess.run(ready_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                ready_output = result.stdout
            
            try:
                ready_replicas = int(ready_output.strip() or "0")
                if ready_replicas >= expected_replicas:
                    return True
            except:
                pass
            time.sleep(2)
        return False
    
    @staticmethod
    def enable_envoy_access_log(deployment: str, ssh_client=None, namespace: str = 'default', log_path: str = '/dev/stdout', wait_ready: bool = True, skip_if_enabled: bool = True):
        """
        Patch deployment 的 pod template annotations，启用 Envoy 访问日志（适用于新建 pod），并自定义 access log 格式。
        patch 后自动 rollout restart deployment，等待新 pod ready。
        
        :param deployment: deployment 名称
        :param ssh_client: SSHClient 实例，如果为 None 则本地执行
        :param namespace: K8s 命名空间
        :param log_path: 日志输出路径
        :param wait_ready: 是否等待 pod ready
        :param skip_if_enabled: 如果已经启用，跳过patch和restart
        """
        # 检查是否已经配置了access log
        if skip_if_enabled and EnvoyLogEnabler.check_access_log_enabled(deployment, ssh_client, namespace):
            print(f"ℹ️  deployment/{deployment} 已经配置了 access log，跳过重复配置")
            return
        
        # 使用增强的访问日志格式，确保记录所有错误（包括故障注入的503）
        access_log_format = (
            '[%START_TIME%] "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %PROTOCOL%" '
            '%RESPONSE_CODE% %RESPONSE_FLAGS% %BYTES_RECEIVED% %BYTES_SENT% %DURATION% '
            '%RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)% "%REQ(X-FORWARDED-FOR)%" "%REQ(USER-AGENT)%" '
            '"%REQ(X-REQUEST-ID)%" "%REQ(:AUTHORITY)%" "%UPSTREAM_HOST%" "%UPSTREAM_CLUSTER%" '
            '%DOWNSTREAM_REMOTE_ADDRESS% %ROUTE_NAME%\n'
        )
        
        # 使用正确的 proxy.istio.io/config 格式，确保记录所有响应
        proxy_config = {
            "proxyStatsMatcher": {
                "inclusionRegexps": [".*"]
            },
            "accessLogFile": log_path,
            "accessLogFormat": access_log_format,
            "accessLogEncoding": "TEXT",
            # 关键：添加proxyMetadata确保访问日志在Pod级别生效
            "proxyMetadata": {
                "PILOT_ENABLE_WORKLOAD_ENTRY_AUTOREGISTRATION": "true",
                "BOOTSTRAP_XDS_AGENT": "true"
            },
            # 确保记录所有状态码，包括故障注入产生的错误
            "accessLogFilter": {
                "expression": "true"  # 记录所有请求，不过滤
            }
        }
        
        # 同时添加 sidecar.istio.io/inject 确保注入
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "sidecar.istio.io/inject": "true",
                            "sidecar.istio.io/logLevel": "info", 
                            "proxy.istio.io/config": json.dumps(proxy_config, separators=(',', ':'))
                        }
                    }
                }
            }
        }
        
        use_ssh = ssh_client and K8sEnvDetector.should_use_ssh(ssh_client)
        
        if use_ssh:
            # 通过 SSH 执行，使用临时文件
            patch_json = json.dumps(patch, indent=2)
            
            # 首先创建临时 patch 文件
            create_patch_cmd = f"cat > /tmp/envoy_patch_{deployment}.json << 'EOF'\n{patch_json}\nEOF"
            print(f"正在通过 SSH 为 deployment/{deployment} 创建 patch 文件...")
            output, error = ssh_client.run_command(create_patch_cmd)
            if error:
                raise RuntimeError(f"创建 patch 文件失败: {error}")
            
            # 使用 patch file 执行 patch
            patch_cmd = f"kubectl patch deployment {deployment} -n {namespace} --patch-file /tmp/envoy_patch_{deployment}.json"
            print(f"正在通过 SSH 为 deployment/{deployment} 注入 Envoy 访问日志配置...")
            output, error = ssh_client.run_command(patch_cmd)
            if error:
                raise RuntimeError(f"Patch deployment 失败: {error}")
            print(f"已为 deployment/{deployment} 注入自定义 Envoy 访问日志格式注解")
            
            # 验证 patch 是否成功
            verify_cmd = f"kubectl get deployment {deployment} -n {namespace} -o jsonpath='{{.spec.template.metadata.annotations}}'"
            output, error = ssh_client.run_command(verify_cmd)
            if output and "proxy.istio.io/config" in output:
                print(f"✅ 验证成功: proxy.istio.io/config 注解已添加")
            else:
                print(f"⚠️  警告: 无法验证注解是否添加成功")
            
            # 清理临时文件
            cleanup_cmd = f"rm -f /tmp/envoy_patch_{deployment}.json"
            ssh_client.run_command(cleanup_cmd)
            
            # rollout restart deployment
            restart_cmd = f"kubectl rollout restart deployment/{deployment} -n {namespace}"
            print(f"正在重启 deployment/{deployment}...")
            output, error = ssh_client.run_command(restart_cmd)
            if error:
                raise RuntimeError(f"重启 deployment 失败: {error}")
            print(f"已重启 deployment/{deployment}，等待新 pod 带上日志配置")
            
            # 等待 rollout 完成（优化：使用快速检查）
            if wait_ready:
                print("等待 rollout 完成...")
                # 先尝试快速检查pod是否ready（最多30秒）
                if EnvoyLogEnabler.check_pods_ready(deployment, ssh_client, namespace, timeout=30):
                    print("✅ Pods 已就绪（快速检查）")
                    # 减少等待时间，因为pod已经ready
                    print("等待 3 秒让新配置生效...")
                    time.sleep(3)
                else:
                    # 如果快速检查失败，使用完整的rollout status（最多60秒）
                    wait_cmd = f"kubectl rollout status deployment/{deployment} -n {namespace} --timeout=60s"
                    output, error = ssh_client.run_command(wait_cmd)
                    if error:
                        print(f"⚠️  等待 rollout 完成超时: {error}")
                    else:
                        print("✅ Rollout 完成")
                    
                    # 减少等待时间（从10秒减少到5秒）
                    print("等待 5 秒让新配置生效...")
                    time.sleep(5)
        else:
            # 本地执行（保持原有逻辑）
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.yaml') as f:
                yaml.safe_dump(patch, f)
                patch_file = f.name
            try:
                subprocess.run([
                    "kubectl", "patch", "deployment", deployment, "-n", namespace, "--patch-file", patch_file
                ], check=True)
                print(f"已为 deployment/{deployment} 注入自定义 Envoy 访问日志格式注解")
                # rollout restart deployment
                subprocess.run([
                    "kubectl", "rollout", "restart", f"deployment/{deployment}", "-n", namespace
                ], check=True)
                print(f"已重启 deployment/{deployment}，等待新 pod 带上日志配置")
                if wait_ready:
                    subprocess.run([
                        "kubectl", "rollout", "status", f"deployment/{deployment}", "-n", namespace, "--timeout=60s"
                    ], check=True)
                    time.sleep(5)  # 减少等待时间
            finally:
                os.remove(patch_file)

    @staticmethod
    def verify_access_log_config(deployment: str, ssh_client=None, namespace: str = 'default'):
        """
        验证 deployment 的 access log 配置是否正确
        """
        use_ssh = ssh_client and K8sEnvDetector.should_use_ssh(ssh_client)
        
        # 检查 deployment annotations
        cmd = f"kubectl get deployment {deployment} -n {namespace} -o jsonpath='{{.spec.template.metadata.annotations}}'"
        if use_ssh:
            output, error = ssh_client.run_command(cmd)
        else:
            result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            output, error = result.stdout, result.stderr
        
        if error:
            print(f"❌ 无法获取 deployment annotations: {error}")
            return False
        
        print(f"📋 Deployment {deployment} annotations:")
        print(output)
        
        if "proxy.istio.io/config" not in output:
            print("❌ 缺少 proxy.istio.io/config 注解")
            return False
        
        # 检查 pod 是否有正确的注解
        pod_cmd = f"kubectl get pods -n {namespace} -l app={deployment.split('-')[0]} -o jsonpath='{{.items[0].metadata.annotations}}'"
        if use_ssh:
            pod_output, pod_error = ssh_client.run_command(pod_cmd)
        else:
            result = subprocess.run(pod_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            pod_output, pod_error = result.stdout, result.stderr
        
        if not pod_error:
            print(f"📋 Pod annotations:")
            print(pod_output)
        
        return True

    @staticmethod
    def get_envoy_logs(pod_name: str, namespace: str = 'default', tail_lines: int = 200) -> str:
        """
        获取 istio-proxy 容器的 Envoy 访问日志。
        """
        cmd = [
            "kubectl", "logs", pod_name, "-n", namespace, "-c", "istio-proxy", "--tail", str(tail_lines)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode == 0:
            return result.stdout
        else:
            raise RuntimeError(f"获取 Envoy 日志失败: {result.stderr}")
