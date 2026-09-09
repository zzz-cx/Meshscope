#!/usr/bin/env bash
# overnight_coverage_campaign.sh
#
# 等当前 orthogonal_efficiency 集群实验结束后，整晚多轮跑：
#   - 更多配置组合（含 C5、更大 N、不同 bundle）
#   - 多次重复（覆盖率/检出率稳定性）
#   - 汇总覆盖率对比表
#
# 用法:
#   ./overnight_coverage_campaign.sh
#   WAIT_PID=18149 ./overnight_coverage_campaign.sh
#   SKIP_WAIT=1 ./overnight_coverage_campaign.sh          # 不等待，直接开跑
#   DRY_RUN=1 ./overnight_coverage_campaign.sh            # 只打印计划
#
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export KUBECONFIG="${KUBECONFIG:-/root/.kube/config}"
export PYTHONUNBUFFERED=1

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${OUT_ROOT:-$ROOT/results_overnight_${STAMP}}"
LOG="$OUT_ROOT/overnight.log"
SUMMARY="$OUT_ROOT/coverage_campaign_summary.json"
mkdir -p "$OUT_ROOT"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG"
}

run_phase() {
  local name="$1"
  shift
  local phase_dir="$OUT_ROOT/$name"
  mkdir -p "$phase_dir"
  log "======== PHASE $name START: $* ========"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    log "DRY_RUN skip: python3 run_experiment.py $*"
    return 0
  fi
  # 阶段开始前清理 ortho ns，避免命名空间冲突
  for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    case "$ns" in
      meshscope-ortho-n*)
        kubectl delete ns "$ns" --wait=false >/dev/null 2>&1 || true
        ;;
    esac
  done
  sleep 15
  # shellcheck disable=SC2086
  if python3 -u run_experiment.py "$@" --output-dir "$phase_dir" >>"$phase_dir/phase.log" 2>&1; then
    log "PHASE $name OK"
  else
    local rc=$?
    log "PHASE $name FAILED rc=$rc (continue)"
    echo "$name" >>"$OUT_ROOT/failed_phases.txt"
    return "$rc"
  fi
  # 每阶段结束后追加覆盖率摘要
  python3 - <<PY >>"$LOG" 2>&1
import csv
from pathlib import Path
p = Path("$phase_dir") / "orthogonal_reduction.csv"
if not p.exists():
    print("no csv for $name")
else:
    rows = list(csv.DictReader(p.open()))
    print("phase=$name cells=%d" % len(rows))
    for r in rows:
        print("  N=%s %s cases %s->%s red=%s%% DRb=%s DRa=%s delta=%s Te=%.1f To=%.1f" % (
            r.get("n_services"), r.get("config_level"),
            r.get("exhaustive_cases"), r.get("orthogonal_cases"),
            r.get("reduction_pct"),
            r.get("dr_before_pct"), r.get("dr_after_pct"), r.get("delta_detection_pct"),
            float(r.get("exh_validation_s_mean") or 0),
            float(r.get("ortho_validation_s_mean") or 0),
        ))
PY
}

wait_for_current_experiment() {
  if [[ "${SKIP_WAIT:-0}" == "1" ]]; then
    log "SKIP_WAIT=1, not waiting"
    return 0
  fi

  local pid="${WAIT_PID:-}"
  if [[ -z "$pid" ]]; then
    # 自动找正在跑的 cluster 实验
    pid="$(pgrep -f 'run_experiment.py --mode cluster' | head -n1 || true)"
  fi

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    log "等待当前实验结束 PID=$pid ..."
    while kill -0 "$pid" 2>/dev/null; do
      local etime
      etime="$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ' || true)"
      local tail_line
      tail_line="$(tail -n1 "$ROOT/results_cluster/experiment_cluster.log" 2>/dev/null || true)"
      log "still running etime=${etime:-?} | ${tail_line:0:120}"
      sleep 60
    done
    log "PID $pid 已结束"
  else
    log "未发现运行中的 cluster 实验（或 WAIT_PID 无效），直接开始夜间任务"
  fi

  # 再等 log 出现 [done]（若存在）
  local clog="$ROOT/results_cluster/experiment_cluster.log"
  if [[ -f "$clog" ]]; then
    if ! grep -q '\[done\] total_wall' "$clog" 2>/dev/null; then
      log "等待 results_cluster 日志出现 [done]（最多 30 分钟）..."
      local i=0
      while (( i < 30 )); do
        if grep -q '\[done\] total_wall' "$clog" 2>/dev/null; then
          break
        fi
        # 若已无 python 进程也跳出
        if ! pgrep -f 'run_experiment.py --mode cluster' >/dev/null 2>&1; then
          log "无 cluster 进程，继续"
          break
        fi
        sleep 60
        i=$((i + 1))
      done
    fi
    log "当前实验日志末尾:"
    tail -n 15 "$clog" | tee -a "$LOG" || true
  fi
}

