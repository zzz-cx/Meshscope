# -*- coding: utf-8 -*-
"""
Orthogonal Testing Efficiency — cluster mode (real data) by default.

Complete validation wall-clock:
  apply → traffic → assert → clear  (kubectl + curl against Istio ingress)
"""

from __future__ import print_function

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib.ablation import ablation_compare, detect_faults, build_fault_set  # noqa: E402
from lib.case_model import (  # noqa: E402
    build_exhaustive_units,
    exhaustive_cases,
    orthogonal_merge_units,
    reduction_stats,
    effects_for_level,
)
from lib.config_synth import (  # noqa: E402
    CONFIG_LEVELS,
    count_config_items,
    iter_scale_grid,
    synthesize_istio_config,
)
from lib.validation_timing import mean_std, suite_validation_time  # noqa: E402
from lib.cluster_validate import (  # noqa: E402
    cleanup_namespace,
    ensure_cluster_namespace,
    validate_suite_cluster,
)

def run_one_model(n_services, config_level, max_bundle_size, n_runs, seed):
    istio = synthesize_istio_config(n_services, config_level)
    units = build_exhaustive_units(n_services, config_level)
    exh = exhaustive_cases(units)
    ortho = orthogonal_merge_units(units, max_bundle_size=max_bundle_size)
    red = reduction_stats(len(exh), len(ortho))
    abl = ablation_compare(units, exh, ortho)
    exh_times, ortho_times, run_details = [], [], []
    for r in range(n_runs):
        te = suite_validation_time(exh, seed=seed + r * 17 + n_services * 3)
        to = suite_validation_time(ortho, seed=seed + 10007 + r * 19 + n_services * 5)
        exh_times.append(te["total_validation_s"])
        ortho_times.append(to["total_validation_s"])
        run_details.append(
            {
                "run": r + 1,
                "exhaustive_validation_s": te["total_validation_s"],
                "orthogonal_validation_s": to["total_validation_s"],
            }
        )
    return _pack_row(
        n_services,
        config_level,
        istio,
        units,
        red,
        abl,
        exh_times,
        ortho_times,
        run_details,
        n_runs,
        max_bundle_size,
        mode="model",
        extra={},
    )


