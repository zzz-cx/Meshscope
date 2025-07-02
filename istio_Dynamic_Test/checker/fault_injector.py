import time
import os
import paramiko
import yaml

class FaultInjector:
    """
    支持自动生成/patch 任意 VirtualService 实现故障注入。
    - 无目标 VS 时新建，清理时删除。
    - 有目标 VS 时先备份，patch 注入高优先级路由，清理时恢复。
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
        print(f"🔥 [INJECTING FAULT] patch VS '{self._vs_name}' 注入 HTTP {error_code} 故障...")
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
            remote_backup = self._backup_path
            local_backup = f'checker/{self._vs_name}_vs_backup.yaml'
            local_patched = f'checker/{self._vs_name}_vs_patched.yaml'
            dump_cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml > {remote_backup}"
            self._remote(dump_cmd)
            self._download_vs_to_local(remote_backup, local_backup)
            self._patch_vs_fault(local_backup, local_patched, error_code, match_headers, match_path)
            self._upload_file(local_patched, self._patched_path)
            apply_cmd = f"kubectl apply -f {self._patched_path}"
            out, err = self._remote(apply_cmd)
            print(f"  - patch VS输出: {out.strip()}")
            if err:
                print(f"  - patch VS错误: {err.strip()}")
            self._injected = True

    def clear_faults(self):
        print(f"🧹 [CLEARING FAULT] 清除 VS '{self._vs_name}' 的所有故障...")
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

# Main block removed to convert this file into a library module. 

