import time
import os
import yaml
import shutil
import sys
from pathlib import Path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.env_detector import K8sEnvDetector

class FaultInjector:
    _DEFAULT_NONEXISTENT_HOST = "nonexistent-service.default.svc.cluster.local"
    """
    支持自动生成/patch 任意 VirtualService 实现故障注入。
    扩展支持新的正交原则故障注入类型：
    - 配置故障注入 (abort/delay with percentage)
    - 高负载+错误场景 (用于熔断测试)
    - 故障+超时组合测试
    - 多种触发机制正交组合
    
    自动检测环境：如果在 K8s 环境中直接执行，否则使用 SSH。
    """
    def __init__(self, ssh_client=None, vs_name='reviews', route_host='reviews', namespace='default'):
        self.ssh_client = ssh_client
        self._vs_name = vs_name
        self._route_host = route_host
        self._namespace = namespace
        self._use_ssh = K8sEnvDetector.should_use_ssh(ssh_client)
        self._backup_path = f'/tmp/{vs_name}_vs_backup.yaml'
        self._patched_path = f'/tmp/{vs_name}_vs_patched.yaml'
        self._new_path = f'/tmp/{vs_name}_vs_new.yaml'
        self._injected = False
        self._created = False
        self._fault_type = None  # 记录当前故障类型
        self._local_dir = Path(__file__).resolve().parent
        self._local_dir.mkdir(parents=True, exist_ok=True)
        print(f"🔧 FaultInjector initialized for VS: {vs_name}, route_host: {route_host} (使用{'SSH' if self._use_ssh else '本地'}执行)")

    def _local_file(self, filename: str) -> str:
        path = self._local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _remote(self, cmd):
        """执行命令，自动检测环境"""
        if self.ssh_client:
            return self.ssh_client.run_command(cmd)
        else:
            import subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.stdout, result.stderr

    def _upload_file(self, local_path, remote_path):
        """上传文件，如果在本地环境则直接复制"""
        if not self._use_ssh or not self.ssh_client or not self.ssh_client.hostname:
            # 本地环境：直接复制文件
            shutil.copy2(local_path, remote_path)
            return
        
        # SSH 环境：使用 SSHClient 的 run_command（复用连接）
        # 读取本地文件内容
        with open(local_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
        
        # 通过 SSH 创建远程文件
        create_cmd = f"cat > {remote_path} << 'EOF'\n{file_content}\nEOF"
        output, error = self.ssh_client.run_command(create_cmd)
        if error:
            raise RuntimeError(f"上传文件失败: {error}")

    def _download_vs_to_local(self, remote_path, local_path):
        """下载文件，如果在本地环境则直接复制"""
        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        
        if not self._use_ssh or not self.ssh_client or not self.ssh_client.hostname:
            # 本地环境：直接复制文件
            if os.path.exists(remote_path):
                shutil.copy2(remote_path, local_path)
            else:
                # 如果远程路径不存在，尝试从 kubectl 获取
                cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
                output, error = self._remote(cmd)
                if not error:
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(output)
            return
        
        # SSH 环境：使用 SSHClient 的 run_command（复用连接）
        cmd = f"cat {remote_path}"
        output, error = self.ssh_client.run_command(cmd)
        if error:
            # 如果文件不存在，尝试从 kubectl 获取
            cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
            output, error = self._remote(cmd)
            if error:
                raise RuntimeError(f"下载文件失败: {error}")
        
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(output)

    def _patch_vs_fault(self, local_backup, local_patched, error_code=503, match_headers=None, match_path=None):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        fault_rule = {
            'fault': {
                'abort': {
                    'httpStatus': error_code,
                    'percentage': {'value': 100}
                }
            },
            'route': [{
                'destination': {'host': self._route_host}
            }]
        }
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        with open(local_patched, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print('[DEBUG] patch 后 VS yaml 预览:')
            print(''.join(lines[:40]))

    def _patch_vs_config_fault(self, local_backup, local_patched, fault_type='abort', 
                              status_code=503, delay='1s', percentage=100, match_headers=None):
        """生成配置故障注入的VirtualService补丁"""
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        
        fault_rule = {
            'route': [{
                'destination': {'host': self._route_host}
            }]
        }
        
        # 根据故障类型构建fault块
        if fault_type == 'abort':
            fault_rule['fault'] = {
                'abort': {
                    'httpStatus': status_code,
                    'percentage': {'value': percentage}
                }
            }
        elif fault_type == 'delay':
            fault_rule['fault'] = {
                'delay': {
                    'fixedDelay': delay,
                    'percentage': {'value': percentage}
                }
            }
        elif fault_type == 'both':
            # 同时注入abort和delay
            fault_rule['fault'] = {
                'abort': {
                    'httpStatus': status_code,
                    'percentage': {'value': percentage // 2}
                },
                'delay': {
                    'fixedDelay': delay,
                    'percentage': {'value': percentage // 2}
                }
            }
        
        # 添加匹配条件
        if match_headers:
            fault_rule['match'] = [{
                'headers': {k: {'exact': v} for k, v in match_headers.items()}
            }]
        
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_high_load_scenario(self, local_backup, local_patched):
        """生成高负载+错误场景的VirtualService补丁（用于熔断测试）"""
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        
        # 创建多个故障规则模拟高负载场景
        fault_rules = [
            # 80% 的请求返回503错误
            {
                'fault': {
                    'abort': {
                        'httpStatus': 503,
                        'percentage': {'value': 80}
                    }
                },
                'route': [{'destination': {'host': self._route_host}}]
            },
            # 15% 的请求有延迟
            {
                'fault': {
                    'delay': {
                        'fixedDelay': '2s',
                        'percentage': {'value': 15}
                    }
                },
                'route': [{'destination': {'host': self._route_host}}]
            },
            # 5% 正常请求
            {
                'route': [{'destination': {'host': self._route_host}}]
            }
        ]
        
        vs['spec']['http'] = fault_rules + vs['spec'].get('http', [])
        
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_fault_with_timeout(self, local_backup, local_patched, 
                                   status_code=503, percentage=100, timeout='2s'):
        """生成故障注入+超时组合的VirtualService补丁"""
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        
        fault_rule = {
            'fault': {
                'abort': {
                    'httpStatus': status_code,
                    'percentage': {'value': percentage}
                }
            },
            'timeout': timeout,  # 添加超时设置
            'route': [{
                'destination': {'host': self._route_host}
            }]
        }
        
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_upstream_error_scenario(self, local_backup, local_patched, error_percentage=80):
        """生成上游错误场景的VirtualService补丁（路由到不存在的服务）"""
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        
        # 创建上游错误规则：使用权重路由到不存在的服务
        error_percentage = max(0, min(100, int(error_percentage)))
        healthy_percentage = 100 - error_percentage if error_percentage < 100 else 0

        route_destinations = [
            {
                'destination': {'host': self._DEFAULT_NONEXISTENT_HOST},
                'weight': error_percentage
            }
        ]

        if healthy_percentage > 0:
            route_destinations.append({
                'destination': {'host': self._route_host},
                'weight': healthy_percentage
            })

        upstream_error_rules = [
            {
                'route': route_destinations
            }
        ]
        
        # 更新VS规则
        vs['spec']['http'] = upstream_error_rules + vs['spec'].get('http', [])
        
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _generate_new_vs(self, local_path, error_code=503, match_headers=None, match_path=None):
        fault_rule = {
            'fault': {
                'abort': {
                    'httpStatus': error_code,
                    'percentage': {'value': 100}
                }
            },
            'route': [{
                'destination': {'host': self._route_host}
            }]
        }
        vs = {
            'apiVersion': 'networking.istio.io/v1beta1',
            'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {
                'hosts': [self._route_host],
                'http': [fault_rule]
            }
        }
        with open(local_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def inject_http_fault(self, error_code=503, match_headers=None, match_path=None):
        """传统HTTP故障注入（兼容性方法）"""
        print(f"🔥 [INJECTING FAULT] patch VS '{self._vs_name}' 注入 HTTP {error_code} 故障...")
        self._fault_type = "http_fault"
        check_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace}"
        output, error = self._remote(check_cmd)
        if 'NotFound' in output or 'NotFound' in error:
            print(f"  - 未检测到 {self._vs_name} VS，自动生成新 VS")
            local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
            self._generate_new_vs(local_new, error_code, match_headers, match_path)
            self._upload_file(local_new, self._new_path)
            apply_cmd = f"kubectl apply -f {self._new_path}"
            out, err = self._remote(apply_cmd)
            print(f"  - 新建VS输出: {out.strip()}")
            if err:
                print(f"  - 新建VS错误: {err.strip()}")
            self._created = True
        else:
            print(f"  - 检测到 {self._vs_name} VS，先备份并patch注入故障")
            self._backup_and_patch_vs(self._patch_vs_fault, error_code, match_headers, match_path)

    def inject_config_fault(self, fault_type='abort', status_code=503, delay='1s', 
                          percentage=100, match_headers=None):
        """配置故障注入（支持abort、delay、both）"""
        print(f"🔥 [CONFIG FAULT] 注入配置故障 {fault_type} (百分比: {percentage}%)")
        self._fault_type = f"config_fault_{fault_type}"
        
        check_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace}"
        output, error = self._remote(check_cmd)
        
        if 'NotFound' in output or 'NotFound' in error:
            print(f"  - 未检测到 {self._vs_name} VS，自动生成新 VS")
            # 为配置故障创建新的VS
            self._create_new_config_fault_vs(fault_type, status_code, delay, percentage, match_headers)
        else:
            print(f"  - 检测到 {self._vs_name} VS，先备份并patch注入配置故障")
            self._backup_and_patch_vs(
                self._patch_vs_config_fault, fault_type, status_code, delay, percentage, match_headers
            )

    def inject_high_load_scenario(self):
        """注入高负载+错误场景（用于熔断测试）"""
        print(f"🔥 [HIGH LOAD] 注入高负载+错误场景用于熔断测试")
        self._fault_type = "high_load_scenario"
        
        check_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace}"
        output, error = self._remote(check_cmd)
        
        if 'NotFound' in output or 'NotFound' in error:
            print(f"  - 未检测到 {self._vs_name} VS，创建高负载场景VS")
            self._create_high_load_vs()
        else:
            print(f"  - 检测到 {self._vs_name} VS，patch注入高负载场景")
            self._backup_and_patch_vs(self._patch_vs_high_load_scenario)

    def inject_fault_with_timeout(self, status_code=503, percentage=100, timeout='2s'):
        """注入故障+超时组合"""
        print(f"🔥 [FAULT+TIMEOUT] 注入故障({status_code})和超时({timeout})组合")
        self._fault_type = "fault_with_timeout"
        
        check_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace}"
        output, error = self._remote(check_cmd)
        
        if 'NotFound' in output or 'NotFound' in error:
            print(f"  - 未检测到 {self._vs_name} VS，创建故障+超时VS")
            self._create_fault_timeout_vs(status_code, percentage, timeout)
        else:
            print(f"  - 检测到 {self._vs_name} VS，patch注入故障+超时")
            self._backup_and_patch_vs(self._patch_vs_fault_with_timeout, status_code, percentage, timeout)

    def inject_upstream_error_scenario(self, error_percentage=80):
        """注入上游错误场景（路由到不存在的服务，产生可记录的503）"""
        print(f"🔥 [UPSTREAM_ERROR] 注入上游错误场景，错误率{error_percentage}%")
        self._fault_type = "upstream_error_scenario"
        
        check_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace}"
        output, error = self._remote(check_cmd)
        
        if 'NotFound' in output or 'NotFound' in error:
            print(f"  - 未检测到 {self._vs_name} VS，创建上游错误VS")
            self._create_upstream_error_vs(error_percentage)
        else:
            print(f"  - 检测到 {self._vs_name} VS，patch注入上游错误")
            self._backup_and_patch_vs(self._patch_vs_upstream_error_scenario, error_percentage)

    def _backup_and_patch_vs(self, patch_method, *args, **kwargs):
        """通用的备份和patch方法"""
        remote_backup = self._backup_path
        local_backup = self._local_file(f'{self._vs_name}_vs_backup.yaml')
        local_patched = self._local_file(f'{self._vs_name}_vs_patched.yaml')
        
        # 备份当前VS
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            # SSH 环境：先保存到远程，再下载
            dump_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml > {remote_backup}"
            self._remote(dump_cmd)
            self._download_vs_to_local(remote_backup, local_backup)
        else:
            # 本地环境：直接获取并保存
            dump_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
            output, error = self._remote(dump_cmd)
            if error:
                raise RuntimeError(f"获取 VirtualService 失败: {error}")
            with open(local_backup, 'w', encoding='utf-8') as f:
                f.write(output)
        
        # 应用patch
        patch_method(local_backup, local_patched, *args, **kwargs)
        
        # 上传并应用
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            # SSH 环境：上传到远程再应用
            self._upload_file(local_patched, self._patched_path)
            apply_cmd = f"kubectl apply -n {self._namespace} -f {self._patched_path}"
        else:
            # 本地环境：直接应用本地文件
            apply_cmd = f"kubectl apply -n {self._namespace} -f \"{local_patched}\""
        
        out, err = self._remote(apply_cmd)
        print(f"  - patch VS输出: {out.strip()}")
        if err:
            print(f"  - patch VS错误: {err.strip()}")
        self._injected = True

    def _create_new_config_fault_vs(self, fault_type, status_code, delay, percentage, match_headers):
        """创建新的配置故障VS"""
        fault_rule = {'route': [{'destination': {'host': self._route_host}}]}
        
        if fault_type == 'abort':
            fault_rule['fault'] = {
                'abort': {
                    'httpStatus': status_code,
                    'percentage': {'value': percentage}
                }
            }
        elif fault_type == 'delay':
            fault_rule['fault'] = {
                'delay': {
                    'fixedDelay': delay,
                    'percentage': {'value': percentage}
                }
            }
        
        vs = {
            'apiVersion': 'networking.istio.io/v1beta1',
            'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {
                'hosts': [self._route_host],
                'http': [fault_rule]
            }
        }
        
        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            # SSH 环境：上传到远程再应用
            self._upload_file(local_new, self._new_path)
            apply_cmd = f"kubectl apply -n {self._namespace} -f {self._new_path}"
        else:
            # 本地环境：直接应用本地文件
            apply_cmd = f"kubectl apply -n {self._namespace} -f \"{local_new}\""
        
        out, err = self._remote(apply_cmd)
        print(f"  - 新建配置故障VS输出: {out.strip()}")
        if err:
            print(f"  - 新建配置故障VS错误: {err.strip()}")
        self._created = True

    def _create_high_load_vs(self):
        """创建高负载场景VS"""
        fault_rules = [
            {
                'fault': {
                    'abort': {
                        'httpStatus': 503,
                        'percentage': {'value': 80}
                    }
                },
                'route': [{'destination': {'host': self._route_host}}]
            },
            {
                'fault': {
                    'delay': {
                        'fixedDelay': '2s',
                        'percentage': {'value': 15}
                    }
                },
                'route': [{'destination': {'host': self._route_host}}]
            },
            {
                'route': [{'destination': {'host': self._route_host}}]
            }
        ]
        
        vs = {
            'apiVersion': 'networking.istio.io/v1beta1',
            'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {
                'hosts': [self._route_host],
                'http': fault_rules
            }
        }
        
        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            # SSH 环境：上传到远程再应用
            self._upload_file(local_new, self._new_path)
            apply_cmd = f"kubectl apply -n {self._namespace} -f {self._new_path}"
        else:
            # 本地环境：直接应用本地文件
            apply_cmd = f"kubectl apply -n {self._namespace} -f \"{local_new}\""
        
        out, err = self._remote(apply_cmd)
        print(f"  - 新建高负载VS输出: {out.strip()}")
        if err:
            print(f"  - 新建高负载VS错误: {err.strip()}")
        self._created = True

    def _create_fault_timeout_vs(self, status_code, percentage, timeout):
        """创建故障+超时VS"""
        fault_rule = {
            'fault': {
                'abort': {
                    'httpStatus': status_code,
                    'percentage': {'value': percentage}
                }
            },
            'timeout': timeout,
            'route': [{'destination': {'host': self._route_host}}]
        }
        
        vs = {
            'apiVersion': 'networking.istio.io/v1beta1',
            'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {
                'hosts': [self._route_host],
                'http': [fault_rule]
            }
        }
        
        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            # SSH 环境：上传到远程再应用
            self._upload_file(local_new, self._new_path)
            apply_cmd = f"kubectl apply -n {self._namespace} -f {self._new_path}"
        else:
            # 本地环境：直接应用本地文件
            apply_cmd = f"kubectl apply -n {self._namespace} -f \"{local_new}\""
        
        out, err = self._remote(apply_cmd)
        print(f"  - 新建故障+超时VS输出: {out.strip()}")
        if err:
            print(f"  - 新建故障+超时VS错误: {err.strip()}")
        self._created = True

    def clear_faults(self):
        print(f"🧹 [CLEARING FAULT] 清除 VS '{self._vs_name}' 的所有故障 (类型: {self._fault_type})")
        if self._created:
            del_cmd = f"kubectl delete virtualservice {self._vs_name} -n {self._namespace} --ignore-not-found"
            out, err = self._remote(del_cmd)
            print(f"  - 删除VS输出: {out.strip()}")
            if err:
                print(f"  - 删除VS错误: {err.strip()}")
            self._created = False
        elif self._injected:
            print(f"  - 恢复原始 {self._vs_name} VS 配置")
            self._upload_file(self._local_file(f'{self._vs_name}_vs_backup.yaml'), self._backup_path)
            replace_cmd = f"kubectl replace --force -n {self._namespace} -f {self._backup_path}"
            out, err = self._remote(replace_cmd)
            print(f"  - 恢复VS输出: {out.strip()}")
            if err:
                print(f"  - 恢复VS错误: {err.strip()}")
            self._injected = False
        
        self._fault_type = None

    def _create_upstream_error_vs(self, error_percentage=80):
        """创建上游错误场景VS（当目标 VS 不存在时使用）"""
        error_percentage = max(0, min(100, int(error_percentage)))
        healthy_percentage = 100 - error_percentage if error_percentage < 100 else 0

        route_destinations = [
            {
                'destination': {'host': self._DEFAULT_NONEXISTENT_HOST},
                'weight': error_percentage
            }
        ]

        if healthy_percentage > 0:
            route_destinations.append({
                'destination': {'host': self._route_host},
                'weight': healthy_percentage
            })

        vs = {
            'apiVersion': 'networking.istio.io/v1beta1',
            'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {
                'hosts': [self._route_host],
                'http': [
                    {
                        'route': route_destinations
                    }
                ]
            }
        }

        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            self._upload_file(local_new, self._new_path)
            apply_cmd = f"kubectl apply -n {self._namespace} -f {self._new_path}"
        else:
            apply_cmd = f"kubectl apply -n {self._namespace} -f \"{local_new}\""

        out, err = self._remote(apply_cmd)
        print(f"  - 新建上游错误VS输出: {out.strip()}")
        if err:
            print(f"  - 新建上游错误VS错误: {err.strip()}")
        self._created = True

# Main block removed to convert this file into a library module. 