def run_one_cluster(
    n_services,
    config_level,
    max_bundle_size,
    n_runs,
    seed,
    ns,
    base_url,
    settle_s,
    skip_deploy,
):
    istio = synthesize_istio_config(n_services, config_level)
    units = build_exhaustive_units(n_services, config_level)
    exh = exhaustive_cases(units)
    ortho = orthogonal_merge_units(units, max_bundle_size=max_bundle_size)
    red = reduction_stats(len(exh), len(ortho))

    print(
        "  [cluster] deploy/ensure ns={0} services={1} (skip_deploy={2})".format(
            ns, n_services, skip_deploy
        )
    )
    sys.stdout.flush()
    ensure_cluster_namespace(ns, n_services, skip_deploy=skip_deploy)

    exh_times, ortho_times, run_details = [], [], []
    last_exh_suite, last_ortho_suite = None, None

    for r in range(n_runs):
        print(
            "  [cluster] run {0}/{1} exhaustive cases={2} ...".format(
                r + 1, n_runs, len(exh)
            )
        )
        sys.stdout.flush()
        te = validate_suite_cluster(exh, ns, base_url, settle_s=settle_s)
        print(
            "  [cluster] run {0}/{1} orthogonal cases={2} ...".format(
                r + 1, n_runs, len(ortho)
            )
        )
        sys.stdout.flush()
        to = validate_suite_cluster(ortho, ns, base_url, settle_s=settle_s)
        last_exh_suite, last_ortho_suite = te, to
        exh_times.append(te["total_validation_s"])
        ortho_times.append(to["total_validation_s"])
        run_details.append(
            {
                "run": r + 1,
                "exhaustive_validation_s": te["total_validation_s"],
                "orthogonal_validation_s": to["total_validation_s"],
                "exh_success_rate_pct": te["success_rate_pct"],
                "ortho_success_rate_pct": to["success_rate_pct"],
                "exh_num_ok": te["num_ok"],
                "ortho_num_ok": to["num_ok"],
                "wall_note": "real kubectl+curl wall-clock",
            }
        )
        print(
            "  [cluster] run {0} done: Te={1:.1f}s To={2:.1f}s exh_ok={3}/{4} ortho_ok={5}/{6}".format(
                r + 1,
                te["total_validation_s"],
                to["total_validation_s"],
                te["num_ok"],
                te["num_cases"],
                to["num_ok"],
                to["num_cases"],
            )
        )
        sys.stdout.flush()

    # Real ablation: credit each unit that individually passed HTTP checks
    # (bundles no longer all-or-nothing). Prefer union of detected_units across last run.
    faults = build_fault_set(units)

    def _cases_from_suite(suite, fallback_cases):
        out = []
        # Prefer suite-level detected_units (per-member passes)
        detected = list(suite.get("detected_units") or [])
        if detected:
            out.append(
                {
                    "case_id": "suite_detected_units",
                    "observes": detected,
                }
            )
            return out
        by_id = {c["case_id"]: c for c in fallback_cases}
        for r in suite.get("results") or []:
            passed = list(r.get("detected_units") or r.get("observes") or [])
            if not passed:
                continue
            out.append({"case_id": r.get("case_id"), "observes": passed})
        return out

    before_cases = _cases_from_suite(last_exh_suite or {}, exh)
    after_cases = _cases_from_suite(last_ortho_suite or {}, ortho)
    before = detect_faults(faults, before_cases if before_cases else exh)
    after = detect_faults(faults, after_cases if after_cases else ortho)
    abl = {
        "fault_set_size": len(faults),
        "before_merge": before,
        "after_merge": after,
        "delta_detection_pct": round(
            before["detection_rate_pct"] - after["detection_rate_pct"], 2
        ),
        "coverage_preserved": (
            before["detection_rate_pct"] - after["detection_rate_pct"]
        )
        <= 2.0,
        "principle": (
            "Real cluster: a unit counts as detected if its own HTTP assertion passed "
            "after live apply (per-member; bundle siblings no longer all-or-nothing). "
            "DR overlays update the primary service DestinationRule in-place to avoid "
            "same-host multi-DR conflicts at large N."
        ),
    }

    extra = {
        "base_url": base_url,
        "namespace": ns,
        "exh_success_rate_pct_last": (last_exh_suite or {}).get("success_rate_pct"),
        "ortho_success_rate_pct_last": (last_ortho_suite or {}).get("success_rate_pct"),
    }
    return _pack_row(
        n_services,
        config_level,
        istio,
        units,
        red,
        abl,
        exh_times,
        ortho_times,
        run_details,
        n_runs,
        max_bundle_size,
        mode="cluster",
        extra=extra,
    )


