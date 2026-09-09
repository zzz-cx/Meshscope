#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 Ingress 发送真实 HTTP 流量并统计分支覆盖/成功率。"""


import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def discover_ingress_url() -> str:
    """优先 NodePort HTTP。"""
    proc = subprocess.run(
        [
            "kubectl",
            "-n",
            "istio-system",
            "get",
            "svc",
            "istio-ingressgateway",
            "-o",
            "jsonpath={.spec.ports[?(@.name==\"http2\")].nodePort}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    node_port = (proc.stdout or "").strip()
    if not node_port:
        proc = subprocess.run(
            [
                "kubectl",
                "-n",
                "istio-system",
                "get",
                "svc",
                "istio-ingressgateway",
                "-o",
                "jsonpath={.spec.ports[?(@.port==80)].nodePort}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        node_port = (proc.stdout or "").strip() or "31605"

    # 用本机（master）访问即可，ingress 在集群内
    node_ip = "127.0.0.1"
    # 若本机不是 node，取任一 Ready 节点 InternalIP
    proc = subprocess.run(
        [
            "kubectl",
            "get",
            "nodes",
            "-o",
            "jsonpath={.items[0].status.addresses[?(@.type==\"InternalIP\")].address}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        node_ip = proc.stdout.strip()
    return "http://{0}:{1}".format(node_ip, node_port)


def curl_once(base: str, path: str, headers: Dict[str, str], timeout: int = 5) -> Tuple[int, float, str]:
    url = base.rstrip("/") + path
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}", "--max-time", str(timeout)]
    for k, v in (headers or {}).items():
        cmd.extend(["-H", "{0}: {1}".format(k, v)])
    cmd.append(url)
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    elapsed = time.time() - t0
    out = (proc.stdout or "").strip()
    code = 0
    try:
        code = int(out.split()[0])
    except Exception:
        code = 0
    return code, elapsed, out


def run_case(base: str, case: Dict[str, Any]) -> Dict[str, Any]:
    repeat = max(int(case.get("repeat", 1)), 1)
    statuses = []
    latencies = []
    for _ in range(repeat):
        code, lat, _ = curl_once(base, case.get("path", "/"), case.get("headers") or {})
        statuses.append(code)
        latencies.append(lat)

    expect = case.get("expect_status")
    expect_any = case.get("expect_status_any")
    ok = True
    if expect_any:
        ok = all(s in expect_any for s in statuses) or any(s in expect_any for s in statuses)
    elif expect is not None:
        ok = all(s == expect for s in statuses)

    return {
        "case_id": case["case_id"],
        "method": case.get("method"),
        "feature_id": case.get("feature_id"),
        "feature_type": case.get("feature_type"),
        "branch_id": case.get("branch_id"),
        "path": case.get("path"),
        "repeat": repeat,
        "statuses": statuses,
        "ok": bool(ok),
        "avg_latency_s": round(sum(latencies) / max(len(latencies), 1), 4),
        "covered_branches": case.get("covered_branches", []),
    }


def execute_suite(
    cases_file: Path,
    base_url: Optional[str] = None,
    workers: int = 8,
) -> Dict[str, Any]:
    payload = json.loads(cases_file.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    base = base_url or discover_ingress_url()
    print("[traffic] base_url={0} cases={1}".format(base, len(cases)))

    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(run_case, base, c): c for c in cases}
        for fut in as_completed(futs):
            results.append(fut.result())
    elapsed = time.time() - t0

    covered = set()
    for r in results:
        if r.get("ok"):
            covered.update(r.get("covered_branches") or [])

    gen_stats = payload.get("stats") or {}
    total_branches = gen_stats.get("total_branches")
    if not total_branches:
        # fallback
        all_b = set()
        for c in cases:
            all_b.update(c.get("covered_branches") or [])
        total_branches = len(all_b) or 1

    ok_n = sum(1 for r in results if r.get("ok"))
    summary = {
        "base_url": base,
        "method": cases[0].get("method") if cases else "unknown",
        "num_cases": len(cases),
        "num_ok": ok_n,
        "success_rate_pct": round(100.0 * ok_n / max(len(cases), 1), 2),
        "runtime_s": round(elapsed, 3),
        "branch_coverage_pct": round(100.0 * len(covered) / max(total_branches, 1), 2),
        "covered_branches": len(covered),
        "total_branches": total_branches,
        "results": results,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    summary = execute_suite(Path(args.cases), args.base_url or None, args.workers)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 结果文件可能很大，保留汇总 + 精简 results
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {k: summary[k] for k in summary if k != "results"},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
