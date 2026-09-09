#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实流量实验主编排：
  服务规模 N ∈ {10,20,30,40,50}
  功能配置数随 N 递增（默认 features = N）
  对比 exhaustive（覆盖全部功能分支） vs orthogonal
"""


import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from deploy_services import deploy, wait_ready  # noqa: E402
from inject_features import FeatureInjector  # noqa: E402
from generate_cases import (  # noqa: E402
    coverage_stats,
    generate_exhaustive,
    generate_orthogonal,
)
from run_traffic import execute_suite  # noqa: E402


def run_one_scale(
    ns: str,
    n_services: int,
    n_features: int,
    out_root: Path,
    seed: int,
    skip_deploy: bool,
    base_url: str,
) -> dict:
    scale_dir = out_root / "N{0}_F{1}".format(n_services, n_features)
    scale_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if not skip_deploy:
        manifest = scale_dir / "services.yaml"
        deploy(ns, n_services, manifest)
        wait_ready(ns, n_services, timeout_sec=900)

    # 功能注入（增量：同 ns 内按目标数量补齐）
    inj = FeatureInjector(ns, n_services, seed=seed)
    # 若已有功能，先读目录；本实验每个规模用独立 ns 更干净
    inj.ensure_feature_count(n_features)
    catalog_path = scale_dir / "feature_catalog.json"
    inj.export_catalog(catalog_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    exh = generate_exhaustive(catalog)
    ortho = generate_orthogonal(catalog)
    exh_stats = coverage_stats(exh, catalog)
    ortho_stats = coverage_stats(ortho, catalog)

    cases_dir = scale_dir / "cases"
    cases_dir.mkdir(exist_ok=True)
    exh_file = cases_dir / "exhaustive_cases.json"
    ortho_file = cases_dir / "orthogonal_cases.json"
    exh_file.write_text(
        json.dumps({"cases": exh, "stats": exh_stats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    ortho_file.write_text(
        json.dumps({"cases": ortho, "stats": ortho_stats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("[run] executing exhaustive traffic ({0} cases)...".format(len(exh)))
    exh_result = execute_suite(exh_file, base_url or None, workers=8)
    (scale_dir / "traffic_exhaustive.json").write_text(
        json.dumps(exh_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("[run] executing orthogonal traffic ({0} cases)...".format(len(ortho)))
    ortho_result = execute_suite(ortho_file, base_url or None, workers=8)
    (scale_dir / "traffic_orthogonal.json").write_text(
        json.dumps(ortho_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    summary = {
        "namespace": ns,
        "n_services": n_services,
        "n_features": n_features,
        "generation": {"exhaustive": exh_stats, "orthogonal": ortho_stats},
        "traffic": {
            "exhaustive": {k: exh_result[k] for k in exh_result if k != "results"},
            "orthogonal": {k: ortho_result[k] for k in ortho_result if k != "results"},
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
    (scale_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="正交 vs 穷举真实流量实验")
    parser.add_argument(
        "--scales",
        default="10,20,30,40,50",
        help="服务规模阶梯，逗号分隔",
    )
    parser.add_argument(
        "--feature-factor",
        type=float,
        default=1.0,
        help="功能数 = ceil(N * factor)，默认 1.0（与服务数相同）",
    )
    parser.add_argument("--namespace-prefix", default="meshscope-exp")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default=str(HERE / "results" / "runs"))
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--base-url", default="")
    parser.add_argument(
        "--only",
        type=int,
        default=0,
        help="只跑某一个规模（如 10），用于冒烟",
    )
    args = parser.parse_args()

    scales = [int(x) for x in args.scales.split(",") if x.strip()]
    if args.only:
        scales = [args.only]

    out_root = Path(args.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    all_summaries = []

    for n in scales:
        n_features = max(1, int(round(n * args.feature_factor)))
        # 每个规模独立命名空间，避免配置互相污染
        ns = "{0}-n{1}".format(args.namespace_prefix, n)
        print("=" * 60)
        print("SCALE N={0} features={1} ns={2}".format(n, n_features, ns))
        print("=" * 60)
        # 释放资源：删除其它规模的实验命名空间（保留当前）
        if not args.skip_deploy:
            try:
                from deploy_services import kubectl as _kubectl, wait_namespace_gone

                out = _kubectl(["get", "ns", "-o", "jsonpath={.items[*].metadata.name}"])
                for name in out.split():
                    if name.startswith(args.namespace_prefix + "-n") and name != ns:
                        print("[cleanup] delete ns {0}".format(name))
                        __import__("subprocess").run(
                            ["kubectl", "delete", "ns", name, "--wait=false"],
                            stdout=__import__("subprocess").PIPE,
                            stderr=__import__("subprocess").PIPE,
                            universal_newlines=True,
                        )
                        wait_namespace_gone(name, timeout_sec=600)
            except Exception as exc:
                print("[cleanup] warn: {0}".format(exc))
        summary = run_one_scale(
            ns=ns,
            n_services=n,
            n_features=n_features,
            out_root=out_root,
            seed=args.seed + n,
            skip_deploy=args.skip_deploy,
            base_url=args.base_url,
        )
        all_summaries.append(summary)

    report = {
        "scales": scales,
        "summaries": all_summaries,
        "comparison": [
            {
                "n_services": s["n_services"],
                "n_features": s["n_features"],
                "exh_cases": s["generation"]["exhaustive"]["num_cases"],
                "ortho_cases": s["generation"]["orthogonal"]["num_cases"],
                "exh_branch_cov_gen": s["generation"]["exhaustive"]["coverage_pct"],
                "ortho_branch_cov_gen": s["generation"]["orthogonal"]["coverage_pct"],
                "exh_success": s["traffic"]["exhaustive"]["success_rate_pct"],
                "ortho_success": s["traffic"]["orthogonal"]["success_rate_pct"],
                "exh_runtime_s": s["traffic"]["exhaustive"]["runtime_s"],
                "ortho_runtime_s": s["traffic"]["orthogonal"]["runtime_s"],
                "exh_branch_cov_runtime": s["traffic"]["exhaustive"]["branch_coverage_pct"],
                "ortho_branch_cov_runtime": s["traffic"]["orthogonal"]["branch_coverage_pct"],
            }
            for s in all_summaries
        ],
    }
    report_path = out_root / "comparison_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n[done] comparison report -> {0}".format(report_path))
    print(json.dumps(report["comparison"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
