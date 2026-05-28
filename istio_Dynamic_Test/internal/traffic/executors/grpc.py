"""gRPC 执行器 —— 基于 grpcurl（入口 / mesh 内 / 负载）。"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, PolicyType, TestCase
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor
from istio_Dynamic_Test.internal.traffic.protocols.grpc.grpcurl import (
    build_grpcurl_cmd,
    run_grpcurl_once,
)
from istio_Dynamic_Test.internal.traffic.protocols.grpc.status import count_success_from_grpc_status_map
from istio_Dynamic_Test.internal.traffic.protocols.grpc.target import resolve_grpc_endpoint, resolve_grpc_method
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient


class GrpcExecutor(BaseExecutor):
    """从入口（SSH 节点）发起单次 gRPC 请求。"""

    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()
        self._grpcurl_available: Optional[bool] = None

    def execute(self, test_case: TestCase) -> ExecutionResult:
        if not self._check_grpcurl():
            return ExecutionResult(
                case_id=test_case.case_id,
                status_codes={"error": 1},
                total_requests=1,
                success_rate=0.0,
                error_count=1,
                raw_output="grpcurl not found on remote host",
                metadata={"protocol": "grpc", "error": "grpcurl_missing"},
            )

        cmd, label = build_grpcurl_cmd(test_case)
        print(f"  [gRPC] {label}")
        print(f"  [gRPC] {cmd}")
        start = time.time()
        code, output, error, ok = run_grpcurl_once(self._ssh, test_case)
        elapsed = time.time() - start
        print(f"  [gRPC] status={code}  time={elapsed:.3f}s")
        if error:
            print(f"  [gRPC] stderr: {error[:200]}")

        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes={code: 1},
            total_requests=1,
            success_rate=100.0 if ok else 0.0,
            avg_response_time=elapsed,
            error_count=0 if ok else 1,
            raw_output=output,
            metadata={"protocol": "grpc", "grpc_method": resolve_grpc_method(test_case)},
        )

    def _check_grpcurl(self) -> bool:
        if self._grpcurl_available is not None:
            return self._grpcurl_available
        out, err = self._ssh.run_command("grpcurl -version 2>&1 || grpcurl 2>&1")
        combined = (out or "") + (err or "")
        self._grpcurl_available = (
            "grpcurl" in combined.lower()
            and "not found" not in combined.lower()
            and "not recognized" not in combined.lower()
        )
        if not self._grpcurl_available:
            print("  [gRPC] grpcurl not found on SSH host")
        return self._grpcurl_available


class GrpcLoadExecutor(GrpcExecutor):
    """并行多次 grpcurl，用于负载类用例。"""

    def execute(self, test_case: TestCase) -> ExecutionResult:
        if not self._check_grpcurl():
            return ExecutionResult(
                case_id=test_case.case_id,
                status_codes={"error": 1},
                total_requests=0,
                success_rate=0.0,
                metadata={"protocol": "grpc", "error": "grpcurl_missing"},
            )

        n = max(int(test_case.request_count or 1), 1)
        conc = min(int(test_case.concurrency or 1), n, 10)
        print(f"  [gRPC-LOAD] batch x{n} (concurrency={conc})")

        codes: dict = {}
        total_time = 0.0

        def _send():
            s = time.time()
            code, _out, _err, _ok = run_grpcurl_once(self._ssh, test_case, max_time=15)
            return code, time.time() - s

        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(_send) for _ in range(n)]
            for fut in as_completed(futures):
                try:
                    code, elapsed = fut.result(timeout=60)
                    codes[code] = codes.get(code, 0) + 1
                    total_time += elapsed
                except Exception:
                    codes["error"] = codes.get("error", 0) + 1

        total = sum(codes.values())
        success = count_success_from_grpc_status_map(codes)
        rate = (success / total * 100) if total > 0 else 0.0
        print(f"  [gRPC-LOAD] results: {codes}")
        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes=codes,
            total_requests=total,
            success_rate=rate,
            avg_response_time=total_time / total if total > 0 else 0.0,
            error_count=total - success,
            metadata={"protocol": "grpc", "grpc_method": resolve_grpc_method(test_case)},
        )


class GrpcMeshExecutor(GrpcExecutor):
    """从 mesh 内应用 Pod 发起 gRPC（经 sidecar 应用 VS）。"""

    def __init__(
        self,
        ssh_client: Optional[SSHClient] = None,
        source_deploy: str = "productpage-v1",
        app_container: str = "productpage",
        namespace: str = "default",
        default_port: int = 9080,
    ):
        super().__init__(ssh_client)
        self._source_deploy = source_deploy
        self._app_container = app_container
        self._namespace = namespace
        self._default_port = default_port

    def execute(self, test_case: TestCase) -> ExecutionResult:
        if not self._check_grpcurl():
            return ExecutionResult(
                case_id=test_case.case_id,
                status_codes={"error": 1},
                total_requests=0,
                success_rate=0.0,
                metadata={"protocol": "grpc", "error": "grpcurl_missing"},
            )

        n = test_case.request_count
        conc = min(test_case.concurrency, n, 10)
        if PolicyType.TRAFFIC_SPLIT in (test_case.policy_types or []):
            conc = min(max(conc, 8), n, 10)

        target_host = test_case.host or test_case.source_service
        port = test_case.grpc_port or self._default_port
        endpoint = f"{target_host}:{port}"
        method = resolve_grpc_method(test_case)

        container = self._app_container
        base_inner, _ = build_grpcurl_cmd(test_case, endpoint_override=endpoint)
        wrapped = (
            f"kubectl exec deploy/{self._source_deploy} -n {self._namespace} "
            f"-c {container} -- {base_inner}"
        )

        probe_out, probe_err = self._ssh.run_command(wrapped)
        probe_text = (probe_out or "") + (probe_err or "")
        if "command not found" in probe_text.lower() or "executable file not found" in probe_text.lower():
            print("  [gRPC-MESH] app container has no grpcurl, fallback to istio-proxy (may bypass VS)")
            container = "istio-proxy"
            wrapped = (
                f"kubectl exec deploy/{self._source_deploy} -n {self._namespace} "
                f"-c {container} -- {base_inner}"
            )

        print(f"  [gRPC-MESH] {endpoint}/{method} x{n} via {container}")

        codes: dict = {}
        total_time = 0.0

        def _send():
            s = time.time()
            out, err = self._ssh.run_command(wrapped)
            from istio_Dynamic_Test.internal.traffic.protocols.grpc.status import parse_grpcurl_output

            code, _ok = parse_grpcurl_output(out, err)
            return code, time.time() - s

        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(_send) for _ in range(n)]
            for fut in as_completed(futures):
                try:
                    code, elapsed = fut.result(timeout=60)
                    codes[code] = codes.get(code, 0) + 1
                    total_time += elapsed
                except Exception:
                    codes["error"] = codes.get("error", 0) + 1

        total = sum(codes.values())
        success = count_success_from_grpc_status_map(codes)
        rate = (success / total * 100) if total > 0 else 0.0
        print(f"  [gRPC-MESH] results: {codes}")
        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes=codes,
            total_requests=total,
            success_rate=rate,
            avg_response_time=total_time / total if total > 0 else 0.0,
            error_count=total - success,
            metadata={"protocol": "grpc", "grpc_method": method, "mesh_endpoint": endpoint},
        )
