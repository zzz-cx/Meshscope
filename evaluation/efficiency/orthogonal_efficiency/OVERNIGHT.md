# Overnight coverage campaign

等当前 `results_cluster` 实验结束后，自动开跑一整晚的多阶段真实集群实验，重点看**覆盖率/故障检出率**在不同配置组合与重复次数下是否稳定。

## 阶段计划

| 阶段 | 内容 |
|------|------|
| phase1 | N=10,20 × C3/C4/C5 × **5 runs**（关键格子稳定性） |
| phase2 | N=5..30 × C1..C5 × **3 runs**（规模×配置覆盖率） |
| phase3 | N=15,20 × C4/C5 × bundle=2..6 × **3 runs**（合并强度消融） |
| phase4 | N=10,15 × C4/C5 × **8 runs**（高重复方差） |
| 汇总 | `coverage_campaign_summary.json` + `coverage_report.md` |

## 启动（等当前实验结束）

```bash
cd /root/configPilot/istio_check/evaluation/efficiency/orthogonal_efficiency
chmod +x overnight_coverage_campaign.sh

# 自动等待当前 cluster 实验 PID 结束后开跑
WAIT_PID=18149 nohup ./overnight_coverage_campaign.sh > /tmp/overnight_campaign_stdout.log 2>&1 &

# 或自动探测 run_experiment.py --mode cluster
nohup ./overnight_coverage_campaign.sh > /tmp/overnight_campaign_stdout.log 2>&1 &
```

## 常用环境变量

| 变量 | 含义 |
|------|------|
| `WAIT_PID` | 等待该 PID 结束后再跑 |
| `SKIP_WAIT=1` | 不等待，立刻开始夜间阶段 |
| `DRY_RUN=1` | 只打印计划 |
| `KEEP_NS=1` | 结束不删命名空间 |
| `OUT_ROOT` | 自定义输出目录 |

## 看进度

```bash
# 夜间总日志（OUT_ROOT 以实际目录名为准）
ls -d results_overnight_*
tail -f results_overnight_*/overnight.log

# 当前仍在跑的基线实验
tail -f results_cluster/experiment_cluster.log
```
