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
import threading

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.utils.env_detector import K8sEnvDetector
from istio_Dynamic_Test.utils.ingress_shard import is_synth_ingress_vs_resource_name


_VS_YAML_CACHE = {}  # (namespace, vs_name) -> 最近一次「干净」YAML（清理后或 kubectl get 后）
_VS_CACHE_LOCK = threading.Lock()


def _fault_vs_cache_enabled() -> bool:
    v = (os.getenv("DYNAMIC_TEST_FAULT_VS_CACHE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _post_fault_apply_wait_seconds() -> float:
    """Pilot 下发到 ingress gateway 有滞后；缓存命中时 apply 更快，不等待易 curl 到旧路由。"""
    try:
        s = float((os.getenv("DYNAMIC_TEST_POST_FAULT_APPLY_S") or "2").strip() or "2")
    except ValueError:
        s = 2.0
    return max(0.0, s)


def _vs_patch_lock_for(vs_name: str) -> Optional[threading.Lock]:
    """合成入口 VS 家族按资源名互斥；其它 VS 仍由调用方保证不并发写。"""
    if not is_synth_ingress_vs_resource_name(vs_name):
        return None
    with FaultInjector._SYNTH_INGRESS_LOCK_REGISTRY_GUARD:
        lk = FaultInjector._SYNTH_INGRESS_LOCK_BY_VS.get(vs_name)
        if lk is None:
            lk = threading.Lock()
            FaultInjector._SYNTH_INGRESS_LOCK_BY_VS[vs_name] = lk
        return lk


class FaultInjector:
    _DEFAULT_NONEXISTENT_HOST = "nonexistent-service.default.svc.cluster.local"
    _SYNTH_INGRESS_LOCK_REGISTRY_GUARD = threading.Lock()
    _SYNTH_INGRESS_LOCK_BY_VS = {}  # type: ignore[var-annotated]

    def __init__(self, ssh_client=None, vs_name='reviews', route_host='reviews', namespace='default'):
        self.ssh_client = ssh_client
        # 用例中有些“全局 host=*”场景会把 vs_name 传成 "*"（不是合法 K8s 资源名），
        # 这里统一映射到我们合成入口 VS，避免 kubectl apply/get 因非法名称直接失败。
        self._vs_name = "meshscope-synth-ingress" if vs_name == "*" else vs_name
        self._route_host = route_host
        self._namespace = namespace
        self._use_ssh = K8sEnvDetector.should_use_ssh(ssh_client)
        _fn_safe = self._vs_name.replace("/", "-").replace(":", "-")
        if self._use_ssh:
            self._backup_path = f'/tmp/{_fn_safe}_vs_backup.yaml'
            self._patched_path = f'/tmp/{_fn_safe}_vs_patched.yaml'
            self._new_path = f'/tmp/{_fn_safe}_vs_new.yaml'
        else:
            _tmp = tempfile.gettempdir()
            self._backup_path = os.path.join(_tmp, f'{_fn_safe}_vs_backup.yaml')
            self._patched_path = os.path.join(_tmp, f'{_fn_safe}_vs_patched.yaml')
            self._new_path = os.path.join(_tmp, f'{_fn_safe}_vs_new.yaml')
        self._injected = False
        self._created = False
        self._fault_type = None
        self._local_dir = Path(__file__).resolve().parent
        self._local_dir.mkdir(parents=True, exist_ok=True)
        print(f"FaultInjector initialized for VS: {self._vs_name}, route_host: {route_host} "
              f"({'SSH' if self._use_ssh else 'local'})")

    def _cache_key(self):
        return (self._namespace, self._vs_name)

    def _virtualservice_exists(self) -> bool:
        ck = self._cache_key()
        if _fault_vs_cache_enabled():
            with _VS_CACHE_LOCK:
                if ck in _VS_YAML_CACHE:
                    return True
        output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace}")
        return "NotFound" not in (output or "") + (error or "")

    def _local_file(self, filename: str) -> str:
        path = self._local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _pick_existing_destination_host(self, vs: dict) -> str:
        """
        从现有 VirtualService 规则中挑一个可用的 destination.host，避免注入时写入非法 host（例如 '*'）。
        """
        try:
            http = ((vs.get("spec") or {}).get("http") or [])
            for rb in http:
                if not isinstance(rb, dict):
                    continue
                routes = rb.get("route") or []
                for r in routes:
                    if not isinstance(r, dict):
                        continue
                    dest = r.get("destination") or {}
                    if not isinstance(dest, dict):
                        continue
                    host = dest.get("host")
                    if isinstance(host, str) and host and host != "*":
                        return host
        except Exception:
            pass
        return ""

    def _route_destination_like_existing(self, vs: dict, host: str) -> Dict[str, Any]:
        """
        与现有合成入口 VS 中对齐：同 host 尽量复用 subset/port（DR 定义 subset 时缺失可能导致行为异常）。
        """
        h = (host or "").strip()
        if not h or h == "*":
            h = self._pick_existing_destination_host(vs) or self._DEFAULT_NONEXISTENT_HOST
        try:
            http = ((vs.get("spec") or {}).get("http") or [])
            for rb in http:
                if not isinstance(rb, dict):
                    continue
                for r in rb.get("route") or []:
                    if not isinstance(r, dict):
                        continue
                    dest = r.get("destination") or {}
                    if not isinstance(dest, dict):
                        continue
                    if dest.get("host") == h:
                        out: Dict[str, Any] = {"host": h}
                        if dest.get("subset") is not None:
                            out["subset"] = dest["subset"]
                        if dest.get("port") is not None:
                            out["port"] = dest["port"]
                        return out
        except Exception:
            pass
        if h.startswith("meshscope-svc-"):
            return {"host": h, "subset": "v1", "port": {"number": 80}}
        return {"host": h}

    def _remote(self, cmd):
        if self.ssh_client:
            return self.ssh_client.run_command(cmd)
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return result.stdout, result.stderr

    def _merge_live_metadata_into_patched_vs(self, local_patched: str) -> None:
        """
        仅同步 resourceVersion/uid/generation，避免整块替换 metadata 时把旧的
        kubectl.kubernetes.io/last-applied-configuration 并进来，导致 apply 把 spec 合并回「无故障」状态。
        """
        out, err = self._remote(
            "kubectl get virtualservice {0} -n {1} -o yaml".format(self._vs_name, self._namespace)
        )
        if err or not out:
            return
        try:
            live = yaml.safe_load(out)
            with open(local_patched, 'r', encoding='utf-8') as f:
                patched = yaml.safe_load(f)
            if not isinstance(live, dict) or not isinstance(patched, dict):
                return
            lm = live.get("metadata")
            pm = patched.get("metadata")
            if not isinstance(lm, dict) or not isinstance(pm, dict):
                return
            for k in ("resourceVersion", "uid", "generation"):
                if k in lm:
                    pm[k] = lm[k]
            pm.pop("kubectl.kubernetes.io/last-applied-configuration", None)
            patched["metadata"] = pm
            patched.pop("status", None)
            with open(local_patched, 'w', encoding='utf-8') as f:
                yaml.safe_dump(patched, f)
        except Exception:
            pass

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
        dest = self._route_destination_like_existing(vs, self._route_host)
        fault_rule = {
            'fault': {'abort': {'httpStatus': error_code, 'percentage': {'value': 100}}},
            'route': [{'destination': dest}],
        }
        match = {}
        if match_headers:
            match["headers"] = {k: {'exact': v} for k, v in match_headers.items()}
        if match_path:
            match["uri"] = {"prefix": match_path}
        if match:
            fault_rule["match"] = [match]
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_config_fault(
        self,
        local_backup,
        local_patched,
        fault_type='abort',
        status_code=503,
        delay='1s',
        percentage=100,
        match_headers=None,
        match_path: str = None,
    ):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        dest_host = self._route_host
        if dest_host == "*" or not dest_host:
            dest_host = self._pick_existing_destination_host(vs) or self._DEFAULT_NONEXISTENT_HOST
        fault_rule = {'route': [{'destination': self._route_destination_like_existing(vs, dest_host)}]}
        if fault_type == 'abort':
            fault_rule['fault'] = {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}}
        elif fault_type == 'delay':
            fault_rule['fault'] = {'delay': {'fixedDelay': delay, 'percentage': {'value': percentage}}}
        elif fault_type == 'both':
            fault_rule['fault'] = {
                'abort': {'httpStatus': status_code, 'percentage': {'value': percentage // 2}},
                'delay': {'fixedDelay': delay, 'percentage': {'value': percentage // 2}},
            }
        match = {}
        if match_headers:
            match["headers"] = {k: {'exact': v} for k, v in match_headers.items()}
        if match_path:
            match["uri"] = {"prefix": match_path}
        if match:
            fault_rule["match"] = [match]
        vs['spec']['http'] = [fault_rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_multi_ingress_faults(
        self,
        local_backup,
        local_patched,
        items: List[Dict[str, Any]],
    ):
        """在单个 VS 上追加多条带 uri.prefix 的 http 规则（用于正交 bundle）。"""
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        new_rules = []
        for it in items:
            dest = it.get("route_host") or self._route_host
            if dest == "*" or not dest:
                dest = self._pick_existing_destination_host(vs) or self._DEFAULT_NONEXISTENT_HOST
            mode = it.get("mode")
            match_path = it.get("match_path") or ""
            pct = int(it.get("percentage", 100))
            rule = {"route": [{"destination": self._route_destination_like_existing(vs, dest)}]}
            if mode == "abort":
                sc = int(it.get("status_code", 503))
                rule["fault"] = {"abort": {"httpStatus": sc, "percentage": {"value": pct}}}
            elif mode == "delay":
                delay = str(it.get("delay", "1s"))
                rule["fault"] = {"delay": {"fixedDelay": delay, "percentage": {"value": pct}}}
            elif mode == "fault_timeout":
                sc = int(it.get("status_code", 503))
                rule["fault"] = {"abort": {"httpStatus": sc, "percentage": {"value": pct}}}
                rule["timeout"] = str(it.get("timeout", "2s"))
            else:
                raise ValueError("unknown multi-fault mode: {0}".format(mode))
            if match_path:
                rule["match"] = [{"uri": {"prefix": match_path}}]
            new_rules.append(rule)
        vs["spec"]["http"] = new_rules + vs["spec"].get("http", [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_high_load_scenario(self, local_backup, local_patched):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        dest_host = self._route_host
        if dest_host == "*" or not dest_host:
            dest_host = self._pick_existing_destination_host(vs) or self._DEFAULT_NONEXISTENT_HOST
        rules = [
            {'fault': {'abort': {'httpStatus': 503, 'percentage': {'value': 80}}},
             'route': [{'destination': {'host': dest_host}}]},
            {'fault': {'delay': {'fixedDelay': '2s', 'percentage': {'value': 15}}},
             'route': [{'destination': {'host': dest_host}}]},
            {'route': [{'destination': {'host': dest_host}}]},
        ]
        vs['spec']['http'] = rules + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_fault_with_timeout(
        self,
        local_backup,
        local_patched,
        status_code=503,
        percentage=100,
        timeout='2s',
        match_headers=None,
        match_path: str = None,
    ):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        dest_host = self._route_host
        if dest_host == "*" or not dest_host:
            dest_host = self._pick_existing_destination_host(vs) or self._DEFAULT_NONEXISTENT_HOST
        rule = {
            'fault': {'abort': {'httpStatus': status_code, 'percentage': {'value': percentage}}},
            'timeout': timeout,
            'route': [{'destination': self._route_destination_like_existing(vs, dest_host)}],
        }
        match = {}
        if match_headers:
            match["headers"] = {k: {'exact': v} for k, v in match_headers.items()}
        if match_path:
            match["uri"] = {"prefix": match_path}
        if match:
            rule["match"] = [match]
        vs['spec']['http'] = [rule] + vs['spec'].get('http', [])
        with open(local_patched, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs, f)

    def _patch_vs_upstream_error_scenario(self, local_backup, local_patched, error_percentage=80, match_path: str = None):
        with open(local_backup, 'r', encoding='utf-8') as f:
            vs = yaml.safe_load(f)
        ep = max(0, min(100, int(error_percentage)))
        hp = 100 - ep if ep < 100 else 0
        dests = [{'destination': {'host': self._DEFAULT_NONEXISTENT_HOST}, 'weight': ep}]
        if hp > 0:
            dests.append({'destination': {'host': self._route_host}, 'weight': hp})
        rule: dict = {'route': dests}
        if match_path:
            rule['match'] = [{'uri': {'prefix': match_path}}]
        vs['spec']['http'] = [rule] + vs['spec'].get('http', [])
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
        lock = _vs_patch_lock_for(self._vs_name)
        if lock:
            lock.acquire()
        try:
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
        finally:
            if lock:
                lock.release()

    def _create_vs_from_dict(self, vs_dict):
        local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
        with open(local_new, 'w', encoding='utf-8') as f:
            yaml.safe_dump(vs_dict, f)
        self._apply_new_vs(local_new)

    # ── 公开接口 ─────────────────────────────────────────────────────────

    def inject_http_fault(self, error_code=503, match_headers=None, match_path=None):
        print(f"  [FAULT] inject HTTP {error_code} into VS '{self._vs_name}'")
        self._fault_type = "http_fault"
        if not self._virtualservice_exists():
            local_new = self._local_file(f'{self._vs_name}_vs_new.yaml')
            self._generate_new_vs(local_new, error_code, match_headers, match_path)
            self._apply_new_vs(local_new)
        else:
            self._backup_and_patch_vs(self._patch_vs_fault, error_code, match_headers, match_path)

    def inject_config_fault(
        self,
        fault_type='abort',
        status_code=503,
        delay='1s',
        percentage=100,
        match_headers=None,
        match_path: str = None,
    ):
        print(f"  [FAULT] config fault {fault_type} ({percentage}%)")
        self._fault_type = f"config_fault_{fault_type}"
        if not self._virtualservice_exists():
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
            self._backup_and_patch_vs(
                self._patch_vs_config_fault,
                fault_type,
                status_code,
                delay,
                percentage,
                match_headers,
                match_path,
            )

    def inject_high_load_scenario(self):
        print(f"  [FAULT] high load scenario for '{self._vs_name}'")
        self._fault_type = "high_load_scenario"
        if not self._virtualservice_exists():
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

    def inject_fault_with_timeout(
        self,
        status_code=503,
        percentage=100,
        timeout='2s',
        match_headers=None,
        match_path: str = None,
    ):
        print(f"  [FAULT] fault({status_code})+timeout({timeout}) for '{self._vs_name}'")
        self._fault_type = "fault_with_timeout"
        if not self._virtualservice_exists():
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
            self._backup_and_patch_vs(
                self._patch_vs_fault_with_timeout,
                status_code,
                percentage,
                timeout,
                match_headers,
                match_path,
            )

    def inject_multi_ingress_faults(
        self,
        items: List[Dict[str, Any]],
        fault_group_name: str = "orthogonal_bundle",
    ) -> None:
        """
        一次备份/apply，在入口 VS 上追加多条独立 match 的 fault 规则。
        items: mode in abort|delay|fault_timeout，含 route_host、match_path 等。
        """
        if not items:
            raise ValueError("inject_multi_ingress_faults: empty items")
        print(
            "  [FAULT] multi ingress faults ({0} rules) VS '{1}'".format(
                len(items), self._vs_name
            )
        )
        self._fault_type = "multi_{0}".format(fault_group_name)
        if not self._virtualservice_exists():
            raise RuntimeError(
                "inject_multi_ingress_faults requires VirtualService {0} to exist".format(
                    self._vs_name
                )
            )
        self._backup_and_patch_vs(self._patch_vs_multi_ingress_faults, items)

    def inject_upstream_error_scenario(self, error_percentage=80, match_path: str = None):
        print(f"  [FAULT] upstream error {error_percentage}% for '{self._vs_name}'")
        self._fault_type = "upstream_error_scenario"
        ep = max(0, min(100, int(error_percentage)))
        hp = 100 - ep if ep < 100 else 0
        dests = [{'destination': {'host': self._DEFAULT_NONEXISTENT_HOST}, 'weight': ep}]
        if hp > 0:
            dests.append({'destination': {'host': self._route_host}, 'weight': hp})
        if not self._virtualservice_exists():
            self._create_vs_from_dict({
                'apiVersion': 'networking.istio.io/v1beta1', 'kind': 'VirtualService',
                'metadata': {'name': self._vs_name, 'namespace': self._namespace},
                'spec': {'hosts': [self._route_host], 'http': ([{'match': [{'uri': {'prefix': match_path}}], 'route': dests}] if match_path else [{'route': dests}])}
            })
        else:
            self._backup_and_patch_vs(self._patch_vs_upstream_error_scenario, error_percentage, match_path)

    # ── 通用备份 & patch ─────────────────────────────────────────────────

    def _backup_and_patch_vs(self, patch_method, *args, **kwargs):
        lock = _vs_patch_lock_for(self._vs_name)
        if lock:
            lock.acquire()
        try:
            local_backup = self._local_file(f'{self._vs_name}_vs_backup.yaml')
            local_patched = self._local_file(f'{self._vs_name}_vs_patched.yaml')
            ck = self._cache_key()
            used_cache = False
            cached_yaml = None
            if _fault_vs_cache_enabled():
                with _VS_CACHE_LOCK:
                    cached_yaml = _VS_YAML_CACHE.get(ck)
            if cached_yaml is not None:
                with open(local_backup, 'w', encoding='utf-8') as f:
                    f.write(cached_yaml)
                used_cache = True
            if not used_cache:
                if self._use_ssh and self.ssh_client and self.ssh_client.hostname:
                    self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml > {self._backup_path}")
                    self._download_vs_to_local(self._backup_path, local_backup)
                else:
                    output, error = self._remote(f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml")
                    if error:
                        raise RuntimeError(f"get VS failed: {error}")
                    with open(local_backup, 'w', encoding='utf-8') as f:
                        f.write(output)
                if _fault_vs_cache_enabled():
                    with open(local_backup, 'r', encoding='utf-8') as f:
                        clean = f.read()
                    with _VS_CACHE_LOCK:
                        _VS_YAML_CACHE[ck] = clean
            patch_method(local_backup, local_patched, *args, **kwargs)
            self._merge_live_metadata_into_patched_vs(local_patched)
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
            w = _post_fault_apply_wait_seconds()
            if w > 0:
                time.sleep(w)
        finally:
            if lock:
                lock.release()

    def clear_faults(self):
        print(f"  [CLEANUP] clear faults from VS '{self._vs_name}' (type: {self._fault_type})")
        lock = _vs_patch_lock_for(self._vs_name)
        if lock:
            lock.acquire()
        ck = self._cache_key()
        try:
            if self._created:
                out, err = self._remote(f"kubectl delete virtualservice {self._vs_name} -n {self._namespace} --ignore-not-found")
                print(f"  - delete: {out.strip()}")
                self._created = False
                if _fault_vs_cache_enabled():
                    with _VS_CACHE_LOCK:
                        _VS_YAML_CACHE.pop(ck, None)
            elif self._injected:
                local_backup = self._local_file(f'{self._vs_name}_vs_backup.yaml')
                self._upload_file(local_backup, self._backup_path)
                out, err = self._remote(f"kubectl replace --force -n {self._namespace} -f {self._backup_path}")
                print(f"  - restore: {out.strip()}")
                self._injected = False
                output, err_get = self._remote(
                    f"kubectl get virtualservice {self._vs_name} -n {self._namespace} -o yaml"
                )
                if output and not err_get:
                    try:
                        with open(local_backup, 'w', encoding='utf-8') as f:
                            f.write(output)
                        if _fault_vs_cache_enabled():
                            with _VS_CACHE_LOCK:
                                _VS_YAML_CACHE[ck] = output
                    except Exception:
                        pass
                elif _fault_vs_cache_enabled() and os.path.exists(local_backup):
                    try:
                        with open(local_backup, 'r', encoding='utf-8') as f:
                            clean = f.read()
                        with _VS_CACHE_LOCK:
                            _VS_YAML_CACHE[ck] = clean
                    except Exception:
                        pass
            self._fault_type = None
        finally:
            if lock:
                lock.release()
