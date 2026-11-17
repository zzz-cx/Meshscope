"""SplitExecutor —— 经真实入口打 HTTP，再决定能否用响应体观察分流。

响应体/响应头能认出 subset 时直接统计；认不出时只记录入口与样本，
由 Collector 走 Prometheus / Envoy / Jaeger。
"""
from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, TestCase
from istio_Dynamic_Test.internal.traffic.entry import resolve_traffic_entry
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor
from istio_Dynamic_Test.internal.traffic.protocols.http.curl import count_success_from_status_map
from istio_Dynamic_Test.internal.traffic.split_observe import (
    counts_to_percent,
    infer_service,
    infer_subset_from_response,
    version_signal_usable,
)


def _one_request(url: str, headers: Dict[str, str], expected_versions) -> Tuple[str, str, Optional[str], str]:
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", "replace")
            code = str(getattr(resp, "status", None) or resp.getcode() or "200")
            ver = infer_subset_from_response(body, resp.headers, expected_versions)
            return code, ver, infer_service(body), body[:120]
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = str(exc)
        ver = infer_subset_from_response(body, getattr(exc, "headers", None), expected_versions)
        return str(exc.code), ver, infer_service(body), body[:120]
    except (URLError, TimeoutError, OSError) as exc:
        return "error", "unknown", None, str(exc)


class SplitExecutor(BaseExecutor):
    """入口真实流量；有版本信号用 body，否则交给可观测工具。"""

    def __init__(self, ingress_url: Optional[str] = None):
        self._ingress_url = ingress_url or ""

    def execute(self, test_case: TestCase) -> ExecutionResult:
        n = max(int(test_case.request_count or 1), 1)
        conc = min(max(int(test_case.concurrency or 1), 1), n, 20)
        url, headers, reason = resolve_traffic_entry(test_case, self._ingress_url)
        expected = list((test_case.expected_distribution or {}).keys())
        print(f"  [SPLIT] entry={reason} {n} requests conc={conc} -> {url} Host={headers.get('Host') or '-'}")
        if reason == "missing_entry":
            return ExecutionResult(
                case_id=test_case.case_id,
                status_codes={"error": n},
                total_requests=n,
                success_rate=0.0,
                error_count=n,
                metadata={
                    "protocol": "http",
                    "observer": "none",
                    "body_usable": False,
                    "entry_url": url,
                    "entry_reason": reason,
                    "version_counts": {},
                },
            )

        codes: Counter = Counter()
        versions: Counter = Counter()
        services: Counter = Counter()
        samples = []
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=conc) as pool:
            futs = [pool.submit(_one_request, url, headers, expected) for _ in range(n)]
            done = 0
            for fut in as_completed(futs):
                code, ver, svc, snippet = fut.result()
                codes[code] += 1
                versions[ver] += 1
                if svc:
                    services[svc] += 1
                if len(samples) < 8:
                    samples.append({"status": code, "subset": ver, "service": svc, "body": snippet})
                done += 1
                if done % 20 == 0 or done == n:
                    print(f"  [SPLIT] progress: {done}/{n}")

        elapsed = time.time() - t0
        total = sum(codes.values())
        success = count_success_from_status_map(dict(codes))
        percents, observed = counts_to_percent(dict(versions), expected)
        usable = version_signal_usable(dict(versions), expected)
        observer = "http_body" if usable else "http_no_version_signal"
        print(
            f"  [SPLIT] status={dict(codes)} subsets={dict(versions)} "
            f"services={dict(services)} body_usable={usable}"
        )

        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes=dict(codes),
            total_requests=total,
            success_rate=(success / total * 100) if total else 0.0,
            avg_response_time=(elapsed / total) if total else 0.0,
            error_count=total - success,
            metadata={
                "protocol": "http",
                "observer": observer,
                "body_usable": usable,
                "entry_url": url,
                "entry_reason": reason,
                "request_url": url,
                "version_counts": dict(versions),
                "version_percentages": percents,
                "observed_samples": observed,
                "landed_services": dict(services),
                "samples": samples,
            },
        )
