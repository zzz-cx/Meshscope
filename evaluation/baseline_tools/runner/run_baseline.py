#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Baseline experiment runner: S-Istio / S-Ours / S-Lint / S-Schema / D-Naive / D-Ours / H-Ours

Defaults (confirmed):
  - Dynamic baselines: D-Ours + D-Naive (yaml_oracle without --cluster)
  - S-Istio: report both offline and cluster; primary = offline
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters import istioctl_analyze  # noqa: E402
from adapters import kube_tools  # noqa: E402
from adapters import static_ours  # noqa: E402
from adapters import dynamic_adapters  # noqa: E402
from adapters import mesh_hybrid  # noqa: E402
from adapters.base import load_yaml_mapping, timed_detect  # noqa: E402
from runner.score import score_method  # noqa: E402


SAMPLES = os.path.join(ROOT, "configs", "samples")
GT_PATH = os.path.join(ROOT, "configs", "ground_truth.json")
MAP_PATH = os.path.join(ROOT, "configs", "fault_type_mapping.yaml")
RESULTS = os.path.join(ROOT, "results")


def list_samples(gt):
    paths = []
    for rel in sorted((gt.get("samples") or {}).keys()):
        p = os.path.join(SAMPLES, rel)
        if os.path.isfile(p):
            paths.append((rel, p))
        else:
            print("[warn] missing sample file: {0}".format(p))
    return paths


def run_all(methods, cluster=False, istioctl_cluster=False):
    mapping = load_yaml_mapping(MAP_PATH)
    with open(GT_PATH, "r") as f:
        gt = json.load(f)
    samples = list_samples(gt)
    print("[baseline] samples={0} methods={1} cluster={2}".format(
        len(samples), methods, cluster))

    method_results = {}
    raw_dir = os.path.join(RESULTS, "raw")
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)

    for method in methods:
        per = []
        for rel, path in samples:
            print("  [{0}] {1}".format(method, rel))
            if method == "S-Istio-offline":
                res = timed_detect(istioctl_analyze.detect, path, mapping, mode="offline")
            elif method == "S-Istio-cluster":
                res = timed_detect(istioctl_analyze.detect, path, mapping, mode="cluster")
            elif method == "S-Ours":
                res = timed_detect(static_ours.detect, path, mapping)
            elif method == "S-Lint":
                res = timed_detect(kube_tools.detect_kube_linter, path, mapping)
            elif method == "S-Schema":
                res = timed_detect(kube_tools.detect_kubeval, path, mapping)
            elif method == "D-Naive":
                res = timed_detect(
                    dynamic_adapters.detect_naive, path, mapping, cluster=cluster)
            elif method == "D-Ours":
                res = timed_detect(
                    dynamic_adapters.detect_ours, path, mapping, cluster=cluster)
            elif method == "H-Ours":
                res = timed_detect(
                    mesh_hybrid.detect, path, mapping, cluster=cluster)
            else:
                raise ValueError("unknown method {0}".format(method))
            per.append(res)

        scored = score_method(per, gt, SAMPLES)
        method_results[method] = {
            "metrics": scored,
            "available": all(r.get("available", True) for r in per),
            "n_unavailable": sum(1 for r in per if r.get("available") is False),
        }
        with open(os.path.join(raw_dir, method + ".json"), "w") as f:
            json.dump({"method": method, "results": per, "metrics": scored}, f, indent=2)
            f.write("\n")

        o = scored["overall"]
        print("  -> P={0:.3f} R={1:.3f} F1={2:.3f} Tavg={3:.3f}s stratified_R={4}".format(
            o["precision"], o["recall"], o["f1"], scored["t_detect_avg_sec"],
            scored["stratified_recall"]))

    return method_results, gt