aggregate_coverage() {
  log "汇总覆盖率报告 -> $SUMMARY"
  python3 - <<'PY'
import csv, json, glob
from pathlib import Path
import os

out_root = Path(os.environ["OUT_ROOT"])
rows = []
for csv_path in sorted(list(out_root.glob("phase*/orthogonal_reduction.csv"))):
    phase = csv_path.parent.name
    for r in csv.DictReader(csv_path.open()):
        item = dict(r)
        item["phase"] = phase
        rows.append(item)

# also include baseline results_cluster if present
base = Path(os.environ.get("ROOT", ".")) / "results_cluster" / "orthogonal_reduction.csv"
if base.exists():
    for r in csv.DictReader(base.open()):
        item = dict(r)
        item["phase"] = "baseline_results_cluster"
        rows.append(item)

def fnum(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

# coverage-focused table
coverage_rows = []
for r in rows:
    coverage_rows.append({
        "phase": r.get("phase"),
        "n_services": int(r.get("n_services") or 0),
        "config_level": r.get("config_level"),
        "exhaustive_cases": int(float(r.get("exhaustive_cases") or 0)),
        "orthogonal_cases": int(float(r.get("orthogonal_cases") or 0)),
        "reduction_pct": fnum(r.get("reduction_pct")),
        "dr_before_pct": fnum(r.get("dr_before_pct")),
        "dr_after_pct": fnum(r.get("dr_after_pct")),
        "delta_detection_pct": fnum(r.get("delta_detection_pct")),
        "coverage_preserved": str(r.get("coverage_preserved")).lower() in ("1", "true", "yes"),
        "exh_validation_s_mean": fnum(r.get("exh_validation_s_mean")),
        "ortho_validation_s_mean": fnum(r.get("ortho_validation_s_mean")),
        "time_reduction_pct_mean": fnum(r.get("time_reduction_pct_mean")),
        "n_runs": int(float(r.get("n_runs") or 1)),
        "mode": r.get("mode", "cluster"),
    })

# stats
preserved = [x for x in coverage_rows if x["coverage_preserved"]]
delta_ok = [x for x in coverage_rows if abs(x["delta_detection_pct"]) <= 2.0]
report = {
    "n_cells": len(coverage_rows),
    "n_coverage_preserved": len(preserved),
    "n_delta_le_2pct": len(delta_ok),
    "mean_dr_before": round(sum(x["dr_before_pct"] for x in coverage_rows) / max(len(coverage_rows), 1), 3),
    "mean_dr_after": round(sum(x["dr_after_pct"] for x in coverage_rows) / max(len(coverage_rows), 1), 3),
    "mean_delta_detection_pct": round(sum(x["delta_detection_pct"] for x in coverage_rows) / max(len(coverage_rows), 1), 3),
    "mean_case_reduction_pct": round(sum(x["reduction_pct"] for x in coverage_rows) / max(len(coverage_rows), 1), 3),
    "mean_time_reduction_pct": round(sum(x["time_reduction_pct_mean"] for x in coverage_rows) / max(len(coverage_rows), 1), 3),
    "worst_delta": max((x["delta_detection_pct"] for x in coverage_rows), default=0.0),
    "cells": coverage_rows,
}
out = Path(os.environ["SUMMARY"])
out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

# markdown table
md = out_root / "coverage_report.md"
lines = [
    "# Overnight Coverage Campaign Report",
    "",
    "- cells: **%d**" % report["n_cells"],
    "- coverage preserved: **%d**" % report["n_coverage_preserved"],
    "- delta DR <= 2%%: **%d**" % report["n_delta_le_2pct"],
    "- mean DR before/after: **%.2f%% / %.2f%%**" % (report["mean_dr_before"], report["mean_dr_after"]),
    "- mean case reduction: **%.2f%%**" % report["mean_case_reduction_pct"],
    "- mean time reduction: **%.2f%%**" % report["mean_time_reduction_pct"],
    "",
    "| phase | N | Cfg | exh | ortho | red% | DRb | DRa | Δ | Te(s) | To(s) |",
    "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for x in coverage_rows:
    lines.append(
        "| {phase} | {n} | {c} | {e} | {o} | {r:.1f} | {db:.1f} | {da:.1f} | {dd:.2f} | {te:.1f} | {to:.1f} |".format(
            phase=x["phase"], n=x["n_services"], c=x["config_level"],
            e=x["exhaustive_cases"], o=x["orthogonal_cases"], r=x["reduction_pct"],
            db=x["dr_before_pct"], da=x["dr_after_pct"], dd=x["delta_detection_pct"],
            te=x["exh_validation_s_mean"], to=x["ortho_validation_s_mean"],
        )
    )
md.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out)
print("wrote", md)
PY
}

# ---------------- main ----------------
export OUT_ROOT SUMMARY ROOT

log "Overnight coverage campaign start"
log "OUT_ROOT=$OUT_ROOT"
log "KUBECONFIG=$KUBECONFIG"

wait_for_current_experiment

# 清理旧实验 ns，释放资源（忽略失败）
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  log "清理 meshscope-ortho-* / 旧 exp ns（不等待）"
  for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    case "$ns" in
      meshscope-ortho-n*|meshscope-exp-n*)
        log "delete ns $ns"
        kubectl delete ns "$ns" --wait=false >/dev/null 2>&1 || true
        ;;
    esac
  done
  # 等至少一个 ortho ns 消失，避免立刻重建冲突
  sleep 20
