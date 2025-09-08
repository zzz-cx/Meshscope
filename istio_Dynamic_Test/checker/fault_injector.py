import time
import os
import paramiko
import yaml

class FaultInjector:
    """
    支持自动生成/patch 任意 VirtualService 实现故障注入。
    扩展支持新的正交原则故障注入类型：
    - 配置故障注入 (abort/delay with percentage)
    - 高负载+错误场景 (用于熔断测试)
    - 故障+超时组合测试
    - 多种触发机制正交组合
    """
    def __init__(self, ssh_client, vs_name='reviews', route_host='reviews', namespace='default'):
        self.ssh_client = ssh_client
        self._vs_name = vs_name
        self._route_host = route_host
        self._namespace = namespace
        self._backup_path = f'/tmp/{vs_name}_vs_backup.yaml'
        self._patched_path = f'/tmp/{vs_name}_vs_patched.yaml'
        self._new_path = f'/tmp/{vs_name}_vs_new.yaml'
        self._injected = False
        self._created = False
        self._fault_type = None  # 记录当前故障类型
        print(f"🔧 FaultInjector initialized for VS: {vs_name}, route_host: {route_host}")

    def _remote(self, cmd):
        return self.ssh_client.run_command(cmd)

    def _upload_file(self, local_path, remote_path):
        transport = paramiko.Transport((self.ssh_client.hostname, self.ssh_client.port))
        if self.ssh_client.password:
            transport.connect(username=self.ssh_client.username, password=self.ssh_client.password)
        else:
            transport.connect(username=self.ssh_client.username, pkey=None)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(local_path, remote_path)
        sftp.close()
        transport.close()

    def _download_vs_to_local(self, remote_path, local_path):
        # 确保本地目录存在
        import os
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        
        transport = paramiko.Transport((self.ssh_client.hostname, self.ssh_client.port))
        if self.ssh_client.password:
            transport.connect(username=self.ssh_client.username, password=self.ssh_client.password)
        else:
            transport.connect(username=self.ssh_client.username, pkey=None)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get(remote_path, local_path)
        sftp.close()
        transport.close()

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
        upstream_error_rules = [
            # 80% 的请求路由到不存在的服务（产生cluster not found 503）
            {
                'route': [
                    {
                        'destination': {'host': 'nonexistent-service.default.svc.cluster.local'},
                        'weight': 80
                    },
                    {
                        'destination': {'host': self._route_host},
                        'weight': 20
                    }
                ]
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
            local_new = f'checker/{self._vs_name}_vs_new.yaml'
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
        local_backup = f'checker/{self._vs_name}_vs_backup.yaml'
        local_patched = f'checker/{self._vs_name}_vs_patched.yaml'
        
        # 备份当前VS
        dump_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml > {remote_backup}"
        self._remote(dump_cmd)
        self._download_vs_to_local(remote_backup, local_backup)
        
        # 应用patch
        patch_method(local_backup, local_patched, *args, **kwargs)
        
        # 上传并应用
        self._upload_file(local_patched, self._patched_path)
        apply_cmd = f"kubectl apply -f {self._patched_path}"
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
        
        local_new = f'checker/{self._vs_name}_vs_new.yaml'
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        self._upload_file(local_new, self._new_path)
        apply_cmd = f"kubectl apply -f {self._new_path}"
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
        
        local_new = f'checker/{self._vs_name}_vs_new.yaml'
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        self._upload_file(local_new, self._new_path)
        apply_cmd = f"kubectl apply -f {self._new_path}"
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
        
        local_new = f'checker/{self._vs_name}_vs_new.yaml'
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)
        
        self._upload_file(local_new, self._new_path)
        apply_cmd = f"kubectl apply -f {self._new_path}"
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
            self._upload_file(f'checker/{self._vs_name}_vs_backup.yaml', self._backup_path)
            replace_cmd = f"kubectl replace --force -f {self._backup_path}"
            out, err = self._remote(replace_cmd)
            print(f"  - 恢复VS输出: {out.strip()}")
            if err:
                print(f"  - 恢复VS错误: {err.strip()}")
            self._injected = False
        
        self._fault_type = None

# Main block removed to convert this file into a library module. 

