"""HttpExecutor —— 发送单次 HTTP 请求。

典型用途：路由匹配验证、正交匹配组合测试。
通过 curl 命令（本地或 SSH）发送请求，解析返回的 HTTP 状态码。
"""

from __future__ import annotations

import time
from typing import Optional

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseExecutor


class HttpExecutor(BaseExecutor):
    """单次 HTTP 请求执行器。

    Args:
        ssh_client: SSH 客户端（自动检测本地 / SSH 环境）。
    """

    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()

    def execute(self, test_case: TestCase) -> ExecutionResult:
        header_parts = []
        for k, v in test_case.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)

        url = f"{test_case.target_url}{test_case.path}"
        curl_cmd = (
            f'curl.exe -s -o NUL -w "%{{http_code}}" '
            f"{header_str} \"{url}\""
        )

        print(f"  [HTTP] {curl_cmd}")
        start = time.time()
        output, error = self._ssh.run_command(curl_cmd)
        elapsed = time.time() - start

        status = output.strip()
        is_success = status.startswith("2")

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
        )
