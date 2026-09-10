"""LoadExecutor —— HTTP 负载（hey 或批量 curl）。"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, PolicyType, TestCase
from istio_Dynamic_Test.internal.traffic.protocols.http.curl import build_status_curl_cmd, count_success_from_status_map
from istio_Dynamic_Test.internal.traffic.protocols.http.headers import build_curl_header_args
from istio_Dynamic_Test.internal.traffic.protocols.http.hey import parse_hey_output
from istio_Dynamic_Test.internal.traffic.protocols.http.url import compose_request_url
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor


class LoadExecutor(BaseExecutor):
    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()
        self._hey_available: Optional[bool] = None

    def execute(self, test_case: TestCase) -> ExecutionResult:
        if self._check_hey():
            return self._execute_hey(test_case)
        return self._execute_curl_batch(test_case)

    def _check_hey(self) -> bool:
        if self._hey_available is not None:
            return self._hey_available
        out, err = self._ssh.run_command("hey --help 2>&1 || hey 2>&1")
        combined = (out or "") + (err or "")
        self._hey_available = (
            "Usage:" in combined
            and "not found" not in combined.lower()
            and "not recognized" not in combined.lower()
        )
        if not self._hey_available:
            print("  [LOAD] hey not found, fallback to batch curl")
        return self._hey_available

    def _execute_hey(self, tc: TestCase) -> ExecutionResult:
        header_str = build_curl_header_args(tc)
        url = compose_request_url(tc.target_url, tc.path or "")
        extra = ""
        if tc.policy_types and (
            PolicyType.CIRCUIT_BREAKER in tc.policy_types
            or PolicyType.CONNECTION_POOL in tc.policy_types
            or PolicyType.RATE_LIMIT in tc.policy_types
        ):
            extra = " -disable-keepalive"
        n = max(int(tc.request_count or 1), 1)
        c = max(int(tc.concurrency or 1), 1)
        if n < c:
            n = c
        hey_cmd = f'timeout 40 hey -n {n} -c {c}{extra} {header_str} "{url}"'
        print(f"  [LOAD] {hey_cmd}")
        output, error = self._ssh.run_command(hey_cmd)
        if error:
            print(f"  [LOAD] error: {error}")
        return parse_hey_output(tc.case_id, output)

    def _execute_curl_batch(self, tc: TestCase) -> ExecutionResult:
        n = tc.request_count
        conc = min(tc.concurrency, n, 10)
        curl_cmd, _ = build_status_curl_cmd(tc)
        print(f"  [LOAD] batch curl x{n} (concurrency={conc})")
        codes: dict[str, int] = {}
        total_time = 0.0

        def _send():
            s = time.time()
            out, _ = self._ssh.run_command(curl_cmd)
            return out.strip(), time.time() - s

        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(_send) for _ in range(n)]
            for fut in as_completed(futures):
                try:
                    code, elapsed = fut.result(timeout=30)
                    codes[code] = codes.get(code, 0) + 1
                    total_time += elapsed
                except Exception:
                    codes["error"] = codes.get("error", 0) + 1

        total = sum(codes.values())
        success = count_success_from_status_map(codes)
        rate = (success / total * 100) if total > 0 else 0.0
        print(f"  [LOAD] results: {codes}")
        return ExecutionResult(
            case_id=tc.case_id,
            status_codes=codes,
            total_requests=total,
            success_rate=rate,
            avg_response_time=total_time / total if total > 0 else 0.0,
            error_count=total - success,
            metadata={"protocol": "http"},
        )
