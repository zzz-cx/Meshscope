"""HttpExecutor —— 单次 HTTP 请求（协议层：protocols/http）。"""

import time
from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, TestCase
from istio_Dynamic_Test.internal.traffic.protocols.http.curl import build_status_curl_cmd, is_http_success_code
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor


class HttpExecutor(BaseExecutor):
    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()

    def execute(self, test_case: TestCase) -> ExecutionResult:
        curl_cmd, _url = build_status_curl_cmd(test_case)
        print(f"  [HTTP] {curl_cmd}")
        start = time.time()
        output, error = self._ssh.run_command(curl_cmd)
        elapsed = time.time() - start

        status = output.strip()
        is_success = is_http_success_code(status)
        print(f"  [HTTP] status={status}  time={elapsed:.3f}s")
        if error:
            print(f"  [HTTP] error: {error}")

        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes={status: 1},
            total_requests=1,
            success_rate=100.0 if is_success else 0.0,
            avg_response_time=elapsed,
            error_count=0 if is_success else 1,
            raw_output=output,
            metadata={"protocol": "http"},
        )
