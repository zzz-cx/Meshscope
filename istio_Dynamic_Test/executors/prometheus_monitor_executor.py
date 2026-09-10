"""PrometheusMonitorExecutor —— 持续 curl + Prometheus 增量验证的流量执行器。

通过入口 URL 持续发起请求，按 Prometheus 增量验证流量分布，
与 TrafficSplitValidator 逻辑对齐。支持并行 curl 压缩时间。

用法（CLI）: python -m istio_Dynamic_Test.executors.prometheus_monitor_executor \\
      --ingress-url URL --prom-url URL --expected v1:0.5,v2:0.5 --duration 12
"""

import math
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, Optional

import requests

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase

from .base import BaseExecutor

_stop_curl = threading.Event()


def _run_curl_loop(ingress_url: str, interval: float) -> None:
    """后台持续 curl"""
    while not _stop_curl.is_set():
        try:
            subprocess.run(
                ["curl", "-s", "-o", "/dev/null", ingress_url],
                timeout=10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        time.sleep(interval)


def _query_prometheus(
    prom_url: str,
    service: str,
    namespace: str,
) -> dict:
    """查询目标服务各版本请求数"""
    svc_fqdn = f"{service}.{namespace}.svc.cluster.local"
    q = f'sum(istio_requests_total{{destination_service="{svc_fqdn}"}}) by (destination_version)'
    try:
        r = requests.get(f"{prom_url}/api/v1/query", params={"query": q}, timeout=5)
        d = r.json()
        if d.get("status") != "success":
            return {}
        by_ver = {}
        for x in d.get("data", {}).get("result", []):
            ver = x.get("metric", {}).get("destination_version", "unknown")
            val = int(float(x.get("value", [0, 0])[1]))
            by_ver[ver] = by_ver.get(ver, 0) + val
        return by_ver
    except Exception as e:
        return {"_error": str(e)}


def _effective_margin(expected: Dict[str, float], n: int, base: float) -> float:
    """基于二项分布 95% 置信区间的动态容错"""
    if n <= 0:
        return base
    margins = []
    for p in expected.values():
        p = max(0.0, min(1.0, float(p)))
        se = math.sqrt(p * (1.0 - p) / n)
        margins.append(1.96 * se)
    dynamic = max(margins) + 0.01 if margins else 0.0
    return max(base, dynamic)


def run_monitor(
    ingress_url: str,
    prom_url: str,
    expected_dist: Dict[str, float],
    service: str = "reviews",
    namespace: str = "default",
    duration: float = 12.0,
    curl_interval: float = 0.2,
    monitor_interval: float = 1.0,
    parallel: int = 4,
    verbose: bool = True,
) -> Dict:
    """
    运行持续 curl + Prometheus 增量验证。

    Returns:
        {"passed": bool, "pass_count": int, "total_count": int}
    """
    _stop_curl.clear()
    pass_count = 0
    total_count = 0

    if verbose:
        print("=== 持续 curl + Prometheus 监控（按增量验证）===")
        print(f"  curl: {ingress_url} (间隔 {curl_interval}s × {parallel} 并行)")
        print(f"  Prometheus: {prom_url} (查询间隔 {monitor_interval}s)")
        if expected_dist:
            print(f"  期望分布: {expected_dist}")
        print(f"  运行时长: {duration}s\n")

    init = _query_prometheus(prom_url, service, namespace)
    if init and verbose:
        total = sum(v for k, v in init.items() if not k.startswith("_"))
        print(f"初始计数(基准): {init} (总计: {total})\n")

    for _ in range(parallel):
        t = threading.Thread(
            target=_run_curl_loop,
            args=(ingress_url, curl_interval),
            daemon=True,
        )
        t.start()

    try:
        last = init or {}
        start_time = time.time()
        while (time.time() - start_time) < duration:
            time.sleep(monitor_interval)
            by_ver = _query_prometheus(prom_url, service, namespace)
            if "_error" in by_ver:
                if verbose:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 查询失败: {by_ver['_error']}")
                continue
            delta = {
                k: by_ver.get(k, 0) - last.get(k, 0)
                for k in set(by_ver) | set(last)
                if not k.startswith("_")
            }
            delta_total = sum(delta.values())
            last = by_ver

            if delta_total == 0:
                continue

            delta_pct = {k: v / delta_total for k, v in delta.items()}

            if expected_dist:
                base_margin = 0.15
                margin = _effective_margin(expected_dist, delta_total, base_margin) + 0.05
                all_pass = True
                for v, exp in expected_dist.items():
                    pct = delta_pct.get(v, 0.0)
                    if abs(pct - exp) > margin:
                        all_pass = False
                        break
                total_count += 1
                if all_pass:
                    pass_count += 1
                if verbose:
                    parts = [
                        f"{v}: +{delta.get(v,0)} ({delta_pct.get(v,0):.1%})"
                        for v in sorted(delta.keys()) if not v.startswith("_")
                    ]
                    status = "✓ 通过" if all_pass else "✗ 未通过"
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] 增量={delta_total} 容错±{margin:.1%} {status} | {' | '.join(parts)}")
    finally:
        _stop_curl.set()

    majority_pass = total_count > 0 and (pass_count / total_count) >= 0.5
    if verbose and expected_dist:
        print(f"FINAL:{'PASS' if majority_pass else 'FAIL'}")

    return {
        "passed": majority_pass,
        "pass_count": pass_count,
        "total_count": total_count,
    }


