#!/usr/bin/env python3

import json
import tempfile
import os

class IstioGlobalAccessLog:
    """
    使用 Istio 全局配置启用 access log
    这是一个替代方案，当 deployment 级别的注解不生效时可以使用
    """
    
    @staticmethod
    def enable_global_access_log(ssh_client, namespace='istio-system'):
        """
        通过修改 Istio ConfigMap 启用全局 access log
        """
        
        # 检查是否存在 istio ConfigMap
        check_cmd = f"kubectl get configmap istio -n {namespace}"
        output, error = ssh_client.run_command(check_cmd)
        
        if error and "NotFound" in error:
            print("🔧 Istio ConfigMap 不存在，创建新的配置...")
            return IstioGlobalAccessLog._create_istio_configmap(ssh_client, namespace)
        else:
            print("📋 Istio ConfigMap 已存在，更新配置...")
            return IstioGlobalAccessLog._update_istio_configmap(ssh_client, namespace)
    
    @staticmethod
    def _create_istio_configmap(ssh_client, namespace):
        """创建新的 Istio ConfigMap 启用 access log"""
        
        # 简单的 access log 格式
        access_log_format = (
            '[%START_TIME%] "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %PROTOCOL%" '
            '%RESPONSE_CODE% %RESPONSE_FLAGS% %BYTES_RECEIVED% %BYTES_SENT% %DURATION% '
            '%RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)% "%REQ(X-FORWARDED-FOR)%" "%REQ(USER-AGENT)%" '
            '"%REQ(X-REQUEST-ID)%" "%REQ(:AUTHORITY)%" "%UPSTREAM_HOST%" "%UPSTREAM_CLUSTER%"'
        )
        
        istio_config = {
            "mesh": {
                "accessLogFile": "/dev/stdout",
                "accessLogFormat": access_log_format,
                "defaultConfig": {
                    "proxyStatsMatcher": {
                        "inclusionRegexps": [".*requests.*", ".*connections.*", ".*upstream.*"],
                        "exclusionRegexps": [".*_bucket"]
                    }
                }
            }
        }
        
        configmap_yaml = f"""
apiVersion: v1
kind: ConfigMap
metadata:
  name: istio
  namespace: {namespace}
  labels:
    istio.io/rev: default
data:
  mesh: |
{json.dumps(istio_config['mesh'], indent=4)}
"""
        
        # 创建 ConfigMap
        create_cmd = f"cat > /tmp/istio-configmap.yaml << 'EOF'\n{configmap_yaml}\nEOF"
        output, error = ssh_client.run_command(create_cmd)
        if error:
            raise RuntimeError(f"创建 ConfigMap 文件失败: {error}")
        
        apply_cmd = f"kubectl apply -f /tmp/istio-configmap.yaml"
        output, error = ssh_client.run_command(apply_cmd)
        if error:
            raise RuntimeError(f"应用 ConfigMap 失败: {error}")
        
        # 清理临时文件
        ssh_client.run_command("rm -f /tmp/istio-configmap.yaml")
        
        print("✅ 已创建 Istio ConfigMap 并启用全局 access log")
        return True
    
    @staticmethod
    def _update_istio_configmap(ssh_client, namespace):
        """更新现有的 Istio ConfigMap"""
        
        # 获取当前 ConfigMap
        get_cmd = f"kubectl get configmap istio -n {namespace} -o yaml"
        output, error = ssh_client.run_command(get_cmd)
        if error:
            raise RuntimeError(f"获取 ConfigMap 失败: {error}")
        
        print("📋 当前 Istio ConfigMap:")
        print(output[:500] + "...")
        
        # 简单的方法：使用 kubectl patch 添加 access log 配置
        access_log_config = {
            "data": {
                "mesh": json.dumps({
                    "accessLogFile": "/dev/stdout",
                    "accessLogFormat": (
                        '[%START_TIME%] "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %PROTOCOL%" '
                        '%RESPONSE_CODE% %RESPONSE_FLAGS% %BYTES_RECEIVED% %BYTES_SENT% %DURATION% '
                        '%RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)% "%REQ(X-FORWARDED-FOR)%" "%REQ(USER-AGENT)%" '
                        '"%REQ(X-REQUEST-ID)%" "%REQ(:AUTHORITY)%" "%UPSTREAM_HOST%" "%UPSTREAM_CLUSTER%"'
                    ),
                    "defaultConfig": {
                        "proxyStatsMatcher": {
                            "inclusionRegexps": [".*"]
                        }
                    }
                }, indent=2)
            }
        }
        
        # 使用临时文件进行 patch
        patch_json = json.dumps(access_log_config, indent=2)
        create_patch_cmd = f"cat > /tmp/istio-patch.json << 'EOF'\n{patch_json}\nEOF"
        output, error = ssh_client.run_command(create_patch_cmd)
        if error:
            raise RuntimeError(f"创建 patch 文件失败: {error}")
        
        patch_cmd = f"kubectl patch configmap istio -n {namespace} --patch-file /tmp/istio-patch.json"
        output, error = ssh_client.run_command(patch_cmd)
        if error:
            raise RuntimeError(f"Patch ConfigMap 失败: {error}")
        
        # 清理临时文件
        ssh_client.run_command("rm -f /tmp/istio-patch.json")
        
        print("✅ 已更新 Istio ConfigMap 启用全局 access log")
        return True
    
    @staticmethod
    def restart_istio_proxies(ssh_client, namespace='default'):
        """
        重启所有 pod 以应用新的 Istio 配置
        """
        print("🔄 重启 Istio proxy 以应用新配置...")
        
        # 获取所有有 istio-proxy 的 deployment
        get_deployments_cmd = f"kubectl get deployments -n {namespace} -o jsonpath='{{.items[*].metadata.name}}'"
        output, error = ssh_client.run_command(get_deployments_cmd)
        if error:
            print(f"⚠️ 获取 deployment 列表失败: {error}")
            return False
        
        deployments = output.strip().split()
        print(f"📋 找到 {len(deployments)} 个 deployment")
        
        # 重启所有 deployment
        for deployment in deployments:
            if deployment:  # 确保不是空字符串
                restart_cmd = f"kubectl rollout restart deployment/{deployment} -n {namespace}"
                print(f"  重启 deployment/{deployment}")
                output, error = ssh_client.run_command(restart_cmd)
                if error:
                    print(f"    ⚠️ 重启失败: {error}")
                else:
                    print(f"    ✅ 重启成功")
        
        print("⏳ 等待所有 deployment 重启完成...")
        
        # 等待 rollout 完成
        for deployment in deployments:
            if deployment:
                wait_cmd = f"kubectl rollout status deployment/{deployment} -n {namespace} --timeout=60s"
                output, error = ssh_client.run_command(wait_cmd)
                if error:
                    print(f"  ⚠️ {deployment} 重启超时")
                else:
                    print(f"  ✅ {deployment} 重启完成")
        
        return True
    
    @staticmethod
    def verify_global_config(ssh_client, namespace='istio-system'):
        """验证全局配置是否正确"""
        
        print("🔍 验证 Istio 全局配置...")
        
        # 检查 ConfigMap
        get_cmd = f"kubectl get configmap istio -n {namespace} -o jsonpath='{{.data.mesh}}'"
        output, error = ssh_client.run_command(get_cmd)
        if error:
            print(f"❌ 无法获取 Istio ConfigMap: {error}")
            return False
        
        print("📋 当前 mesh 配置:")
        print(output)
        
        if "accessLogFile" in output:
            print("✅ 发现 accessLogFile 配置")
        else:
            print("❌ 未找到 accessLogFile 配置")
            return False
        
        if "accessLogFormat" in output:
            print("✅ 发现 accessLogFormat 配置")
        else:
            print("❌ 未找到 accessLogFormat 配置")
            return False
        
        return True 