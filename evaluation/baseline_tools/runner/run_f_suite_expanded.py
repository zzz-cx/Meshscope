#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Run F1--F10 against an expanded baseline set and write comparison tables.

Methods (skip unavailable gracefully):
  S-Istio-offline, S-Ours, S-PolicyLite, S-LintBP, S-SchemaCRD,
  S-KubectlDryRun-client, S-KubectlDryRun-server,
  S-Lint (kube-linter), S-Schema (kubeconform), S-Kyverno, S-Checkov,
  D-Ours, H-Ours
"""
from __future__ import print_function

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# prefer local tool binaries
BIN = os.path.join(ROOT, "bin")
if os.path.isdir(BIN):
    os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")

from adapters import istioctl_analyze  # noqa: E402
from adapters import static_ours  # noqa: E402
from adapters import dynamic_adapters  # noqa: E402
from adapters import mesh_hybrid  # noqa: E402
from adapters import extra_baselines  # noqa: E402
from adapters.base import load_yaml_mapping, timed_detect  # noqa: E402
from runner.score import score_method  # noqa: E402

SAMPLES = os.path.join(ROOT, "configs", "samples")
GT_PATH = os.path.join(ROOT, "configs", "ground_truth_f_suite.json")
MAP_PATH = os.path.join(ROOT, "configs", "fault_type_mapping.yaml")
RESULTS = os.path.join(ROOT, "results")

F_ORDER = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"]

# display label, method id
METHODS = [
    ("S-Istio-offline", "istioctl"),
    ("S-Ours", "Static Only"),
    ("S-PolicyLite", "PolicyLite"),
    ("S-LintBP", "LintBP"),
    ("S-SchemaCRD", "SchemaCRD"),
    ("S-KubectlDryRun-client", "kubectl-dry(client)"),
    ("S-KubectlDryRun-server", "kubectl-dry(server)"),
    ("S-Lint", "kube-linter"),
    ("S-Schema", "kubeconform"),
    ("S-Kyverno", "Kyverno"),
    ("S-Checkov", "Checkov"),
    ("D-Ours", "Dyn. Only"),
    ("H-Ours", "Hybrid"),
]


def list_samples(gt):
    paths = []
    for rel in sorted((gt.get("samples") or {}).keys()):
        p = os.path.join(SAMPLES, rel)
        if os.path.isfile(p):
            paths.append((rel, p))
        else:
            print("[warn] missing: {0}".format(p))
    return paths


def run_one(method, path, mapping):
    if method == "S-Istio-offline":
        return timed_detect(istioctl_analyze.detect, path, mapping, mode="offline")
    if method == "S-Ours":
        return timed_detect(static_ours.detect, path, mapping)
    if method == "S-PolicyLite":
        return timed_detect(extra_baselines.detect_policy_lite, path, mapping)
    if method == "S-LintBP":
        return timed_detect(extra_baselines.detect_lint_bp, path, mapping)
    if method == "S-SchemaCRD":
        return timed_detect(extra_baselines.detect_schema_crd, path, mapping)
    if method == "S-KubectlDryRun-client":
        return timed_detect(extra_baselines.detect_kubectl_dryrun, path, mapping, mode="client")
    if method == "S-KubectlDryRun-server":
        return timed_detect(extra_baselines.detect_kubectl_dryrun, path, mapping, mode="server")
    if method == "S-Lint":
        return timed_detect(extra_baselines.detect_kube_linter, path, mapping)
    if method == "S-Schema":
        return timed_detect(extra_baselines.detect_kubeconform, path, mapping)
    if method == "S-Kyverno":
        return timed_detect(extra_baselines.detect_kyverno, path, mapping)
    if method == "S-Checkov":
        return timed_detect(extra_baselines.detect_checkov, path, mapping)
    if method == "D-Ours":
        return timed_detect(dynamic_adapters.detect_ours, path, mapping, cluster=False)
    if method == "H-Ours":
        return timed_detect(mesh_hybrid.detect, path, mapping, cluster=False)
    raise ValueError(method)


def ding(ok):
    return "Y" if ok else "N"


def main():
    mapping = load_yaml_mapping(MAP_PATH)
    with open(GT_PATH, "r") as f:
        gt = json.load(f)
    samples = list_samples(gt)
    print("[expanded] samples={0} methods={1}".format(len(samples), len(METHODS)))

    if not os.path.isdir(RESULTS):
        os.makedirs(RESULTS)
    raw_dir = os.path.join(RESULTS, "raw_f_suite_expanded")
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)

    method_results = {}
    per_method_rows = {}
    availability = {}

    t0 = time.time()
    for method, label in METHODS:
        print("== {0} ({1}) ==".format(label, method))
        per = []
        for rel, path in samples:
            res = run_one(method, path, mapping)
            per.append(res)
        avail = all(r.get("available", True) for r in per)
        n_unavail = sum(1 for r in per if r.get("available") is False)
        availability[method] = {"available": avail and n_unavail == 0, "n_unavailable": n_unavail}
        if n_unavail == len(per):
            print("  SKIP (unavailable): {0}".format(per[0].get("error")))
            scored = score_method(per, gt, SAMPLES)
            method_results[method] = scored
            per_method_rows[method] = {r["sample"]: r for r in scored["rows"]}
        else:
            scored = score_method(per, gt, SAMPLES)
            method_results[method] = scored
            per_method_rows[method] = {r["sample"]: r for r in scored["rows"]}
            o = scored["overall"]
            print("  P={0:.3f} R={1:.3f} F1={2:.3f} avail={3}".format(
                o["precision"], o["recall"], o["f1"], availability[method]["available"]))
        with open(os.path.join(raw_dir, method + ".json"), "w") as f:
            json.dump({"method": method, "results": per, "metrics": scored,
                       "available": availability[method]}, f, indent=2)
            f.write("\n")

    # checkmark table
    meta = []
    for fid in F_ORDER:
        sample_key = label = None
        for k, v in (gt.get("samples") or {}).items():
            if v.get("id") == fid:
                sample_key = k
                label = v.get("label")
                break
        detects = {}
        for method, _ in METHODS:
            row = per_method_rows.get(method, {}).get(sample_key) or {}
            if not availability[method]["available"]:
                detects[method] = None  # unavailable
            else:
                detects[method] = row.get("label") == "TP"
        meta.append({"id": fid, "label": label, "sample": sample_key, "detects": detects})

    # markdown
    cols = METHODS
    lines = []
    lines.append("# F1--F10 Expanded Baseline Comparison")
    lines.append("")
    lines.append("Generated: {0}".format(datetime.now().isoformat()))
    lines.append("")
    header = "| ID | Type | " + " | ".join(lab for _, lab in cols) + " |"
    sep = "|----|------|" + "|".join(["------"] * len(cols)) + "|"
    lines.append(header)
    lines.append(sep)
    for row in meta:
        cells = []
        for method, _ in cols:
            v = row["detects"][method]
            if v is None:
                cells.append("—")
            else:
                cells.append(ding(v))
        lines.append("| {0} | {1} | {2} |".format(row["id"], row["label"], " | ".join(cells)))
    lines.append("")
    lines.append("## Overall metrics")
    lines.append("")
    lines.append("| Method | Available | Prec | Rec | F1 | T_avg (s) |")
    lines.append("|--------|-----------|------|-----|----|-----------|")
    for method, label in cols:
        o = method_results[method]["overall"]
        avail = "yes" if availability[method]["available"] else "NO"
        lines.append("| {0} | {1} | {2:.3f} | {3:.3f} | {4:.3f} | {5:.4f} |".format(
            label, avail, o["precision"], o["recall"], o["f1"],
            method_results[method]["t_detect_avg_sec"]))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `—` = tool unavailable on this host.")
    lines.append("- PolicyLite / LintBP / SchemaCRD are lightweight stand-ins when Gatekeeper/kube-linter schemas are limited.")
    lines.append("- Dyn. Only / Hybrid use yaml_oracle in this expanded offline sweep (cluster live run is separate).")
    lines.append("- Type-matched scoring: wrong fault_type counts as miss/FP_type, not TP.")
    lines.append("")

    md_path = os.path.join(RESULTS, "F_SUITE_EXPANDED_SUMMARY.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

    payload = {
        "generated_at": datetime.now().isoformat(),
        "elapsed_sec": round(time.time() - t0, 3),
        "availability": availability,
        "checkmark": {
            r["id"]: {
                "label": r["label"],
                **{m: r["detects"][m] for m, _ in METHODS},
            }
            for r in meta
        },
        "methods": {
            m: {
                "label": lab,
                "available": availability[m]["available"],
                "overall": method_results[m]["overall"],
                "t_detect_avg_sec": method_results[m]["t_detect_avg_sec"],
            }
            for m, lab in METHODS
        },
    }
    with open(os.path.join(RESULTS, "f_suite_expanded_metrics_latest.json"), "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print("[expanded] done -> {0}".format(md_path))


if __name__ == "__main__":
    main()
