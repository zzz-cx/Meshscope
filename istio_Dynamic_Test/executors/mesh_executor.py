"""MeshExecutor —— 从 mesh 内部 Pod 发起请求。

必须从应用容器（非 istio-proxy）发起请求，流量才会经 sidecar 劫持并应用 VirtualService。
从 istio-proxy 发 curl 会绕过劫持，直接走 K8s 负载均衡到所有 pod（含 VS 未配置的 v3）。

典型用途：流量分割验证。
traffic_split 由 Collector 通过 Prometheus 前后快照增量校验，本执行器仅负责发固定 N 次请求。
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.models.test_case import ExecutionResult, PolicyType, TestCase
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseExecutor


class MeshExecutor(BaseExecutor):
    """从 mesh 内部 Pod 发起请求的执行器。

    从应用容器（app_container）发起请求，流量经 sidecar 劫持后应用 VirtualService。
    若从 istio-proxy 发请求会绕过 VS，直接走 K8s 负载均衡。

    Args:
        ssh_client: SSH 客户端。
        source_deploy: 发起请求的 Deployment 名（默认 productpage-v1）。
        app_container: 应用容器名，需有 curl（默认 productpage）。traffic_split 必须用此容器。
        namespace: K8s 命名空间。
    """

    def __init__(
        self,
        ssh_client: Optional[SSHClient] = None,
        source_deploy: str = "productpage-v1",
        app_container: str = "productpage",
        namespace: str = "default",
    ):
        self._ssh = ssh_client or SSHClient()
        self._source_deploy = source_deploy
        self._app_container = app_container
        self._namespace = namespace

    def execute(self, test_case: TestCase) -> ExecutionResult:
        n = test_case.request_count
        conc = min(test_case.concurrency, n, 10)
        # traffic_split 提高并发以缩短发送时间（不影响分布验证）
        if PolicyType.TRAFFIC_SPLIT in getattr(test_case, "policy_types", []):
            conc = min(max(conc, 8), n, 10)

        target_host = test_case.host or test_case.source_service
        path = test_case.path.rstrip("/") if test_case.path else ""
        if not path or path == "/":
            path = f"/{target_host}/0"
        target_url = f"http://{target_host}:9080{path}"

        header_parts = ['-H "Connection: close"']  # 避免连接复用，确保每次请求独立路由
        for k, v in test_case.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)

        # 必须从应用容器发起，流量才经 sidecar 应用 VS；版本分布由 Prometheus 校验
        container = self._app_container
        base_cmd = (
            f"kubectl exec deploy/{self._source_deploy} -n {self._namespace} "
            f"-c {container} -- "
            f'curl -s -o /dev/null -w "%{{http_code}}" {header_str} "{target_url}"'
        )

        # 探测：应用容器无 curl 时回退到 istio-proxy（会绕过 VS，Prometheus 仍可采集）
        probe_out, probe_err = self._ssh.run_command(base_cmd)
        probe_text = (probe_out or "") + (probe_err or "")
        probe_lower = probe_text.lower()
        no_curl = (
            "command not found" in probe_lower
            or "curl:" in probe_lower
            or "executable file not found" in probe_lower
        )
        if no_curl and container == self._app_container:
            print(f"  [MESH] {container} 容器无 curl，回退到 istio-proxy（会绕过 VS，结果可能含 v3）")
            container = "istio-proxy"
            base_cmd = (
                f"kubectl exec deploy/{self._source_deploy} -n {self._namespace} "
                f"-c {container} -- "
                f'curl -s -o /dev/null -w "%{{http_code}}" {header_str} "{target_url}"'
            )

        print(f"  [MESH] {n} requests via deploy/{self._source_deploy} -c {container} -> {target_url}")
        print(f"  [MESH] concurrency={conc} (Prometheus 增量校验)")

        codes: dict[str, int] = {}
        total_time = 0.0

        def _send():
            s = time.time()
            out, err = self._ssh.run_command(base_cmd)
            elapsed = time.time() - s
            code = out.strip() if out and out.strip() else "error"
            return code, elapsed

        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(_send) for _ in range(n)]
            done = 0
            for fut in as_completed(futures):
                try:
                    code, elapsed = fut.result(timeout=60)
                    codes[code] = codes.get(code, 0) + 1
                    total_time += elapsed
                except Exception:
                    codes["error"] = codes.get("error", 0) + 1
                done += 1
                if done % 20 == 0 or done == n:
                    print(f"  [MESH] progress: {done}/{n}")

        total = sum(codes.values())
        success = sum(c for k, c in codes.items() if k.startswith("2"))
        rate = (success / total * 100) if total > 0 else 0.0
        avg_t = total_time / total if total > 0 else 0.0

        print(f"  [MESH] results: {dict(sorted(codes.items()))}")

        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes=codes,
            total_requests=total,
            success_rate=rate,
            avg_response_time=avg_t,
            error_count=total - success,
        )
