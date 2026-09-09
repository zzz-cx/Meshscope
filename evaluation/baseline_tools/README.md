# Baseline Tools Experiment

对比 **Istio 原生静态 / 弱静态 / 仅动态 / Hybrid** 在同一 GT 语料上的检出成功率与耗时。

设计见 [`BASELINE_DESIGN.md`](BASELINE_DESIGN.md)。相关工作见 [`RELATED_WORK_PAPER.md`](RELATED_WORK_PAPER.md)。

## 已确认默认

1. **动态主基线**：`D-Ours`（消融）+ `D-Naive`（下界）；暂不挂语义不对齐的外部动态竞品。
2. **S-Istio**：`offline` 与 `cluster` 都跑；论文主报 **offline**。

## 快速跑

```bash
export PATH="/root/configPilot/cluster/istio-1.24.6/bin:/root/configPilot/istio_check/evaluation/baseline_tools/bin:$PATH"
cd /root/configPilot/istio_check/evaluation/baseline_tools

python3 configs/build_ground_truth.py
python3 runner/run_baseline.py                 # 静态真实 + 动态 yaml_oracle
python3 runner/run_baseline.py --static-only   # 仅静态
python3 runner/run_baseline.py --cluster       # 动态额外 kubectl apply + curl（需业务负载）

# 论文 Table F1--F10 对勾实验
python3 runner/run_f_suite.py
python3 runner/run_f_suite.py --cluster

# 扩展外部 baseline 对比（istioctl / kube-linter / kubeconform / Kyverno / kubectl dry-run / ...）
python3 runner/run_f_suite_expanded.py
```

结果：

- `results/BASELINE_SUMMARY.md` / `results/baseline_metrics_latest.json`
- `results/F_SUITE_SUMMARY.md` / `results/f_suite_metrics_latest.json`
- `results/F_SUITE_CLUSTER_SUMMARY.md` / `results/f_suite_cluster_metrics_latest.json`
- `results/F_SUITE_EXPANDED_SUMMARY.md` / `results/f_suite_expanded_metrics_latest.json`
- `results/paper_effectiveness_snippet.tex`（由 `run_f_suite.py` 按实测回填）
- `results/raw/` / `results/raw_f_suite/` / `results/raw_f_suite_expanded/`

## 方法

| ID | 含义 |
|----|------|
| S-Istio-offline | `istioctl analyze --use-kube=false` |
| S-Istio-cluster | `istioctl analyze`（含集群状态） |
| S-Ours | MeshScope 静态启发式（消融） |
| S-Lint / S-Schema | kube-linter / kubeval（未安装则 Available=NO） |
| D-Naive | 弱动态（仅明显 5xx 类信号） |
| D-Ours | 策略感知动态（无 `--cluster` 时为 yaml_oracle） |
| H-Ours | 静动融合 |

## 语料

- 复用 `accuracy/experiments/configs`（symlink）
- 新增 `configs/samples/dynamic_only/`：**7** 个 L-Dynamic 样本
- GT：`configs/ground_truth.json`（含 `detectability`）

## 诚信说明（写论文时必提）

- 当前 **D-*/H-Ours** 默认路径为 **yaml_oracle**（从策略内容推断运行时风险），用于在无 Bookinfo 负载时先打通评测管线；接真实流量后加 `--cluster` 并部署探测目标。
- **S-Ours** 启发式对齐本语料，数字偏乐观，正式稿应换接 `StaticAnalyzer` / `istio_Dynamic_Test`。
- **S-Istio-*** 为真实 `istioctl` 调用，是论文静态主基线。
