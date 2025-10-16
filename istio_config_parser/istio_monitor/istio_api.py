import requests
import json
import subprocess
import os
import yaml
import platform
from typing import Dict, List, Any, Optional, Union

# 添加 paramiko 导入
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

class IstioAPI:
    """
    Istio API 客户端，用于连接 Istio 控制平面和数据平面
    支持通过 HTTP API 和 kubectl 命令行工具获取配置
    """
    
    def __init__(self, 
                 host: str = "localhost", 
                 port: int = 8080, 
                 namespace: str = "istio-system",
                 kubeconfig: Optional[str] = None,
                 use_vm: bool = True,
                 vm_host: Optional[str] = None,
                 vm_port: int = 22,
                 vm_user: str = "root",
                 vm_password: Optional[str] = None,
                 vm_key_file: Optional[str] = None):
        """
        初始化 Istio API 客户端
        
        参数:
            host: Istio 控制平面的主机名或 IP
            port: Istio 控制平面的端口
            namespace: Istio 系统的命名空间
            kubeconfig: Kubernetes 配置文件路径
            use_vm: 是否通过虚拟机连接
            vm_host: 虚拟机主机名或 IP
            vm_port: 虚拟机 SSH 端口
            vm_user: 虚拟机用户名
            vm_password: 虚拟机密码
            vm_key_file: 虚拟机 SSH 密钥文件路径
        """
        self.base_url = f"http://{host}:{port}"
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.use_vm = use_vm
        self.vm_host = vm_host
        self.vm_port = vm_port
        self.vm_user = vm_user
        self.vm_password = vm_password
        self.vm_key_file = vm_key_file
        self.is_windows = platform.system() == "Windows"
        
        # 检查是否需要 paramiko
        if self.is_windows and self.use_vm and not HAS_PARAMIKO:
            print("警告: 在 Windows 上使用 SSH 连接需要安装 paramiko 库")
            print("请运行: pip install paramiko")
        
        # 如果使用虚拟机，检查 SSH 连接
        if self.use_vm and self.vm_host:
            try:
                self._execute_vm_command("echo 'SSH connection test'")
                print(f"成功连接到虚拟机 {self.vm_host}")
            except Exception as e:
                print(f"无法连接到虚拟机: {str(e)}")
    
    def _execute_vm_command(self, command: str) -> str:
        """
        在虚拟机上执行命令
        
        参数:
            command: 要执行的命令
            
        返回:
            命令输出
        """
        if not self.use_vm or not self.vm_host:
            raise ValueError("未配置虚拟机连接")
        
        # 在 Windows 上使用 paramiko
        if self.is_windows:
            if not HAS_PARAMIKO:
                raise ImportError("请安装 paramiko 库: pip install paramiko")
            
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                # 连接到服务器
                if self.vm_key_file:
                    key = paramiko.RSAKey.from_private_key_file(self.vm_key_file)
                    client.connect(
                        hostname=self.vm_host,
                        port=self.vm_port,
                        username=self.vm_user,
                        pkey=key
                    )
                else:
                    client.connect(
                        hostname=self.vm_host,
                        port=self.vm_port,
                        username=self.vm_user,
                        password=self.vm_password
                    )
                
                # 执行命令
                stdin, stdout, stderr = client.exec_command(command)
                result = stdout.read().decode('utf-8').strip()
                error = stderr.read().decode('utf-8').strip()
                
                if error:
                    raise Exception(f"命令执行失败: {error}")
                
                return result
            finally:
                client.close()
        else:
            # 在 Linux/Mac 上使用 SSH 命令
            ssh_options = f"-o StrictHostKeyChecking=no -p {self.vm_port}"
            
            if self.vm_key_file:
                ssh_cmd = f"ssh {ssh_options} -i {self.vm_key_file} {self.vm_user}@{self.vm_host} '{command}'"
            elif self.vm_password:
                # 使用 sshpass 传递密码
                ssh_cmd = f"sshpass -p '{self.vm_password}' ssh {ssh_options} {self.vm_user}@{self.vm_host} '{command}'"
            else:
                raise ValueError("未提供虚拟机密码或密钥文件")
            
            # 执行命令
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"命令执行失败: {result.stderr}")
            
            return result.stdout.strip()
    
    def _execute_kubectl(self, command: str) -> str:
        """
        执行 kubectl 命令
        
        参数:
            command: kubectl 命令（不包含 kubectl 前缀）
            
        返回:
            命令输出
        """
        kubectl_cmd = f"kubectl {command}"
        
        if self.kubeconfig:
            kubectl_cmd += f" --kubeconfig={self.kubeconfig}"
        
        if self.use_vm and self.vm_host:
            return self._execute_vm_command(kubectl_cmd)
        else:
            result = subprocess.run(kubectl_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"kubectl 命令执行失败: {result.stderr}")
            
            return result.stdout.strip()
    
    def _make_request(self, endpoint: str, method: str = "GET", data: Any = None) -> Dict:
        """
        向 Istio API 发送请求
        
        参数:
            endpoint: API 端点
            method: HTTP 方法
            data: 请求数据
            
        返回:
            响应数据
        """
        url = f"{self.base_url}/{endpoint}"
        
        try:
            if method == "GET":
                response = requests.get(url)
            elif method == "POST":
                response = requests.post(url, json=data)
            elif method == "PUT":
                response = requests.put(url, json=data)
            elif method == "DELETE":
                response = requests.delete(url)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API 请求失败: {str(e)}")
            return {}
    
    # 控制平面 API
    
    def get_istio_version(self) -> Dict:
        """获取 Istio 版本信息"""
        try:
            if self.use_vm and self.vm_host:
                output = self._execute_vm_command("istioctl version --short")
            else:
                output = subprocess.run("istioctl version --short", shell=True, capture_output=True, text=True).stdout
            
            lines = output.strip().split('\n')
            version_info = {}
            
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    version_info[key.strip()] = value.strip()
            
            return version_info
        except Exception as e:
            print(f"获取 Istio 版本失败: {str(e)}")
            return {}
    
    def get_control_plane_status(self) -> Dict:
        """获取控制平面状态"""
        try:
            pods = self._execute_kubectl(f"get pods -n {self.namespace} -l app=istiod -o json")
            return json.loads(pods)
        except Exception as e:
            print(f"获取控制平面状态失败: {str(e)}")
            return {}
    
    def get_gateways(self) -> Dict:
        """获取所有网关"""
        try:
            gateways = self._execute_kubectl("get gateways --all-namespaces -o json")
            return json.loads(gateways)
        except Exception as e:
            print(f"获取网关失败: {str(e)}")
            return {}
    
    def get_virtual_services(self, namespace: Optional[str] = None) -> Dict:
        """
        获取虚拟服务
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            虚拟服务列表
        """
        try:
            ns_option = f"-n {namespace}" if namespace else "--all-namespaces"
            vs = self._execute_kubectl(f"get virtualservices {ns_option} -o json")
            return json.loads(vs)
        except Exception as e:
            print(f"获取虚拟服务失败: {str(e)}")
            return {}
    
    def get_destination_rules(self, namespace: Optional[str] = None) -> Dict:
        """
        获取目标规则
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            目标规则列表
        """
        try:
            ns_option = f"-n {namespace}" if namespace else "--all-namespaces"
            dr = self._execute_kubectl(f"get destinationrules {ns_option} -o json")
            return json.loads(dr)
        except Exception as e:
            print(f"获取目标规则失败: {str(e)}")
            return {}
    
    def get_envoy_filters(self, namespace: Optional[str] = None) -> Dict:
        """
        获取 Envoy 过滤器
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            Envoy 过滤器列表
        """
        try:
            ns_option = f"-n {namespace}" if namespace else "--all-namespaces"
            ef = self._execute_kubectl(f"get envoyfilters {ns_option} -o json")
            return json.loads(ef)
        except Exception as e:
            print(f"获取 Envoy 过滤器失败: {str(e)}")
            return {}
    
    def get_service_entries(self, namespace: Optional[str] = None) -> Dict:
        """
        获取服务条目
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            服务条目列表
        """
        try:
            ns_option = f"-n {namespace}" if namespace else "--all-namespaces"
            se = self._execute_kubectl(f"get serviceentries {ns_option} -o json")
            return json.loads(se)
        except Exception as e:
            print(f"获取服务条目失败: {str(e)}")
            return {}
    
    def get_authorization_policies(self, namespace: Optional[str] = None) -> Dict:
        """
        获取授权策略
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            授权策略列表
        """
        try:
            ns_option = f"-n {namespace}" if namespace else "--all-namespaces"
            ap = self._execute_kubectl(f"get authorizationpolicies {ns_option} -o json")
            return json.loads(ap)
        except Exception as e:
            print(f"获取授权策略失败: {str(e)}")
            return {}
    
    # 数据平面 API
    
    def get_proxies(self) -> List[str]:
        """获取所有代理（Sidecar）的列表"""
        try:
            if self.use_vm and self.vm_host:
                output = self._execute_vm_command("istioctl proxy-status")
            else:
                output = subprocess.run("istioctl proxy-status", shell=True, capture_output=True, text=True).stdout
            
            lines = output.strip().split('\n')
            if len(lines) <= 1:  # 只有标题行
                return []
            
            proxies = []
            for line in lines[1:]:  # 跳过标题行
                if line.strip():
                    parts = line.split()
                    if parts:
                        proxies.append(parts[0])
            
            return proxies
        except Exception as e:
            print(f"获取代理列表失败: {str(e)}")
            return []
    
    def get_proxy_config(self, proxy_id: str, config_type: str = "clusters") -> Dict:
        """
        获取代理配置
        
        参数:
            proxy_id: 代理 ID
            config_type: 配置类型，可选值：clusters, listeners, routes, endpoints, bootstrap
            
        返回:
            代理配置
        """
        valid_types = ["clusters", "listeners", "routes", "endpoints", "bootstrap"]
        if config_type not in valid_types:
            raise ValueError(f"无效的配置类型: {config_type}，有效类型: {', '.join(valid_types)}")
        
        try:
            if self.use_vm and self.vm_host:
                output = self._execute_vm_command(f"istioctl proxy-config {config_type} {proxy_id} -o json")
            else:
                output = subprocess.run(f"istioctl proxy-config {config_type} {proxy_id} -o json", 
                                       shell=True, capture_output=True, text=True).stdout
            
            return json.loads(output)
        except Exception as e:
            print(f"获取代理配置失败: {str(e)}")
            return {}
    
    def get_proxy_metrics(self, proxy_id: str) -> Dict:
        """
        获取代理指标
        
        参数:
            proxy_id: 代理 ID
            
        返回:
            代理指标
        """
        try:
            pod_name = proxy_id.split('.')[0]
            namespace = proxy_id.split('.')[1] if '.' in proxy_id else 'default'
            
            # 获取 Pod 的 IP
            pod_info = self._execute_kubectl(f"get pod {pod_name} -n {namespace} -o json")
            pod_data = json.loads(pod_info)
            pod_ip = pod_data.get('status', {}).get('podIP')
            
            if not pod_ip:
                raise ValueError(f"无法获取 Pod {pod_name} 的 IP 地址")
            
            # 获取指标
            metrics_url = f"http://{pod_ip}:15090/stats/prometheus"
            
            if self.use_vm and self.vm_host:
                # 在虚拟机上使用 curl 获取指标
                output = self._execute_vm_command(f"curl -s {metrics_url}")
            else:
                response = requests.get(metrics_url)
                output = response.text
            
            # 解析指标
            metrics = {}
            for line in output.split('\n'):
                if line and not line.startswith('#'):
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        metrics[parts[0]] = float(parts[1])
            
            return metrics
        except Exception as e:
            print(f"获取代理指标失败: {str(e)}")
            return {}
    
    # 辅助方法
    
    def get_service_mesh_overview(self) -> Dict:
        """
        获取服务网格概览
        
        返回:
            服务网格概览信息
        """
        try:
            # 获取服务
            services = self._execute_kubectl("get services --all-namespaces -o json")
            services_data = json.loads(services)
            
            # 获取 Pod
            pods = self._execute_kubectl("get pods --all-namespaces -o json")
            pods_data = json.loads(pods)
            
            # 获取 Istio 资源
            vs_data = self.get_virtual_services()
            dr_data = self.get_destination_rules()
            gw_data = self.get_gateways()
            
            # 统计信息
            overview = {
                "services": len(services_data.get("items", [])),
                "pods": len(pods_data.get("items", [])),
                "virtualServices": len(vs_data.get("items", [])),
                "destinationRules": len(dr_data.get("items", [])),
                "gateways": len(gw_data.get("items", [])),
                "namespaces": {}
            }
            
            # 按命名空间统计
            for item in services_data.get("items", []):
                ns = item.get("metadata", {}).get("namespace", "default")
                if ns not in overview["namespaces"]:
                    overview["namespaces"][ns] = {"services": 0, "pods": 0}
                overview["namespaces"][ns]["services"] += 1
            
            for item in pods_data.get("items", []):
                ns = item.get("metadata", {}).get("namespace", "default")
                if ns not in overview["namespaces"]:
                    overview["namespaces"][ns] = {"services": 0, "pods": 0}
                overview["namespaces"][ns]["pods"] += 1
            
            return overview
        except Exception as e:
            print(f"获取服务网格概览失败: {str(e)}")
            return {}
    
    def get_service_dependencies(self, namespace: Optional[str] = None) -> Dict:
        """
        获取服务依赖关系
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            服务依赖关系
        """
        try:
            # 获取虚拟服务
            vs_data = self.get_virtual_services(namespace)
            
            # 获取目标规则
            dr_data = self.get_destination_rules(namespace)
            
            # 构建依赖关系
            dependencies = {}
            
            # 从虚拟服务中提取依赖
            for vs in vs_data.get("items", []):
                vs_name = vs.get("metadata", {}).get("name")
                vs_hosts = vs.get("spec", {}).get("hosts", [])
                
                for http_route in vs.get("spec", {}).get("http", []):
                    for route in http_route.get("route", []):
                        destination = route.get("destination", {})
                        host = destination.get("host")
                        subset = destination.get("subset")
                        
                        if host:
                            if vs_name not in dependencies:
                                dependencies[vs_name] = []
                            
                            dep = {"host": host}
                            if subset:
                                dep["subset"] = subset
                            
                            if dep not in dependencies[vs_name]:
                                dependencies[vs_name].append(dep)
            
            return dependencies
        except Exception as e:
            print(f"获取服务依赖关系失败: {str(e)}")
            return {}
    
    def get_rate_limits(self, namespace: Optional[str] = None) -> Dict:
        """
        获取限流配置
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            限流配置
        """
        try:
            # 获取 EnvoyFilter
            ef_data = self.get_envoy_filters(namespace)
            
            # 提取限流配置
            rate_limits = {}
            
            for ef in ef_data.get("items", []):
                ef_name = ef.get("metadata", {}).get("name")
                ef_ns = ef.get("metadata", {}).get("namespace", "default")
                
                workload_selector = ef.get("spec", {}).get("workloadSelector", {})
                if workload_selector:
                    labels = workload_selector.get("labels", {})
                    app = labels.get("app")
                    
                    if app:
                        if app not in rate_limits:
                            rate_limits[app] = []
                        
                        # 提取限流规则
                        for patch in ef.get("spec", {}).get("configPatches", []):
                            if patch.get("applyTo") == "HTTP_FILTER":
                                patch_value = patch.get("patch", {}).get("value", {})
                                if patch_value.get("name") == "envoy.filters.http.local_ratelimit":
                                    typed_config = patch_value.get("typed_config", {})
                                    token_bucket = typed_config.get("token_bucket", {})
                                    
                                    if token_bucket:
                                        rate_limit = {
                                            "name": ef_name,
                                            "namespace": ef_ns,
                                            "type": "local",
                                            "max_tokens": token_bucket.get("max_tokens"),
                                            "fill_interval": token_bucket.get("fill_interval")
                                        }
                                        
                                        rate_limits[app].append(rate_limit)
                            
                            elif patch.get("applyTo") == "VIRTUAL_HOST":
                                patch_value = patch.get("patch", {}).get("value", {})
                                rate_limits_config = patch_value.get("rate_limits", [])
                                
                                for limit in rate_limits_config:
                                    actions = limit.get("actions", [])
                                    for action in actions:
                                        if "request_headers" in action:
                                            header = action["request_headers"]
                                            
                                            rate_limit = {
                                                "name": ef_name,
                                                "namespace": ef_ns,
                                                "type": "global",
                                                "header_name": header.get("header_name"),
                                                "descriptor_key": header.get("descriptor_key")
                                            }
                                            
                                            rate_limits[app].append(rate_limit)
            
            return rate_limits
        except Exception as e:
            print(f"获取限流配置失败: {str(e)}")
            return {}
    
    def get_fault_injection(self, namespace: Optional[str] = None) -> Dict:
        """
        获取故障注入配置
        
        参数:
            namespace: 命名空间，如果为 None 则获取所有命名空间
            
        返回:
            故障注入配置
        """
        try:
            # 获取虚拟服务
            vs_data = self.get_virtual_services(namespace)
            
            # 提取故障注入配置
            fault_injections = {}
            
            for vs in vs_data.get("items", []):
                vs_name = vs.get("metadata", {}).get("name")
                vs_ns = vs.get("metadata", {}).get("namespace", "default")
                vs_hosts = vs.get("spec", {}).get("hosts", [])
                
                for http_route in vs.get("spec", {}).get("http", []):
                    if "fault" in http_route:
                        fault = http_route["fault"]
                        
                        for host in vs_hosts:
                            if host not in fault_injections:
                                fault_injections[host] = []
                            
                            fault_config = {
                                "virtualService": vs_name,
                                "namespace": vs_ns,
                                "fault": fault
                            }
                            
                            fault_injections[host].append(fault_config)
            
            return fault_injections
        except Exception as e:
            print(f"获取故障注入配置失败: {str(e)}")
            return {}
    
    def export_config(self, output_dir: str = "./istio_config") -> bool:
        """
        导出 Istio 配置
        
        参数:
            output_dir: 输出目录
            
        返回:
            是否成功
        """
        try:
            # 创建输出目录
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # 导出各种配置
            resources = [
                "virtualservices",
                "destinationrules",
                "gateways",
                "envoyfilters",
                "serviceentries",
                "authorizationpolicies"
            ]
            
            for resource in resources:
                output = self._execute_kubectl(f"get {resource} --all-namespaces -o yaml")
                
                with open(f"{output_dir}/{resource}.yaml", "w") as f:
                    f.write(output)
            
            print(f"配置已导出到 {output_dir}")
            return True
        except Exception as e:
            print(f"导出配置失败: {str(e)}")
            return False