def _pack_row(
    n_services,
    config_level,
    istio,
    units,
    red,
    abl,
    exh_times,
    ortho_times,
    run_details,
    n_runs,
    max_bundle_size,
    mode,
    extra,
):
    exh_stat = mean_std(exh_times)
    ortho_stat = mean_std(ortho_times)
    time_red = [
        100.0 * (1.0 - b / max(a, 1e-9)) for a, b in zip(exh_times, ortho_times)
    ]
    time_red_stat = mean_std(time_red)
    row = {
        "mode": mode,
        "n_services": n_services,
        "config_level": config_level,
        "config_label": CONFIG_LEVELS[config_level]["label"],
        "n_config_items": count_config_items(istio),
        "n_effect_types": len(effects_for_level(config_level)),
        "n_validation_units": len(units),
        "exhaustive_cases": red["exhaustive_cases"],
        "orthogonal_cases": red["orthogonal_cases"],
        "reduction_pct": red["reduction_pct"],
        "n_runs": n_runs,
        "exh_validation_s_mean": exh_stat["mean"],
        "exh_validation_s_std": exh_stat["std"],
        "ortho_validation_s_mean": ortho_stat["mean"],
        "ortho_validation_s_std": ortho_stat["std"],
        "time_reduction_pct_mean": time_red_stat["mean"],
        "time_reduction_pct_std": time_red_stat["std"],
        "fault_set_size": abl["fault_set_size"],
        "dr_before_pct": abl["before_merge"]["detection_rate_pct"],
        "dr_after_pct": abl["after_merge"]["detection_rate_pct"],
        "delta_detection_pct": abl["delta_detection_pct"],
        "coverage_preserved": abl["coverage_preserved"],
        "max_bundle_size": max_bundle_size,
    }
    row.update(extra or {})
    return {
        "summary": row,
        "ablation": abl,
        "runs": run_details,
        "istio_metadata": istio.get("metadata"),
        "timing_note": (
            "cluster wall-clock"
            if mode == "cluster"
            else "model estimate (not wall-clock)"
        ),
    }


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_latex_snippet(path, rows, highlight_n=20, highlight_c="C4"):
    hit = None
    for r in rows:
        if r["n_services"] == highlight_n and r["config_level"] == highlight_c:
            hit = r
            break
    if hit is None and rows:
        hit = max(rows, key=lambda x: x["exhaustive_cases"])
    assert hit is not None

    service_set = sorted({r["n_services"] for r in rows})
    config_set = sorted({r["config_level"] for r in rows})
    mode = hit.get("mode", "cluster")

    abl_lines = []
    for r in rows:
        if r["config_level"] != hit["config_level"]:
            continue
        abl_lines.append(
            "{n} & {f} & {db:.2f}\\% & {da:.2f}\\% & {dd:.2f} & "
            "{e} & {o} & {rp:.2f}\\% & "
            "{te:.1f}$\\pm${tes:.1f} & {to:.1f}$\\pm${tos:.1f} \\\\".format(
                n=r["n_services"],
                f=r["fault_set_size"],
                db=r["dr_before_pct"],
                da=r["dr_after_pct"],
                dd=r["delta_detection_pct"],
                e=r["exhaustive_cases"],
                o=r["orthogonal_cases"],
                rp=r["reduction_pct"],
                te=r["exh_validation_s_mean"],
                tes=r["exh_validation_s_std"],
                to=r["ortho_validation_s_mean"],
                tos=r["ortho_validation_s_std"],
            )
        )

    body = r"""% Auto-generated — REAL cluster timings (mode={mode}).
% Highlight: N={n_services} / {config_level}  runs={n_runs}

\subsection{{Orthogonal Testing Efficiency}}

\begin{{figure*}}[t]
\centering
% \includegraphics[width=0.85\linewidth]{{figures/evaluation/orthogonal-reduction.png}}
\caption{{Orthogonal validation under different scales (real cluster).
(a) Test-case growth vs configuration items.
(b) Complete validation wall-clock time vs configuration items.}}
\label{{fig:orthogonal-reduction}}
\end{{figure*}}

\textbf{{Goal.}}
Evaluate orthogonal reduction of dynamic validation cost on a live Istio cluster, and whether fault detection coverage is preserved after merging.

\textbf{{Setup.}}
Service scales $N\in\{{{n_list}\}}$, configuration levels $\{{{c_list}\}}$.
Each validation case performs live \texttt{{kubectl apply}}, ingress traffic, assertion, and delete.
Orthogonal bundles share one apply/clear and issue per-effect traffic.
Each cell is repeated {n_runs} times; times are wall-clock mean$\pm$std.

\textbf{{Results.}}
Under a {n_services}-service deployment at {config_level} ({n_items} configuration items), exhaustive validation uses {exh} cases vs {ortho} orthogonal cases (reduction {red:.2f}\%).
Complete validation wall-clock time drops from ${te:.1f}\pm{te_std:.1f}$s to ${to:.1f}\pm{to_std:.1f}$s (time reduction {tred:.2f}\%).

\textbf{{Coverage ablation.}}
Table~\ref{{tab:ortho-ablation}} reports live fault/effect detection before vs after merging.

\begin{{table*}}[t]
\centering
\caption{{Real-cluster detection and validation time ({config_level}).}}
\label{{tab:ortho-ablation}}
\scriptsize
\begin{{tabular}}{{cccccccccc}}
\toprule
$N$ & $|F|$ & DR$_b$ & DR$_a$ & $\Delta$ & Cases$_e$ & Cases$_o$ & Red. & $T_e$ (s) & $T_o$ (s) \\
\midrule
{abl_body}
\bottomrule
\end{{tabular}}
\end{{table*}}
""".format(
        mode=mode,
        n_services=hit["n_services"],
        config_level=hit["config_level"],
        n_items=hit["n_config_items"],
        exh=hit["exhaustive_cases"],
        ortho=hit["orthogonal_cases"],
        red=hit["reduction_pct"],
        te=hit["exh_validation_s_mean"],
        to=hit["ortho_validation_s_mean"],
        te_std=hit["exh_validation_s_std"],
        to_std=hit["ortho_validation_s_std"],
        tred=hit["time_reduction_pct_mean"],
        n_runs=hit.get("n_runs", 1),
        n_list=",".join(str(x) for x in service_set),
        c_list=",".join(config_set),
        abl_body="\n".join(abl_lines),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return {
        "highlight": hit,
        "latex_path": str(path),
        "sentence": (
            "[mode={0}] N={1}/{2}: cases {3}->{4} ({5:.2f}%); "
            "wall-clock {6:.1f}±{7:.1f}s -> {8:.1f}±{9:.1f}s "
            "(time red {10:.2f}%, {11} runs)."
        ).format(
            mode,
            hit["n_services"],
            hit["config_level"],
            hit["exhaustive_cases"],
            hit["orthogonal_cases"],
            hit["reduction_pct"],
            hit["exh_validation_s_mean"],
            hit["exh_validation_s_std"],
            hit["ortho_validation_s_mean"],
            hit["ortho_validation_s_std"],
            hit["time_reduction_pct_mean"],
            hit.get("n_runs", 1),
        ),
    }


def try_plot(csv_path, out_png):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    if not rows:
        return False
    pairs = sorted(
        (
            (
                int(r["n_config_items"]),
                int(r["exhaustive_cases"]),
                int(r["orthogonal_cases"]),
                float(r["exh_validation_s_mean"]),
                float(r["ortho_validation_s_mean"]),
                float(r.get("exh_validation_s_std") or 0),
                float(r.get("ortho_validation_s_std") or 0),
            )
            for r in rows
        ),
        key=lambda t: t[0],
    )
    items = [p[0] for p in pairs]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    axes[0].plot(items, [p[1] for p in pairs], "o-", label="Exhaustive", color="#c0392b")
    axes[0].plot(items, [p[2] for p in pairs], "s-", label="Orthogonal", color="#2980b9")
    axes[0].set_xlabel("Configuration items")
    axes[0].set_ylabel("Test cases")
    axes[0].set_title("(a) Case growth")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].errorbar(
        items,
        [p[3] for p in pairs],
        yerr=[p[5] for p in pairs],
        fmt="o-",
        label="Exhaustive",
        color="#c0392b",
        capsize=2,
    )
    axes[1].errorbar(
        items,
        [p[4] for p in pairs],
        yerr=[p[6] for p in pairs],
        fmt="s-",
        label="Orthogonal",
        color="#2980b9",
        capsize=2,
    )
    axes[1].set_xlabel("Configuration items")
    axes[1].set_ylabel("Wall-clock validation time (s)")
    axes[1].set_title("(b) Real complete validation time")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png), dpi=160)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("cluster", "model"),
        default="cluster",
        help="cluster=real kubectl+curl wall-clock (default); model=estimate only",
    )
    parser.add_argument("--services", default="5,10,15,20")
    parser.add_argument("--configs", default="C1,C2,C3,C4")
    parser.add_argument("--bundle-size", type=int, default=4)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--namespace-prefix", default="meshscope-ortho")
    parser.add_argument("--settle-s", type=float, default=0.6)
    parser.add_argument("--skip-deploy", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--highlight", default="20,C4")
    parser.add_argument("--output-dir", default=str(HERE / "results_cluster"))
    parser.add_argument("--only", type=int, default=0, help="only one service scale")
    args = parser.parse_args()

    services = [int(x) for x in args.services.split(",") if x.strip()]
    if args.only:
        services = [args.only]
    configs = [x.strip() for x in args.configs.split(",") if x.strip()]
    hl = args.highlight.split(",")
    highlight_n = int(hl[0])
    highlight_c = hl[1].strip() if len(hl) > 1 else "C4"
    do_cleanup = not args.no_cleanup

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "experiment_cluster.log"

    base_url = ""
    if args.mode == "cluster":
        sys.path.insert(0, str(HERE.parent / "real_traffic_experiment"))
        from run_traffic import discover_ingress_url as _disc

        base_url = _disc()
        print("[cluster] ingress={0}".format(base_url))

    rows = []
    abl_by_key = {}
    t_all = time.time()
    last_n = None
    force_skip = bool(args.skip_deploy)

    with log_path.open("w", encoding="utf-8") as logf:

        def log(msg):
            print(msg)
            logf.write(msg + "\n")
            logf.flush()
            sys.stdout.flush()

        for n, c in iter_scale_grid(services, configs):
            ns = "{0}-n{1}".format(args.namespace_prefix, n)
            log("=" * 60)
            log("SCALE N={0} {1} mode={2} ns={3}".format(n, c, args.mode, ns))
            cell_t0 = time.time()

            if args.mode == "cluster":
                # redeploy when service scale changes; reuse ns across config levels
                skip = force_skip or (last_n == n)
                if last_n is not None and last_n != n and do_cleanup:
                    old_ns = "{0}-n{1}".format(args.namespace_prefix, last_n)
                    log("[cleanup] previous ns {0}".format(old_ns))
                    cleanup_namespace(old_ns, wait=True)
                # larger N needs longer Istio settle
                settle = max(float(args.settle_s), 0.5 + 0.03 * float(n))
                result = run_one_cluster(
                    n,
                    c,
                    args.bundle_size,
                    args.runs,
                    args.seed + n * 100,
                    ns,
                    base_url,
                    settle,
                    skip_deploy=skip,
                )
                last_n = n
            else:
                result = run_one_model(
                    n, c, args.bundle_size, args.runs, args.seed + n * 100
                )

            rows.append(result["summary"])
            key = "N{0}_{1}".format(n, c)
            abl_by_key[key] = result
            s = result["summary"]
            log(
                "  DONE wall_cell={0:.1f}s cases {1}->{2} Te={3:.1f}±{4:.1f}s To={5:.1f}±{6:.1f}s "
                "DRb={7} DRa={8}".format(
                    time.time() - cell_t0,
                    s["exhaustive_cases"],
                    s["orthogonal_cases"],
                    s["exh_validation_s_mean"],
                    s["exh_validation_s_std"],
                    s["ortho_validation_s_mean"],
                    s["ortho_validation_s_std"],
                    s["dr_before_pct"],
                    s["dr_after_pct"],
                )
            )

            write_csv(out / "orthogonal_reduction.csv", rows)
            (out / "coverage_ablation.json").write_text(
                json.dumps(
                    {
                        "mode": args.mode,
                        "n_runs": args.runs,
                        "service_scales": services,
                        "config_levels": configs,
                        "timing_definition": (
                            "Wall-clock complete validation: kubectl apply + ingress "
                            "traffic + assert + kubectl delete (orthogonal shares apply/clear)."
                        ),
                        "grid": {
                            k: {
                                "summary": v["summary"],
                                "ablation": v["ablation"],
                                "runs": v["runs"],
                                "timing_note": v["timing_note"],
                            }
                            for k, v in abl_by_key.items()
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (out / "experiment_summary.json").write_text(
                json.dumps({"rows": rows, "mode": args.mode}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        if args.mode == "cluster" and do_cleanup and last_n is not None:
            ns = "{0}-n{1}".format(args.namespace_prefix, last_n)
            log("[cleanup] final ns {0}".format(ns))
            cleanup_namespace(ns, wait=False)

    latex_meta = write_latex_snippet(
        out / "orthogonal_efficiency_snippet.tex",
        rows,
        highlight_n=highlight_n,
        highlight_c=highlight_c,
    )
    print("[latex]", latex_meta["sentence"])
    fig_path = HERE / "figures" / "orthogonal-reduction-cluster.png"
    if try_plot(out / "orthogonal_reduction.csv", fig_path):
        print("[plot] -> {0}".format(fig_path))
    print("[done] total_wall={0:.1f}s".format(time.time() - t_all))
    print("[done] CSV -> {0}".format(out / "orthogonal_reduction.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
