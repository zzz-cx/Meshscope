"""FaultInjector —— 通过 patch VirtualService 注入故障。

支持的故障类型：
- HTTP abort (503 等)
- Delay injection
- 上游错误 (路由到不存在的服务)
- 故障 + 超时组合
- 高负载场景 (用于熔断测试)
"""

import os
import shutil
import subprocess
import tempfile
import time

import yaml
from pathlib import Path

from istio_Dynamic_Test.utils.env_detector import K8sEnvDetector


class FaultInjector:
    _DEFAULT_NONEXISTENT_HOST = "nonexistent-service.default.svc.cluster.local"

    def __init__(self, ssh_client=None, vs_name='reviews', route_host='reviews', namespace='default'):
        self.ssh_client = ssh_client
        self._vs_name = vs_name
        self._route_host = route_host
        self._namespace = namespace
        self._use_ssh = K8sEnvDetector.should_use_ssh(ssh_client)
        if self._use_ssh:
            self._backup_path = f'/tmp/{vs_name}_vs_backup.yaml'
            self._patched_path = f'/tmp/{vs_name}_vs_patched.yaml'
            self._new_path = f'/tmp/{vs_name}_vs_new.yaml'
        else:
            _tmp = tempfile.gettempdir()
            self._backup_path = os.path.join(_tmp, f'{vs_name}_vs_backup.yaml')
            self._patched_path = os.path.join(_tmp, f'{vs_name}_vs_patched.yaml')
            self._new_path = os.path.join(_tmp, f'{vs_name}_vs_new.yaml')
        self._injected = False
        self._created = False
        self._fault_type = None
        self._local_dir = Path(__file__).resolve().parent
        self._local_dir.mkdir(parents=True, exist_ok=True)
        print(f"FaultInjector initialized for VS: {vs_name}, route_host: {route_host} "
              f"({'SSH' if self._use_ssh else 'local'})")

    def _local_file(self, filename: str) -> str:
        path = self._local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _remote(self, cmd):
        if self.ssh_client:
            return self.ssh_client.run_command(cmd)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout, result.stderr

    def _upload_file(self, local_path, remote_path):
        if not self._use_ssh or not self.ssh_client or not self.ssh_client.hostname:
            shutil.copy2(local_path, remote_path)
            return
        with open(local_path, 'r', encoding='utf-8') as f:
            content = f.read()
        create_cmd = f"cat > {remote_path} << 'EOF'\n{content}\nEOF"
        _, error = self.ssh_client.run_command(create_cmd)
        if error:
            raise RuntimeError(f"upload failed: {error}")

    def _download_vs_to_local(self, remote_path, local_path):
        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)
        if not self._use_ssh or not self.ssh_client or not self.ssh_client.hostname:
            if os.path.exists(remote_path):
                shutil.copy2(remote_path, local_path)
            else:
                cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
                output, error = self._remote(cmd)
                if not error:
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(output)
            return
        cmd = f"cat {remote_path}"
        output, error = self.ssh_client.run_command(cmd)
        if error:
            cmd = f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
            output, error = self._remote(cmd)
            if error:
                raise RuntimeError(f"download failed: {error}")
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(output)

    # ── VS patch 方法 ────────────────────────────────────────────────────

    def _patch_vs_fault(self, local_backup, local_patched, error_code=503, match_headers=None, match_path=None):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        fault_rule = {
            'fault': {'abort': {'httpStatus': error_code, 'percentage': {'value': 100}}},
            'route': [{'destination': {'host': self._route_host}}]
        }
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_config_fault(self, local_backup, local_patched, fault_type='abort',
                               status_code=503, delay='1s', percentage=100, match_headers=None):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        fault_rule = {'route': [{'destination': {'host': self._route_host}}]}
        if fault_type == 'abort':
            fault_rule['fault'] = {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}}
        elif fault_type == 'delay':
            fault_rule['fault'] = {'delay': {'fixedDelay': delay, 'percentage': {'value': percentage}}}
        elif fault_type == 'both':
            fault_rule['fault'] = {
                'abort': {'httpStatus': status_code, 'percentage': {'value': percentage // 2}},
                'delay': {'fixedDelay': delay, 'percentage': {'value': percentage // 2}},
            }
        if match_headers:
            fault_rule['match'] = [{'headers': {k: {'exact': v} for k, v in match_headers.items()}}]
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_high_load_scenario(self, local_backup, local_patched):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        rules = [
            {'fault': {'abort': {'httpStatus': 503, 'percentage': {'value': 80}}},
             'route': [{'destination': {'host': self._route_host}}]},
            {'fault': {'delay': {'fixedDelay': '2s', 'percentage': {'value': 15}}},
             'route': [{'destination': {'host': self._route_host}}]},
            {'route': [{'destination': {'host': self._route_host}}]},
        ]
        vs['spec']['http'] = rules + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_fault_with_timeout(self, local_backup, local_patched,
                                     status_code=503, percentage=100, timeout='2s'):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        rule = {
            'fault': {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}},
            'timeout': timeout,
            'route': [{'destination': {'host': self._route_host}}],
        }
        vs['spec']['http'] = [rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_upstream_error_scenario(self, local_backup, local_patched, error_percentage=80):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        ep = max(0, min(100, int(error_percentage)))
        hp = 100 - ep if ep < 100 else 0
        dests = [{'destination': {'host': self._DEFAULT_NONEXISTENT_HOST}, 'weight': ep}]
        if hp > 0:
            dests.append({'destination': {'host': self._route_host}, 'weight': hp})
        vs['spec']['http'] = [{'route': dests}] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    # ── 新建 VS 方法 ────────────────────────────────────────────────────

    def _generate_new_vs(self, local_path, error_code=503, match_headers=None, match_path=None):
        vs = {
            'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
            'metadata': {'name': self._vs_name, 'namespace': self._namespace},
            'spec': {'hosts': [self._route_host], 'http': [
                {'fault': {'abort': {'httpStatus': error_code, 'percentage': {'value': 100}}},
                 'route': [{'destination': {'host': self._route_host}}]}
            ]}
        }
        with open(local_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _apply_new_vs(self, local_path):
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            self._upload_file(local_path, self._new_path)
            cmd = f"kubectl apply -n {self._namespace} -f {self._new_path}"
        else:
            cmd = f'kubectl apply -n {self._namespace} -f "{local_path}"'
        out, err = self._remote(cmd)
        print(f"  - apply output: {out.strip()}")
        if err:
            print(f"  - apply error: {err.strip()}")
        self._created = True

    def _create_vs_from_dict(self, vs_dict):
        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs_dict, f)
        self._apply_new_vs(local_new)

    # ── 公开接口 ─────────────────────────────────────────────────────────

    def inject_http_fault(self, error_code=503, match_headers=None, match_path=None):
        print(f"  [FAULT] inject HTTP {error_code} into VS '{self._vs_name}'")
        self._fault_type = "http_fault"
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        if 'NotFound' in output or 'NotFound' in error:
            local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
            self._generate_new_vs(local_new, error_code, match_headers, match_path)
            self._apply_new_vs(local_new)
        else:
            self._backup_and_patch_vs(self._patch_vs_fault, error_code, match_headers, match_path)

    def inject_config_fault(self, fault_type='abort', status_code=503, delay='1s',
                            percentage=100, match_headers=None):
        print(f"  [FAULT] config fault {fault_type} ({percentage}%)")
        self._fault_type = f"config_fault_{fault_type}"
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        if 'NotFound' in output or 'NotFound' in error:
            rule = {'route': [{'destination': {'host': self._route_host}}]}
            if fault_type == 'abort':
                rule['fault'] = {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}}
            elif fault_type == 'delay':
                rule['fault'] = {'delay': {'fixedDelay': delay, 'percentage': {'value': percentage}}}
            self._create_vs_from_dict({
                'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
                'metadata': {'name': self._vs_name, 'namespace': self._namespace},
                'spec': {'hosts': [self._route_host], 'http': [rule]}
            })
        else:
            self._backup_and_patch_vs(self._patch_vs_config_fault, fault_type, status_code, delay, percentage, match_headers)

    def inject_high_load_scenario(self):
        print(f"  [FAULT] high load scenario for '{self._vs_name}'")
        self._fault_type = "high_load_scenario"
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        if 'NotFound' in output or 'NotFound' in error:
            rules = [
                {'fault': {'abort': {'httpStatus': 503, 'percentage': {'value': 80}}},
                 'route': [{'destination': {'host': self._route_host}}]},
                {'fault': {'delay': {'fixedDelay': '2s', 'percentage': {'value': 15}}},
                 'route': [{'destination': {'host': self._route_host}}]},
                {'route': [{'destination': {'host': self._route_host}}]},
            ]
            self._create_vs_from_dict({
                'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
                'metadata': {'name': self._vs_name, 'namespace': self._namespace},
                'spec': {'hosts': [self._route_host], 'http': rules}
            })
        else:
            self._backup_and_patch_vs(self._patch_vs_high_load_scenario)

    def inject_fault_with_timeout(self, status_code=503, percentage=100, timeout='2s'):
        print(f"  [FAULT] fault({status_code})+timeout({timeout}) for '{self._vs_name}'")
        self._fault_type = "fault_with_timeout"
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        if 'NotFound' in output or 'NotFound' in error:
            self._create_vs_from_dict({
                'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
                'metadata': {'name': self._vs_name, 'namespace': self._namespace},
                'spec': {'hosts': [self._route_host], 'http': [{
                    'fault': {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}},
                    'timeout': timeout,
                    'route': [{'destination': {'host': self._route_host}}],
                }]}
            })
        else:
            self._backup_and_patch_vs(self._patch_vs_fault_with_timeout, status_code, percentage, timeout)

    def inject_upstream_error_scenario(self, error_percentage=80):
        print(f"  [FAULT] upstream error {error_percentage}% for '{self._vs_name}'")
        self._fault_type = "upstream_error_scenario"
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        ep = max(0, min(100, int(error_percentage)))
        hp = 100 - ep if ep < 100 else 0
        dests = [{'destination': {'host': self._DEFAULT_NONEXISTENT_HOST}, 'weight': ep}]
        if hp > 0:
            dests.append({'destination': {'host': self._route_host}, 'weight': hp})
        if 'NotFound' in output or 'NotFound' in error:
            self._create_vs_from_dict({
                'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
                'metadata': {'name': self._vs_name, 'namespace': self._namespace},
                'spec': {'hosts': [self._route_host], 'http': [{'route': dests}]}
            })
        else:
            self._backup_and_patch_vs(self._patch_vs_upstream_error_scenario, error_percentage)

    # ── 通用备份 & patch ─────────────────────────────────────────────────

    def _backup_and_patch_vs(self, patch_method, *args, **kwargs):
        local_backup = self._local_file(f'{self._vs_name}_vs_backup.yaml')
        local_patched = self._local_file(f'{self._vs_name}_vs_patched.yaml')
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml > {self._backup_path}")
            self._download_vs_to_local(self._backup_path, local_backup)
        else:
            output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml")
            if error:
                raise RuntimeError(f"get VS failed: {error}")
            with open(local_backup, 'w', encoding='utf-8') as f:
                f.write(output)
        patch_method(local_backup, local_patched, *args, **kwargs)
        if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
            self._upload_file(local_patched, self._patched_path)
            cmd = f"kubectl apply -n {self._namespace} -f {self._patched_path}"
        else:
            cmd = f'kubectl apply -n {self._namespace} -f "{local_patched}"'
        out, err = self._remote(cmd)
        print(f"  - patch output: {out.strip()}")
        if err:
            print(f"  - patch warning: {err.strip()}")
        self._injected = True

    def clear_faults(self):
        print(f"  [CLEANUP] clear faults from VS '{self._vs_name}' (type: {self._fault_type})")
        if self._created:
            out, err = self._remote(f"kubectl delete virtualservice {self._vs_name} -n {self._namespace} --ignore-not-found")
            print(f"  - delete: {out.strip()}")
            self._created = False
        elif self._injected:
            local_backup = self._local_file(f'{self._vs_name}_vs_backup.yaml')
            self._upload_file(local_backup, self._backup_path)
            out, err = self._remote(f"kubectl replace --force -n {self._namespace} -f {self._backup_path}")
            print(f"  - restore: {out.strip()}")
            self._injected = False
        self._fault_type = None
