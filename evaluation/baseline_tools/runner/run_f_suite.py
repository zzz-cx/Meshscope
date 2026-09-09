#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Run F1--F10 paper suite against paper baselines:
  istioctl (S-Istio-offline), Naive Dyn. (D-Naive), Dyn. Only (D-Ours), Hybrid (H-Ours)

Writes:
  results/F_SUITE_SUMMARY.md
  results/f_suite_metrics_latest.json
  results/paper_effectiveness_snippet.tex  (checkmark table filled from run)
"""
from __future__ import print_function

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters import istioctl_analyze  # noqa: E402
from adapters import dynamic_adapters  # noqa: E402
from adapters import mesh_hybrid  # noqa: E402
from adapters.base import load_yaml_mapping, timed_detect  # noqa: E402
from runner.score import score_method  # noqa: E402

SAMPLES = os.path.join(ROOT, "configs", "samples")
GT_PATH = os.path.join(ROOT, "configs", "ground_truth_f_suite.json")
MAP_PATH = os.path.join(ROOT, "configs", "fault_type_mapping.yaml")
RESULTS = os.path.join(ROOT, "results")

METHODS = [
    ("S-Istio-offline", "istioctl"),
    ("D-Naive", "Naive Dyn."),
    ("D-Ours", "Dyn. Only"),
    ("H-Ours", "Hybrid"),
]

# display order for paper table
F_ORDER = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"]


def list_samples(gt):
    paths = []
    for rel in sorted((gt.get("samples") or {}).keys()):
        p = os.path.join(SAMPLES, rel)
        if os.path.isfile(p):
            paths.append((rel, p))
        else:
            print("[warn] missing: {0}".format(p))
    return paths


def run_method(method, path, mapping, cluster=False):
    if method == "S-Istio-offline":
        return timed_detect(istioctl_analyze.detect, path, mapping, mode="offline")
    if method == "D-Naive":
        return timed_detect(dynamic_adapters.detect_naive, path, mapping, cluster=cluster)
    if method == "D-Ours":
        return timed_detect(dynamic_adapters.detect_ours, path, mapping, cluster=cluster)
    if method == "H-Ours":
        return timed_detect(mesh_hybrid.detect, path, mapping, cluster=cluster)
    raise ValueError(method)


def ding(ok):
    return r"\ding{51}" if ok else r"\ding{55}"


def write_paper_tex(meta_rows, out_path):
    """meta_rows: list of dicts with id,label, detects{method_id: bool}"""
    lines = []
    lines.append("% Auto-generated from F1--F10 baseline run ({0})".format(
        datetime.now().isoformat()))
    lines.append("% Methods: istioctl / Naive Dyn. / Dyn. Only / Hybrid")
    lines.append("")
    lines.append(r"\paragraph{Baselines.}")
    lines.append(r"We compare \system{} against representative single-modality validators on the")
    lines.append(r"same fault suite (F1--F10).")
    lines.append(r"\textbf{istioctl analyze}~\cite{istioctl-analyze} is the production static")
    lines.append(r"analyzer for Istio (reported in offline mode, \texttt{--use-kube=false}).")
    lines.append(r"\textbf{Naive Dyn.} applies the candidate configuration and issues fixed HTTP")
    lines.append(r"probes, flagging only coarse failure signals (e.g., elevated 5xx), without")
    lines.append(r"policy-level assertions.")
    lines.append(r"\textbf{Dyn.\ Only} is an ablation of \system{} that runs intent-driven traffic")
    lines.append(r"validation without static modeling or result fusion; we use it as the dynamic")
    lines.append(r"baseline because no public tool targets Istio traffic-policy semantics at the")
    lines.append(r"same fault granularity.")
    lines.append(r"\textbf{\system{} (Hybrid)} combines static modeling, orthogonal case")
    lines.append(r"generation, and runtime consistency checking.")
    lines.append("")
    lines.append(r"\subsection{Effectiveness and Accuracy}")
    lines.append(r"\label{sec_eval_eff}")
    lines.append("")
    lines.append(r"\begin{table}[t]")
    lines.append(r"\centering")
    lines.append(r"\caption{Per-fault detection of baselines vs.\ hybrid consistency validation")
    lines.append(r"on the F1--F10 suite. \ding{51}: detected; \ding{55}: missed.}")
    lines.append(r"\label{tab:hybrid-effectiveness}")
    lines.append(r"\small")
    lines.append(r"\renewcommand{\arraystretch}{1.1}")
    lines.append(r"\setlength{\tabcolsep}{3.5pt}")
    lines.append(r"\resizebox{0.98\linewidth}{!}{%")
    lines.append(r"\begin{tabular}{l l c c c c}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{ID} & \textbf{Misconfiguration Type} &")
    lines.append(r"  \textbf{istioctl} & \textbf{Naive Dyn.} & \textbf{Dyn.\ Only} & \textbf{Hybrid} \\")
    lines.append(r"\midrule")
    for row in meta_rows:
        d = row["detects"]
        lines.append("{0} & {1} & {2} & {3} & {4} & {5} \\\\".format(
            row["id"], row["label"],
            ding(d["S-Istio-offline"]),
            ding(d["D-Naive"]),
            ding(d["D-Ours"]),
            ding(d["H-Ours"]),
        ))
        lines.append("")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}%")
    lines.append(r"}")
    lines.append(r"\vspace{-5mm}")
    lines.append(r"\end{table}")
    lines.append("")
    lines.append(r"Table~\ref{tab:hybrid-effectiveness} summarizes detection outcomes on ten")
    lines.append(r"representative misconfigurations spanning control-plane reference errors,")
    lines.append(r"cross-resource policy conflicts, and runtime-only enforcement gaps.")

    # narrative driven by actual marks
    istio_hit = [r["id"] for r in meta_rows if r["detects"]["S-Istio-offline"]]
    istio_miss = [r["id"] for r in meta_rows if not r["detects"]["S-Istio-offline"]]
    naive_hit = [r["id"] for r in meta_rows if r["detects"]["D-Naive"]]
    dyn_hit = [r["id"] for r in meta_rows if r["detects"]["D-Ours"]]
    dyn_miss = [r["id"] for r in meta_rows if not r["detects"]["D-Ours"]]
    hyb_hit = [r["id"] for r in meta_rows if r["detects"]["H-Ours"]]

    lines.append(
        r"\texttt{{istioctl analyze}} detects {0} of 10 cases{1}, but misses "
        r"intent-level and load-dependent faults ({2}).".format(
            len(istio_hit),
            (" (" + ", ".join(istio_hit) + ")" if istio_hit else ""),
            ", ".join(istio_miss) if istio_miss else "none",
        ))
    lines.append(
        r"Naive dynamic probing only flags coarse always-fail signals"
        r"{0}.".format(
            (" (" + ", ".join(naive_hit) + ")" if naive_hit else " and therefore contributes little coverage")
        ))
    lines.append(
        r"Dyn.\ Only recovers runtime-exposed faults ({0}) but misses purely static "
        r"conflicts without a distinguishable traffic signature ({1}).".format(
            ", ".join(dyn_hit) if dyn_hit else "none",
            ", ".join(dyn_miss) if dyn_miss else "none",
        ))
    lines.append(
        r"Hybrid validation detects {0}/10 cases by combining static cross-resource "
        r"reasoning with policy-aware runtime checks, confirming that the two modalities "
        r"are complementary and that fusion is necessary for full coverage.".format(len(hyb_hit)))
    lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster", action="store_true")
    args = ap.parse_args()

    mapping = load_yaml_mapping(MAP_PATH)
    with open(GT_PATH, "r") as f:
        gt = json.load(f)
    samples = list_samples(gt)
    print("[f-suite] samples={0} cluster={1}".format(len(samples), args.cluster))

    if not os.path.isdir(RESULTS):
        os.makedirs(RESULTS)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.cluster:
        raw_dir = os.path.join(RESULTS, "raw_f_suite_cluster")
        latest = os.path.join(RESULTS, "f_suite_cluster_metrics_latest.json")
        stamped = os.path.join(RESULTS, "f_suite_cluster_metrics_{0}.json".format(stamp))
        summary_md = os.path.join(RESULTS, "F_SUITE_CLUSTER_SUMMARY.md")
        tex_path = os.path.join(RESULTS, "paper_effectiveness_snippet_cluster.tex")
        tex_main = os.path.join(RESULTS, "paper_effectiveness_snippet.tex")
    else:
        raw_dir = os.path.join(RESULTS, "raw_f_suite")
        latest = os.path.join(RESULTS, "f_suite_metrics_latest.json")
        stamped = os.path.join(RESULTS, "f_suite_metrics_{0}.json".format(stamp))
        summary_md = os.path.join(RESULTS, "F_SUITE_SUMMARY.md")
        tex_path = os.path.join(RESULTS, "paper_effectiveness_snippet.tex")
        tex_main = None

    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)

    method_results = {}
    per_method_rows = {}

    t0 = time.time()
    os.environ.setdefault("BASELINE_INGRESS", "http://192.168.1.69:31605")
    os.environ.setdefault("BASELINE_NAMESPACE", "baseline-bookinfo")
    for method, _label in METHODS:
        per = []
        for rel, path in samples:
            print("  [{0}] {1}".format(method, rel))
            res = run_method(method, path, mapping, cluster=args.cluster)
            per.append(res)
        scored = score_method(per, gt, SAMPLES)
        method_results[method] = scored
        with open(os.path.join(raw_dir, method + ".json"), "w") as f:
            json.dump({"method": method, "results": per, "metrics": scored}, f, indent=2)
            f.write("\n")
        o = scored["overall"]
        print("  -> P={0:.3f} R={1:.3f} F1={2:.3f}".format(o["precision"], o["recall"], o["f1"]))
        per_method_rows[method] = {r["sample"]: r for r in scored["rows"]}

    meta_rows = []
    for fid in F_ORDER:
        sample_key = None
        label = fid
        for k, v in (gt.get("samples") or {}).items():
            if v.get("id") == fid:
                sample_key = k
                label = v.get("label") or fid
                break
        detects = {}
        for method, _ in METHODS:
            row = per_method_rows[method].get(sample_key) or {}
            detects[method] = row.get("label") == "TP"
        meta_rows.append({"id": fid, "label": label, "sample": sample_key, "detects": detects})

    elapsed = time.time() - t0
    payload = {
        "generated_at": datetime.now().isoformat(),
        "elapsed_sec": round(elapsed, 3),
        "cluster": args.cluster,
        "namespace": os.environ.get("BASELINE_NAMESPACE"),
        "ingress": os.environ.get("BASELINE_INGRESS"),
        "checkmark": {
            r["id"]: {
                "label": r["label"],
                "S-Istio-offline": r["detects"]["S-Istio-offline"],
                "D-Naive": r["detects"]["D-Naive"],
                "D-Ours": r["detects"]["D-Ours"],
                "H-Ours": r["detects"]["H-Ours"],
            }
            for r in meta_rows
        },
        "methods": {
            m: {
                "overall": method_results[m]["overall"],
                "stratified_recall": method_results[m]["stratified_recall"],
                "t_detect_avg_sec": method_results[m]["t_detect_avg_sec"],
            }
            for m, _ in METHODS
        },
    }
    for p in (latest, stamped):
        with open(p, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

    md = []
    md.append("# F1--F10 Baseline Suite Results ({0})".format(
        "CLUSTER" if args.cluster else "offline/yaml_oracle"))
    md.append("")
    md.append("Generated: {0}".format(payload["generated_at"]))
    if args.cluster:
        md.append("Namespace: `{0}`".format(payload.get("namespace")))
        md.append("Ingress: `{0}`".format(payload.get("ingress")))
    md.append("")
    md.append("| ID | Type | istioctl | Naive Dyn. | Dyn. Only | Hybrid |")
    md.append("|----|------|----------|------------|-----------|--------|")
    for r in meta_rows:
        d = r["detects"]

        def mark(b):
            return "Y" if b else "N"

        md.append("| {0} | {1} | {2} | {3} | {4} | {5} |".format(
            r["id"], r["label"],
            mark(d["S-Istio-offline"]), mark(d["D-Naive"]),
            mark(d["D-Ours"]), mark(d["H-Ours"])))
    md.append("")
    md.append("## Overall metrics")
    md.append("")
    md.append("| Method | Prec | Rec | F1 | T_avg (s) |")
    md.append("|--------|------|-----|----|-----------|")
    for method, label in METHODS:
        o = method_results[method]["overall"]
        md.append("| {0} | {1:.3f} | {2:.3f} | {3:.3f} | {4:.4f} |".format(
            label, o["precision"], o["recall"], o["f1"],
            method_results[method]["t_detect_avg_sec"]))
    md.append("")
    with open(summary_md, "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))

    write_paper_tex(meta_rows, tex_path)
    if tex_main:
        write_paper_tex(meta_rows, tex_main)
    print("[f-suite] done in {0:.1f}s -> {1} , {2}".format(elapsed, summary_md, tex_path))


if __name__ == "__main__":
    main()
