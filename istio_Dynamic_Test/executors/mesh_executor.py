"""MeshExecutor —— 从 mesh 内部 Pod 发起请求。

通过 ``kubectl exec`` 在 istio-proxy sidecar 中执行 curl，
使请求经过 Envoy 代理，确保 VirtualService 路由规则生效，
sidecar 日志可被采集用于流量分布等验证。

典型用途：流量分割验证（需要从 mesh 内部发起请求才能触发内部路由规则）。
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseExecutor


class MeshExecutor(BaseExecutor):
    """从 mesh 内部 Pod 发起请求的执行器。

    通过 ``kubectl exec <pod> -c istio-proxy -- curl ...`` 发送请求，
    请求经过 Envoy sidecar，VirtualService 路由规则完全生效。

    Args:
        ssh_client: SSH 客户端。
        source_deploy: 发起请求的 Deployment 名（默认 productpage-v1）。
        namespace: K8s 命名空间。
    """

    def __init__(
        self,
        ssh_client: Optional[SSHClient] = None,
        source_deploy: str = "productpage-v1",
        namespace: str = "default",
    ):
        self._ssh = ssh_client or SSHClient()
        self._source_deploy = source_deploy
        self._namespace = namespace

    def execute(self, test_case: TestCase) -> ExecutionResult:
        n = test_case.request_count
        conc = min(test_case.concurrency, n, 10)

        target_host = test_case.host or test_case.source_service
        path = test_case.path.rstrip("/") if test_case.path else ""
        if not path or path == "/":
            path = f"/{target_host}/0"
        target_url = f"http://{target_host}:9080{path}"

        header_parts = ['-H "Connection: close"']  # 避免连接复用，确保每次请求独立路由
        for k, v in test_case.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)
        base_cmd = (
            f"kubectl exec deploy/{self._source_deploy} -n {self._namespace} "
            f"-c istio-proxy -- "
            f'curl -s -o /dev/null -w "%{{http_code}}" {header_str} "{target_url}"'
        )

        print(f"  [MESH] {n} requests via deploy/{self._source_deploy} -> {target_url}")
        print(f"  [MESH] concurrency={conc}")

        codes: dict[str, int] = {}
        total_time = 0.0

        def _send():
            s = time.time()
            out, err = self._ssh.run_command(base_cmd)
            elapsed = time.time() - s
            code = out.strip() if out.strip() else "error"
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
