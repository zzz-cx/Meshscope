"""hey 负载工具输出解析。"""

import re

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult
from istio_Dynamic_Test.internal.traffic.protocols.http.curl import count_success_from_status_map


def parse_hey_output(case_id: str, output: str) -> ExecutionResult:
    status_codes: dict[str, int] = {}
    total = 0
    avg_time = 0.0
    in_status = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Status code distribution:"):
            in_status = True
            continue
        if in_status:
            if not stripped:
                in_status = False
                continue
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
    success = count_success_from_status_map(status_codes)
    rate = (success / total * 100) if total > 0 else 0.0
    return ExecutionResult(
        case_id=case_id,
        status_codes=status_codes,
        total_requests=total,
        success_rate=rate,
        avg_response_time=avg_time,
        error_count=total - success,
        raw_output=output,
        metadata={"protocol": "http"},
    )
