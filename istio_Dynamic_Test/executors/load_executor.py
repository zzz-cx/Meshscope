"""LoadExecutor —— 负载测试执行器。

优先使用 hey，不可用时自动回退到批量 curl。
典型用途：流量分割验证、熔断触发、连接池压测。
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from .base import BaseExecutor


class LoadExecutor(BaseExecutor):
    """负载测试执行器。

    Args:
        ssh_client: SSH 客户端。
    """

    def __init__(self, ssh_client: Optional[SSHClient] = None):
        self._ssh = ssh_client or SSHClient()
        self._hey_available: Optional[bool] = None

    def execute(self, test_case: TestCase) -> ExecutionResult:
        if self._check_hey():
            return self._execute_hey(test_case)
        return self._execute_curl_batch(test_case)

    # ── hey 模式 ─────────────────────────────────────────────────────────

    def _check_hey(self) -> bool:
        if self._hey_available is not None:
            return self._hey_available
        out, err = self._ssh.run_command("hey -h")
        self._hey_available = "Usage:" in out and "not found" not in err and "not recognized" not in err
        if not self._hey_available:
            print("  [LOAD] hey not found, fallback to batch curl")
        return self._hey_available

    def _execute_hey(self, tc: TestCase) -> ExecutionResult:
        header_parts = []
        for k, v in tc.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)
        url = tc.target_url or ""
        hey_cmd = f'hey -n {tc.request_count} -c {tc.concurrency} {header_str} "{url}"'
        print(f"  [LOAD] {hey_cmd}")
        output, error = self._ssh.run_command(hey_cmd)
        if error:
            print(f"  [LOAD] error: {error}")
        return self._parse_hey_output(tc.case_id, output)

    @staticmethod
    def _parse_hey_output(case_id: str, output: str) -> ExecutionResult:
        status_codes: dict[str, int] = {}
        total = 0
        avg_time = 0.0
        in_status = False
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Status code distribution:"):
                in_status = True
                print("  [LOAD] Status code distribution:")
                continue
            if in_status:
                if not stripped:
                    in_status = False
                    continue
                print(f"    {stripped}")
                m = re.search(r"\[(\d+)\]\s+(\d+)\s+responses", stripped)
                if m:
                    code, count = m.group(1), int(m.group(2))
                    status_codes[code] = count
                    total += count
            if "Average:" in line:
                try:
                    avg_time = float(line.split("Average:")[1].split()[0])
                except (ValueError, IndexError):
                    pass
        success = sum(c for code, c in status_codes.items() if code.startswith("2"))
        rate = (success / total * 100) if total > 0 else 0.0
        return ExecutionResult(
            case_id=case_id, status_codes=status_codes, total_requests=total,
            success_rate=rate, avg_response_time=avg_time, error_count=total - success,
            raw_output=output,
        )

    # ── curl 批量回退模式 ────────────────────────────────────────────────

    def _execute_curl_batch(self, tc: TestCase) -> ExecutionResult:
        n = tc.request_count
        conc = min(tc.concurrency, n, 10)
        header_parts = []
        for k, v in tc.headers.items():
            header_parts.append(f'-H "{k}: {v}"')
        header_str = " ".join(header_parts)
        url = tc.target_url or ""
        curl_cmd = f'curl.exe -s -o NUL -w "%{{http_code}}" {header_str} "{url}"'

        print(f"  [LOAD] batch curl x{n} (concurrency={conc})")
        codes: dict[str, int] = {}
        total_time = 0.0

        def _send():
            s = time.time()
            out, _ = self._ssh.run_command(curl_cmd)
            elapsed = time.time() - s
            return out.strip(), elapsed

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
        success = sum(c for k, c in codes.items() if k.startswith("2"))
        rate = (success / total * 100) if total > 0 else 0.0
        avg_t = total_time / total if total > 0 else 0.0

        print(f"  [LOAD] results: {codes}")
        return ExecutionResult(
            case_id=tc.case_id, status_codes=codes, total_requests=total,
            success_rate=rate, avg_response_time=avg_t, error_count=total - success,
        )