# 使用示例
if __name__ == "__main__":
    # 本地连接
    istio = IstioAPI()
    
    # 打印 Istio 版本
    print("Istio 版本:")
    print(istio.get_istio_version())
    
    # 获取控制平面状态
    print("\n控制平面状态:")
    control_plane = istio.get_control_plane_status()
    for pod in control_plane.get("items", []):
        print(f"Pod: {pod['metadata']['name']}, 状态: {pod['status']['phase']}")
    
    # 获取虚拟服务
    print("\n虚拟服务:")
    vs = istio.get_virtual_services()
    for item in vs.get("items", []):
        print(f"名称: {item['metadata']['name']}, 命名空间: {item['metadata']['namespace']}")
    
    # 获取服务网格概览
    print("\n服务网格概览:")
    overview = istio.get_service_mesh_overview()
    print(f"服务: {overview.get('services')}")
    print(f"Pod: {overview.get('pods')}")
    print(f"虚拟服务: {overview.get('virtualServices')}")
    print(f"目标规则: {overview.get('destinationRules')}")
    print(f"网关: {overview.get('gateways')}")
    
    # 获取限流配置
    print("\n限流配置:")
    rate_limits = istio.get_rate_limits()
    for app, limits in rate_limits.items():
        print(f"应用: {app}")
        for limit in limits:
            print(f"  类型: {limit.get('type')}, 最大令牌: {limit.get('max_tokens')}") 