fi

# -------- 夜间阶段计划（真实集群）--------
# Phase 1: 关键格子多跑几次，看覆盖率稳定性（C3/C4/C5）
run_phase phase1_stability_keycells \
  --mode cluster \
  --services 10,20 \
  --configs C3,C4,C5 \
  --runs 5 \
  --bundle-size 4 \
  --highlight 20,C5 \
  --no-cleanup

# Phase 2: 扩大服务规模 + 全配置阶梯（覆盖率随规模）
run_phase phase2_scale_coverage \
  --mode cluster \
  --services 5,10,15,20,30 \
  --configs C1,C2,C3,C4,C5 \
  --runs 3 \
  --bundle-size 4 \
  --highlight 30,C5 \
  --no-cleanup

# Phase 3: bundle 大小消融（合并强度 vs 覆盖率）
for b in 2 3 4 5 6; do
  run_phase "phase3_bundle${b}" \
    --mode cluster \
    --services 15,20 \
    --configs C4,C5 \
    --runs 3 \
    --bundle-size "$b" \
    --highlight 20,C5 \
    --no-cleanup
done

# Phase 4: 高密度重复（同一组合跑更多次，方差）
run_phase phase4_high_repeats \
  --mode cluster \
  --services 10,15 \
  --configs C4,C5 \
  --runs 8 \
  --bundle-size 4 \
  --highlight 15,C5 \
  --no-cleanup

aggregate_coverage

# 最终清理
if [[ "${DRY_RUN:-0}" != "1" ]] && [[ "${KEEP_NS:-0}" != "1" ]]; then
  log "最终清理命名空间"
  for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    case "$ns" in
      meshscope-ortho-n*)
        kubectl delete ns "$ns" --wait=false >/dev/null 2>&1 || true
        ;;
    esac
  done
fi

log "Overnight campaign finished"
log "Summary: $SUMMARY"
log "Markdown: $OUT_ROOT/coverage_report.md"
exit 0