class PrometheusMonitorExecutor(BaseExecutor):
    """持续 curl + Prometheus 增量验证的流量执行器。"""

    def __init__(
        self,
        ingress_url: str,
        prometheus_url: str,
        namespace: str = "default",
        duration: float = 12.0,
        parallel: int = 4,
    ):
        self._ingress_url = ingress_url
        self._prometheus_url = prometheus_url
        self._namespace = namespace
        self._duration = duration
        self._parallel = parallel

    def execute(self, test_case: TestCase) -> ExecutionResult:
        service = test_case.host or test_case.source_service or "reviews"
        expected = test_case.expected_distribution or {}

        result = run_monitor(
            ingress_url=self._ingress_url,
            prom_url=self._prometheus_url,
            expected_dist=expected,
            service=service,
            namespace=self._namespace,
            duration=self._duration,
            parallel=self._parallel,
            verbose=True,
        )

        passed = result["passed"]
        total = result["total_count"]
        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes={"200": total} if passed else {},
            total_requests=total,
            success_rate=100.0 if passed else 0.0,
            avg_response_time=0.0,
            error_count=0 if passed else total,
            metadata={
                "prometheus_monitor": True,
                "passed": passed,
                "duration_seconds": self._duration,
            },
        )


def _parse_expected(s: str) -> Dict[str, float]:
    """解析 --expected v1:0.5,v2:0.5 为 {v1: 0.5, v2: 0.5}"""
    out = {}
    for part in s.strip().split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                out[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return out


def main() -> None:
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="持续 curl + Prometheus 监控（按增量验证）")
    parser.add_argument("--prom-url", required=True, help="Prometheus URL")
    parser.add_argument("--ingress-url", required=True, help="入口 URL")
    parser.add_argument("--expected", default="", help="期望分布，如 v1:0.5,v2:0.5")
    parser.add_argument("--duration", type=float, default=12, help="运行时长(秒)")
    parser.add_argument("--service", default="reviews", help="目标服务名")
    parser.add_argument("--namespace", default="default", help="K8s 命名空间")
    parser.add_argument("--parallel", type=int, default=4, help="并行 curl 线程数")
    parser.add_argument("--curl-interval", type=float, default=0.2, help="curl 间隔(秒)")
    parser.add_argument("--monitor-interval", type=float, default=1.0, help="Prometheus 查询间隔(秒)")
    args = parser.parse_args()

    expected_dist = _parse_expected(args.expected) if args.expected else {}

    run_monitor(
        ingress_url=args.ingress_url,
        prom_url=args.prom_url,
        expected_dist=expected_dist,
        service=args.service,
        namespace=args.namespace,
        duration=args.duration,
        curl_interval=args.curl_interval,
        monitor_interval=args.monitor_interval,
        parallel=args.parallel,
        verbose=True,
    )


if __name__ == "__main__":
    main()
