"""HttpExecutor —— 发送单次 HTTP 请求。

典型用途：路由匹配验证、正交匹配组合测试。
通过 curl 命令（本地或 SSH）发送请求，解析返回的 HTTP 状态码。
"""

import sys
import time
from typing import Optional

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseExecutor, compose_request_url

_CURL_NULL = "NUL" if sys.platform == "win32" else "/dev/null"


class HttpExecutor(BaseExecutor):
    """单次 HTTP 请求执行器。

    Args:
        ssh_client: SSH 客户端（自动检测本地 / SSH 环境）。
    """

    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()

    def execute(self, test_case: TestCase) -> ExecutionResult:
        # 与 LoadExecutor 一致：Ingress URL 常为 IP:port，须显式 Host 才能匹配 VS；
        # 仅依赖 URL 时 curl 会发送 Host: <ip>，路由/手动 curl 使用 -H "Host: ..." 会不一致。
        header_parts = []
        host_for_header = test_case.host
        if host_for_header == "*" and test_case.source_service:
            host_for_header = test_case.source_service
        if (
            host_for_header
            and host_for_header != "*"
            and "Host" not in (test_case.headers or {})
            and "host" not in (test_case.headers or {})
        ):
            header_parts.append(f'-H "Host: {host_for_header}"')
        for k, v in test_case.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)

        url = compose_request_url(test_case.target_url, test_case.path)
        curl_cmd = (
            f'curl -s -o {_CURL_NULL} -w "%{{http_code}}" '
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
