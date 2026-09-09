# Orthogonal Testing Efficiency

对齐 Dynamic_Test 正交维度（match / action / scope / trigger）与 `orthogonal_fault_bundle` 的「独立效果可合并观测」思想，在 **服务规模 × 配置规模** 二维网格上评估：

1. 穷举 vs 正交的用例数与缩减率  
2. 正交合并前后的故障检出率（覆盖率消融）

## 维度

| 维度 | 取值 |
|------|------|
| 服务规模 \(N\) | 5 / 10 / 15 / 20 / 30 / 40 / 50 |
| 配置规模 | C1→C5（路由 → … → +mirror/authz） |
| 重复次数 | 默认 5（`--runs`） |

## 时间口径（完整检验）

`exh/ortho_validation_s_*` 是整套用例的**完整检验时间**，按 Dynamic_Test 管线逐条累计：

`apply → traffic(+策略开销) → telemetry → assert → clear`

正交 bundle 共享一次 apply/clear，成员效果仍各自打流与断言。多次运行取 mean±std。

## 真实集群模式（默认）

```bash
cd /root/configPilot/istio_check/evaluation/efficiency/orthogonal_efficiency
# 默认 --mode cluster：每条用例真实 kubectl apply → curl → delete，墙钟计时
python3 run_experiment.py --mode cluster --services 5,10,15,20 --configs C1,C2,C3,C4 --runs 2 \
  --output-dir ./results_cluster

# 仅估时（旧行为）：
python3 run_experiment.py --mode model --output-dir ./results
```

产出目录：`results_cluster/`（CSV / 消融 JSON / LaTeX / log）。  
日志：`results_cluster/experiment_cluster.log`。

## 产出

| 文件 | 含义 |
|------|------|
| `results/orthogonal_reduction.csv` | 作图数据（配置项 vs 用例数 / 缩减率） |
| `results/coverage_ablation.json` | 消融表（合并前后 DR） |
| `results/experiment_summary.json` | 全表 JSON |
| `results/orthogonal_efficiency_snippet.tex` | 用**实测数**回填的 LaTeX 片段 |
| `figures/orthogonal-reduction.png` | 若本机有 matplotlib 则自动出图 |

## 与论文表述的对应关系

## 高配置覆盖下降：根因与修复（N=30）

### 根因
1. **Bundle 全有或全无**：正交合并后，任一成员 HTTP 失败 → 整案 `ok=False` → 同 bundle 内已成功的效果也被算作未检出，放大 ΔDR（N=30/C3 曾到 +20%）。
2. **同 host 多 DestinationRule**：CB/outlier 检验新建 `ortho-dr-*`，与部署期 `meshscope-svc-*` DR 同 host 并存，Istio 合并/覆盖不稳定，N 大时 `trigger_*` 类用例首先失败。

### 修复
1. 覆盖按**成员级** HTTP 断言计入（`detected_units`），不再整案一票否决。
2. DR 效果**原地更新**同名服务 DR，结束后 restore 基线 DR；同服务多个 DR 效果禁止打进同一 bundle。
3. 随 N 增大自适应 settle，失败重试加长。

回归：`results_fix_n30/`（N=30 × C3/C4/C5）。
