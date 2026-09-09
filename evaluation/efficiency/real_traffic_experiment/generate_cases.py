#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从功能目录生成穷举（全功能分支）与正交用例。"""


import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def load_catalog(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def generate_exhaustive(catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """穷举：覆盖每个功能的每一个功能分支。"""
    cases = []
    for feat in catalog:
        for br in feat.get("branches", []):
            cases.append(
                {
                    "case_id": "exh_f{0}_{1}".format(feat["feature_id"], br["branch_id"]),
                    "method": "exhaustive",
                    "feature_id": feat["feature_id"],
                    "feature_type": feat["feature_type"],
                    "service": feat["service"],
                    "branch_id": br["branch_id"],
                    "path": br.get("path", "/"),
                    "headers": br.get("headers", {}),
                    "repeat": int(br.get("repeat", 1)),
                    "expect_status": br.get("expect_status"),
                    "expect_status_any": br.get("expect_status_any"),
                    "expect_subset": br.get("expect_subset"),
                    "covered_branches": [
                        "f{0}:{1}".format(feat["feature_id"], br["branch_id"])
                    ],
                }
            )
    return cases


def generate_orthogonal(catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    正交：按功能类型维度取样。
    维度 = feature_type × branch_role(首个代表分支)
    目标是用更少用例覆盖各功能类型的代表分支。
    """
    # 按类型分组
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for feat in catalog:
        by_type.setdefault(feat["feature_type"], []).append(feat)

    types = sorted(by_type.keys())
    if not types:
        return []

    # 每个类型取一个代表功能；分支取第一个
    representatives = []
    for t in types:
        feat = by_type[t][0]
        branches = feat.get("branches") or [{}]
        representatives.append((feat, branches[0]))

    # 若只有一类，直接返回代表
    cases = []
    # 正交组合：对类型做 pairwise-ish —— 每个类型一条代表 + 跨类型组合一轮
    for feat, br in representatives:
        cases.append(
            {
                "case_id": "ortho_type_{0}_f{1}".format(
                    feat["feature_type"], feat["feature_id"]
                ),
                "method": "orthogonal",
                "feature_id": feat["feature_id"],
                "feature_type": feat["feature_type"],
                "service": feat["service"],
                "branch_id": br.get("branch_id", "default"),
                "path": br.get("path", "/"),
                "headers": br.get("headers", {}),
                "repeat": min(int(br.get("repeat", 1)), 5),
                "expect_status": br.get("expect_status"),
                "expect_status_any": br.get("expect_status_any"),
                "expect_subset": br.get("expect_subset"),
                "covered_branches": [
                    "f{0}:{1}".format(feat["feature_id"], br.get("branch_id", "default"))
                ],
            }
        )

    # 额外：对每个功能只取 1 条“主分支”，形成类型×功能稀疏覆盖（正交压缩）
    # 控制规模：最多取 types 数量 * 2 之外的补充
    extra_budget = max(len(types), len(catalog) // max(len(types), 1))
    added = 0
    for feat in catalog:
        if added >= extra_budget:
            break
        # 跳过已作为类型代表的
        if any(c["feature_id"] == feat["feature_id"] for c in cases):
            continue
        br = (feat.get("branches") or [{}])[0]
        cases.append(
            {
                "case_id": "ortho_sparse_f{0}".format(feat["feature_id"]),
                "method": "orthogonal",
                "feature_id": feat["feature_id"],
                "feature_type": feat["feature_type"],
                "service": feat["service"],
                "branch_id": br.get("branch_id", "default"),
                "path": br.get("path", "/"),
                "headers": br.get("headers", {}),
                "repeat": 1,
                "expect_status": br.get("expect_status", 200),
                "expect_status_any": br.get("expect_status_any"),
                "expect_subset": br.get("expect_subset"),
                "covered_branches": [
                    "f{0}:{1}".format(feat["feature_id"], br.get("branch_id", "default"))
                ],
            }
        )
        added += 1

    return cases


def coverage_stats(cases: List[Dict[str, Any]], catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_branches = set()
    for feat in catalog:
        for br in feat.get("branches", []):
            all_branches.add("f{0}:{1}".format(feat["feature_id"], br["branch_id"]))
    covered = set()
    for c in cases:
        covered.update(c.get("covered_branches", []))
    total = len(all_branches) or 1
    return {
        "total_branches": len(all_branches),
        "covered_branches": len(covered),
        "coverage_pct": round(100.0 * len(covered) / total, 2),
        "num_cases": len(cases),
        "uncovered": sorted(all_branches - covered),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--out-dir", default="results/cases")
    args = parser.parse_args()
    catalog = load_catalog(Path(args.catalog))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    exh = generate_exhaustive(catalog)
    ortho = generate_orthogonal(catalog)
    exh_stats = coverage_stats(exh, catalog)
    ortho_stats = coverage_stats(ortho, catalog)

    (out / "exhaustive_cases.json").write_text(
        json.dumps({"cases": exh, "stats": exh_stats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "orthogonal_cases.json").write_text(
        json.dumps({"cases": ortho, "stats": ortho_stats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = {
        "exhaustive": exh_stats,
        "orthogonal": ortho_stats,
        "case_ratio": round(
            exh_stats["num_cases"] / max(ortho_stats["num_cases"], 1), 2
        ),
    }
    (out / "generation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