def write_summary(method_results, out_path):
    lines = []
    lines.append("# Baseline Tools Results")
    lines.append("")
    lines.append("Generated: {0}".format(datetime.now().isoformat()))
    lines.append("")
    lines.append("## Table A — Overall")
    lines.append("")
    lines.append("| Method | Prec | Rec | F1 | TP/FP/FN/TN | T_detect_avg (s) | Available |")
    lines.append("|--------|------|-----|----|-------------|------------------|-----------|")
    for m, pack in method_results.items():
        met = pack["metrics"]["overall"]
        lines.append("| {0} | {1:.3f} | {2:.3f} | {3:.3f} | {4}/{5}/{6}/{7} | {8:.4f} | {9} |".format(
            m, met["precision"], met["recall"], met["f1"],
            met["tp"], met["fp"], met["fn"], met["tn"],
            pack["metrics"]["t_detect_avg_sec"],
            "yes" if pack.get("available", True) else "NO",
        ))
    lines.append("")
    lines.append("## Table B — Stratified Recall")
    lines.append("")
    lines.append("| Method | L-Static (static_only) | L-Dynamic (dynamic_only) | L-Both | L-Neg (none) |")
    lines.append("|--------|------------------------|--------------------------|--------|--------------|")
    for m, pack in method_results.items():
        sr = pack["metrics"].get("stratified_recall") or {}
        def fmt(k):
            return "{0:.3f}".format(sr[k]) if k in sr else "—"
        lines.append("| {0} | {1} | {2} | {3} | {4} |".format(
            m, fmt("static_only"), fmt("dynamic_only"), fmt("both"), fmt("none")))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Primary static baseline: **S-Istio-offline** (`istioctl analyze --use-kube=false`).")
    lines.append("- S-Istio-cluster reported when kube context is available.")
    lines.append("- D-Naive / D-Ours / H-Ours without `--cluster` use **yaml_oracle** (policy-content runtime signals); with `--cluster` they also apply+curl.")
    lines.append("- S-Ours / H-Ours are ablations of MeshScope, not external competitors.")
    lines.append("- S-Lint / S-Schema skipped gracefully if binaries missing.")
    lines.append("")
    text = "\n".join(lines) + "\n"
    with open(out_path, "w") as f:
        f.write(text)
    print(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--methods",
        default="S-Istio-offline,S-Istio-cluster,S-Ours,S-Lint,S-Schema,D-Naive,D-Ours,H-Ours",
        help="comma-separated method ids",
    )
    ap.add_argument("--cluster", action="store_true",
                    help="enable kubectl apply + ingress probes for dynamic/hybrid")
    ap.add_argument("--static-only", action="store_true",
                    help="only run static methods")
    args = ap.parse_args()

    # ensure GT exists
    build = os.path.join(ROOT, "configs", "build_ground_truth.py")
    if not os.path.isfile(GT_PATH):
        os.system("python {0}".format(build))
    else:
        os.system("python {0}".format(build))

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    if args.static_only:
        methods = [m for m in methods if m.startswith("S-")]

    if not os.path.isdir(RESULTS):
        os.makedirs(RESULTS)

    t0 = time.time()
    method_results, gt = run_all(methods, cluster=args.cluster)
    elapsed = time.time() - t0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_json = os.path.join(RESULTS, "baseline_metrics_{0}.json".format(stamp))
    summary_md = os.path.join(RESULTS, "BASELINE_SUMMARY.md")
    latest_json = os.path.join(RESULTS, "baseline_metrics_latest.json")

    payload = {
        "generated_at": datetime.now().isoformat(),
        "elapsed_sec": round(elapsed, 3),
        "cluster": args.cluster,
        "gt_statistics": gt.get("statistics"),
        "methods": {
            m: {
                "overall": pack["metrics"]["overall"],
                "stratified_recall": pack["metrics"]["stratified_recall"],
                "stratified": pack["metrics"]["stratified"],
                "t_detect_avg_sec": pack["metrics"]["t_detect_avg_sec"],
                "t_detect_sum_sec": pack["metrics"]["t_detect_sum_sec"],
                "available": pack.get("available", True),
            }
            for m, pack in method_results.items()
        },
    }
    with open(summary_json, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    with open(latest_json, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    write_summary(method_results, summary_md)
    print("[baseline] done in {0:.1f}s -> {1}".format(elapsed, summary_md))


if __name__ == "__main__":
    main()
