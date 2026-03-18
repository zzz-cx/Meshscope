"""EnvoyCollector —— 采集 Envoy access log 和 Gateway 日志。"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Set, Tuple

from istio_Dynamic_Test.models.test_case import CollectionResult, TestCase
from istio_Dynamic_Test.utils.pod_log_utils import PodLogFetcher
from istio_Dynamic_Test.utils.envoy_log_utils import EnvoyLogEnabler
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseCollector


# ── 底层采集实现（原 recorder/envoy_log_collector.py）────────────────────

class _EnvoyLogCollectorImpl:
    """底层 Envoy 日志采集，直接操作 kubectl / pod log。"""

    def __init__(self, ssh_client=None, namespace='default', result_dir='results/envoy_logs'):
        self.ssh_client = ssh_client
        self.namespace = namespace
        self.result_dir = result_dir
        os.makedirs(self.result_dir, exist_ok=True)

    def ensure_envoy_access_log(self, deployment, skip_if_enabled=True):
        EnvoyLogEnabler.enable_envoy_access_log(
            deployment, ssh_client=self.ssh_client,
            namespace=self.namespace, skip_if_enabled=skip_if_enabled,
        )

    def collect_envoy_logs(self, case_id, service, subset=None, tail_lines=100, deployment=None):
        if deployment:
            self.ensure_envoy_access_log(deployment)
        if subset:
            label_selector = f"app={service},version={subset}"
            file_prefix = f"{case_id}_{service}_v{subset}"
        else:
            label_selector = f"app={service}"
            file_prefix = f"{case_id}_{service}"
        pods = PodLogFetcher.get_pods_by_label(
            label_selector, namespace=self.namespace, ssh_client=self.ssh_client,
        )
        logs = {}
        for pod in pods:
            try:
                log = PodLogFetcher.get_pod_logs(
                    pod, namespace=self.namespace, container="istio-proxy",
                    tail_lines=tail_lines, ssh_client=self.ssh_client,
                )
                logs[pod] = log
                with open(os.path.join(self.result_dir, f"{file_prefix}_{pod}.log"), 'w', encoding='utf-8') as f:
                    f.write(log)
            except Exception as e:
                logs[pod] = f"[ERROR] {e}"
        return logs

    def collect_gateway_logs(self, case_id, tail_lines=200):
        try:
            pods = PodLogFetcher.get_pods_by_label(
                "istio=ingressgateway", namespace="istio-system", ssh_client=self.ssh_client,
            )
            for pod in pods:
                try:
                    log = PodLogFetcher.get_pod_logs(
                        pod, namespace="istio-system", container="istio-proxy",
                        tail_lines=tail_lines, ssh_client=self.ssh_client,
                    )
                    filename = f"{case_id}_gateway_{pod}.log"
                    with open(os.path.join(self.result_dir, filename), 'w', encoding='utf-8') as f:
                        f.write(log)
                    print(f"    Gateway log saved: {filename}")
                except Exception as e:
                    print(f"    Warning: gateway log failed for {pod}: {e}")
        except Exception as e:
            print(f"    Warning: cannot get gateway pods: {e}")


# ── BaseCollector 封装 ───────────────────────────────────────────────────

class EnvoyCollector(BaseCollector):
    """Envoy 日志采集器。"""

    def __init__(self, ssh_client: Optional[SSHClient] = None, namespace: str = "default",
                 result_dir: str = "results/envoy_logs"):
        self._ssh = ssh_client or SSHClient()
        self._namespace = namespace
        self._impl = _EnvoyLogCollectorImpl(
            ssh_client=self._ssh, namespace=namespace, result_dir=result_dir,
        )
        self._enabled: Set[str] = set()

    def collect(self, test_case: TestCase, pre_snapshot: dict = None) -> CollectionResult:
        tail = max(test_case.request_count * 3, 200)
        tasks = self._build_tasks(test_case, tail)
        envoy_logs = self._collect_parallel(tasks)

        if pre_snapshot and envoy_logs:
            envoy_logs = self._diff_logs(envoy_logs, pre_snapshot)

        self._impl.collect_gateway_logs(test_case.case_id, tail)
        return CollectionResult(case_id=test_case.case_id, envoy_logs=envoy_logs)

    def snapshot_log_lines(self, test_case: TestCase) -> dict:
        """记录每个 Pod 当前最后一行日志内容，作为增量采集的分割标记。"""
        snapshot = {}
        from istio_Dynamic_Test.utils.pod_log_utils import PodLogFetcher
        tasks = self._build_tasks(test_case, 1)
        for cid, svc, subset, _ in tasks:
            label = f"app={svc},version={subset}" if subset else f"app={svc}"
            try:
                pods = PodLogFetcher.get_pods_by_label(label, namespace=self._namespace, ssh_client=self._ssh)
                for pod in pods:
                    log = PodLogFetcher.get_pod_logs(
                        pod, namespace=self._namespace, container="istio-proxy",
                        tail_lines=1, ssh_client=self._ssh,
                    )
                    snapshot[pod] = log.strip().splitlines()[-1] if log and log.strip() else ""
            except Exception:
                pass
        return snapshot

    @staticmethod
    def _diff_logs(logs: dict, pre_snapshot: dict) -> dict:
        """用标记行截取：只保留标记行之后的新增日志。"""
        result = {}
        for pod, content in logs.items():
            if not content or content.startswith("[ERROR]"):
                result[pod] = content
                continue
            marker = pre_snapshot.get(pod, "")
            if not marker:
                result[pod] = content
                continue
            lines = content.splitlines()
            try:
                idx = None
                for i, line in enumerate(lines):
                    if line.strip() == marker.strip():
                        idx = i
                if idx is not None and idx + 1 < len(lines):
                    result[pod] = "\n".join(lines[idx + 1:])
                else:
                    result[pod] = content
            except Exception:
                result[pod] = content
        return result

    def ensure_access_log(self, service: str, subset: Optional[str] = None):
        dep = f"{service}-{subset}" if subset else service
        if dep not in self._enabled:
            try:
                self._impl.ensure_envoy_access_log(dep, skip_if_enabled=True)
                self._enabled.add(dep)
                print(f"  [COLLECTOR] access log enabled: {dep}")
            except Exception as e:
                print(f"  [COLLECTOR] warning: access log for {dep}: {e}")

    def warmup_for_suite(self, cases: List[TestCase]):
        svcs: Set[Tuple[str, Optional[str]]] = set()
        for tc in cases:
            svc = tc.host or tc.source_service
            if not svc or not _valid(svc):
                continue
            if tc.expected_distribution:
                for ver in tc.expected_distribution:
                    svcs.add((svc, ver))
            elif tc.expected_destination and _valid(tc.expected_destination):
                svcs.add((svc, tc.expected_destination))
            else:
                svcs.add((svc, None))
        print(f"  [COLLECTOR] warming up access logs for {len(svcs)} service/version(s)")
        for svc, subset in svcs:
            self.ensure_access_log(svc, subset)

    def _build_tasks(self, tc, tail):
        tasks = []
        svc = tc.host or tc.source_service
        if tc.expected_distribution:
            for ver in tc.expected_distribution:
                if _valid(svc):
                    tasks.append((tc.case_id, svc, ver, tail))
        elif tc.expected_destination and _valid(svc) and _valid(tc.expected_destination):
            tasks.append((tc.case_id, svc, tc.expected_destination, tail))
        elif _valid(svc):
            tasks.append((tc.case_id, svc, None, tail))
        return tasks

    def _collect_parallel(self, tasks):
        logs = {}
        if not tasks:
            return logs
        with ThreadPoolExecutor(max_workers=min(5, len(tasks))) as pool:
            futures = []
            for cid, svc, subset, tail in tasks:
                fut = pool.submit(self._impl.collect_envoy_logs, cid, svc, subset=subset, tail_lines=tail)
                futures.append((fut, f"{svc}-{subset}" if subset else svc))
            for fut, key in futures:
                try:
                    result = fut.result(timeout=30)
                    if result:
                        logs.update(result)
                except Exception as e:
                    print(f"  [COLLECTOR] warning: {key}: {e}")
        return logs


def _valid(v: str) -> bool:
    return bool(v and re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9\-_.]*[A-Za-z0-9])?", v))
