# Baseline 实验设计：静态原生 vs 仅动态 vs Hybrid

## 1. 目标

在**同一配置语料 + 同一 GT 标签**上，对比三类方法的**故障检出成功率**与**检测效率**，回答：

1. 仅靠 Istio 原生静态分析（`istioctl analyze`）能覆盖多少类配置错误？
2. 仅靠动态流量验证能覆盖多少（尤其是静态检不出的）？
3. Hybrid（MeshScope：静态建模 + 正交用例 + 结果融合）相对两类单模态基线，在 Recall / F1 / 端到端耗时上的增益是多少？

本实验与 `orthogonal_efficiency` **正交**：后者测「用例规模/耗时」；本实验测「对故障的检出能力 + 检测墙钟时间」。

---

## 2. 对比方法（Baselines）

### 2.1 静态组（Static-only）

| ID | 方法 | 性质 | 说明 |
|----|------|------|------|
| **S-Istio** | `istioctl analyze` | **Istio 原生静态（主基线）** | 对本地 YAML（`--use-kube=false`）或「本地+集群」做交叉资源一致性分析；输出 JSON/message code → 映射到 GT `fault_type` |
| **S-Schema** | `kubeval` / `kubeconform` | 通用 K8s schema | 只做 OpenAPI/CRD schema，几乎不理解 VS↔DR 语义 |
| **S-Lint** | `kube-linter` | 通用 K8s lint | 偏安全/最佳实践，Istio 策略语义弱 |
| **S-Ours** | MeshScope Static-only | 自研消融 | `StaticAnalyzer` / accuracy `static_only`；用于与原生工具对照，**不作为论文里的「竞品」**，而作为消融 |

**论文主对比取：S-Istio（必选）+ S-Schema 或 S-Lint（可选弱静态）+ Hybrid。**

实现要点：

- 将现有 `existing_tools.py` **拆开**：每个工具单独跑、单独计分、单独计时（禁止再绑成一个 `existing_tools` 总分）。
- `istioctl analyze` 建议两种模式都记一笔（表里可只报主结果）：
  - **offline**：`--use-kube=false`（纯静态、可复现、CI 友好）
  - **cluster-aware**：本地文件 + 集群状态（更强，但依赖环境）

### 2.2 动态组（Dynamic-only）

业界**几乎没有**与 Istio 策略语义对齐的开源「仅动态配置校验」竞品（Meshery/Linkerd check 等不对齐本语料）。因此动态基线定义为：

| ID | 方法 | 性质 | 说明 |
|----|------|------|------|
| **D-Naive** | 部署 + 泛化 HTTP 探测 | 弱动态 | `kubectl apply` → 固定 curl/ingress → 仅看 2xx/5xx；**不**做策略断言 |
| **D-Ours** | MeshScope Dynamic-only | **主动态基线（消融）** | 接 `istio_Dynamic_Test` / `DynamicAnalyzer`：按策略类型做流量验证与行为断言 |
| **D-Chaos**（可选） | FaultInjection / 加压 | 辅助 | 仅对熔断/重试等压力相关故障；不作为全语料主基线 |

**论文表述建议：**  
> Dynamic baseline = *runtime traffic validation without static guidance*（本系统动态模块消融）；另报 *naive HTTP probe* 作为下界。

### 2.3 本方法（Hybrid）

| ID | 方法 | 说明 |
|----|------|------|
| **H-Ours** | MeshScope Hybrid | 静态分析 → 正交用例生成 → 动态验证 → 置信度融合 |

要求与 accuracy 旧实现脱钩：正交用例必须**真正驱动**动态路径（对齐 `orthogonal_efficiency` / Dynamic_Test），禁止只生成元数据。

---

## 3. 语料与 GT 分层（关键）

复用并扩展 `evaluation/accuracy/experiments/configs/`。

### 3.1 故障分层（必须在 GT 中显式标注）

| 层 | 定义 | 预期检出 | 示例 |
|----|------|----------|------|
| **L-Static** | 配置层面可判定 | S✓ D✗/弱 | 权重和≠100、重复资源、gateway selector 无匹配 |
| **L-Dynamic** | 仅运行时行为暴露 | S✗ D✓ | 权重意图与实测分流偏差、超时过短导致尾延迟、熔断阈值在负载下才触发误熔断、限流 token 实际生效不符 |
| **L-Both** | 静可检且动可观测 | S✓ D✓ | missing subset、指向不存在 host、路由冲突导致不稳定路由 |
| **L-Neg** | 正确配置 | S✗ D✗ | baseline / correct |

当前 GT 缺口：**`dynamic_only ≈ 0`**。实施前必须补 **≥6–8** 个 L-Dynamic 样本，否则无法证明「仅静态不够、仅动态/Hybrid 有增益」。

### 3.2 样本规模（建议）

| 来源 | 规模 | 备注 |
|------|------|------|
| human_errors | ≥12（含新增 runtime-only） | 可控、可解释 |
| mutated | ≥20 | 变异 VS/DR/EF |
| real_world | 能收集多少算多少 | 真实仓库摘录 |
| correct | ≥5 | 控 FP |

每个样本字段扩展：

```json
{
  "has_fault": true,
  "fault_type": "...",
  "detectability": "static_only|dynamic_only|both|none",
  "expected_detection": {
    "static_detection": true,
    "dynamic_detection": false
  }
}
```

评测器必须按 `detectability` **分层报 P/R/F1**，不能只报一个全局数。

---

## 4. 指标

### 4.1 成功率（主指标）

对每个方法 × 全体 / 分层：

- Precision / Recall / F1（样本级：`has_fault` + `fault_type` 命中）
- 可选：按 `fault_type` 的 per-class Recall
- FP 率（在 L-Neg 上）

映射规则：`istioctl` message code / 动态断言标签 → GT `fault_type` 的对照表固定进仓库（`configs/fault_type_mapping.yaml`），避免事后调参。

### 4.2 效率（次指标）

| 指标 | 定义 |
|------|------|
| **T_detect** | 单样本：从「输入配置」到「输出检测结果」墙钟时间 |
| **T_static** / **T_dynamic** | Hybrid 内部分段耗时 |
| **请求数 / 字节** | 仅动态方法：探针请求量（可选） |

静态方法应显著快于动态；Hybrid 应对标「静态引导后的动态」，相对 D-Ours 全量探测应更少请求或更短 T_detect（可与 orthogonal 结论交叉引用）。

### 4.3 统计

- 每方法重复 **≥3** 次取均值±标准差（动态有抖动）
- 主表用 bootstrap 95% CI（可选）
- 配对比较：H-Ours vs S-Istio、H-Ours vs D-Ours（McNemar on 检出对错）

---

## 5. 实验流程

```
对每个样本 config:
  for method in [S-Istio, S-Schema?, S-Lint?, D-Naive, D-Ours, H-Ours]:
      t0 = now()
      result = method.detect(config)   # 静态不 apply；动态/Hybrid 按需 apply+清理
      t1 = now()
      score(result, GT[config])
      log(T_detect=t1-t0, raw_output)
  teardown namespace / restore baseline
聚合 → metrics.json + per_method.csv + stratified_table.md
```

约束：

1. **公平部署**：凡需集群的方法使用同一 namespace模板、同一 settle 策略。
2. **隔离**：样本串行或独立 namespace，避免交叉污染。
3. **超时**：动态单样本硬超时（如 120s），超时记 FN + 记时封顶。
4. **可复现**：固定 Istio/K8s 版本、记录 `istioctl version`、随机种子。

---

## 6. 目录与实现落点

```
evaluation/baseline_tools/
├── BASELINE_DESIGN.md          # 本设计
├── README.md                   # 运行说明（实现后补）
├── adapters/                   # 每个基线一个适配器
│   ├── istioctl_analyze.py     # S-Istio
│   ├── kube_schema.py          # S-Schema
│   ├── kube_linter.py          # S-Lint
│   ├── naive_dynamic.py        # D-Naive
│   ├── mesh_dynamic_only.py    # D-Ours → istio_Dynamic_Test
│   └── mesh_hybrid.py          # H-Ours
├── configs/
│   ├── fault_type_mapping.yaml
│   └── (symlink or copy) ground_truth + samples
├── runner/
│   ├── run_baseline.py
│   └── score.py                # 分层 P/R/F1 + 耗时
└── results/
```

复用：

- GT / YAML：`evaluation/accuracy/experiments/configs/`
- 打分骨架：`.../runner/evaluator.py`（扩展分层 + 单工具拆分）
- 动态能力：`istio_Dynamic_Test/`、`consistency_checker/core/`
- 不与 `orthogonal_efficiency` 混跑；结果可交叉引用「用例数↓、此处 Recall 不降」

---

## 7. 预期结果形态（论文表）

**Table A — 整体成功率**

| Method | Prec | Rec | F1 | T_detect (s) |
|--------|------|-----|----|--------------|
| S-Istio | … | … | … | … |
| D-Naive | … | … | … | … |
| D-Ours | … | … | … | … |
| **H-Ours** | … | … | … | … |

**Table B — 分层 Recall**

| Method | L-Static | L-Dynamic | L-Both |
|--------|----------|-----------|--------|
| S-Istio | high | **low** | mid |
| D-Ours | low/mid | **high** | high |
| H-Ours | high | high | high |

预期叙事：静态原生强在 L-Static/部分 L-Both；仅动态强在 L-Dynamic；Hybrid 两侧都高，且相对盲目动态更省时。

---

## 8. 实施阶段

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P0** | 拆分 `istioctl` 适配器 + 映射表；对现有 GT 跑 S-Istio smoke | 单工具 JSON |
| **P1** | 补 L-Dynamic 样本 ≥6；接 D-Naive / D-Ours | 分层可评 |
| **P2** | 接 H-Ours（真正交驱动）；统一 runner + 耗时 | 主表 A/B |
| **P3** | 可选 S-Schema/S-Lint；重复 3 次；写结果摘要 | `results/BASELINE_SUMMARY.md` |

---

## 9. 与现有 accuracy 实验的关系

| 项目 | accuracy/experiments | 本 baseline |
|------|----------------------|-------------|
| existing_tools | 三工具绑一起 | **拆开，S-Istio 独立** |
| static/dynamic | 启发式脚本，未接生产分析器 | **接真实 Static/Dynamic_Test** |
| GT | 缺 runtime-only | **强制分层 + 补样** |
| 指标 | 主打 P/R/F1 | P/R/F1 **+ T_detect**，分层报 |

旧 accuracy 可作为历史草稿；论文数字以本目录跑出的结果为准。

---

## 10. 已确认决策

1. **动态主基线**：采用「D-Ours（自研动态消融）+ D-Naive 下界」；不强制外部动态竞品。
2. **S-Istio 模式**：**offline + cluster 都跑**；论文主报 **offline**。

## 11. 首轮实验结果（2026-07-28）

语料：**19** 样本（L-Static=3, L-Dynamic=7, L-Both=8, L-Neg=1）。  
命令：`python3 runner/run_baseline.py`（动态为 yaml_oracle；S-Lint/S-Schema 未安装）。

| Method | Prec | Rec | F1 | T_avg (s) |
|--------|------|-----|----|-----------|
| S-Istio-offline | 0.500 | **0.059** | 0.105 | 0.035 |
| S-Istio-cluster | 0.125 | 0.400 | 0.191 | 0.134 |
| D-Naive | 1.000 | 0.167 | 0.286 | 0.005 |
| D-Ours | 0.929 | **0.765** | 0.839 | 0.004 |
| **H-Ours** | 0.944 | **1.000** | **0.971** | 0.008 |
| S-Ours (消融) | 0.944 | 1.000 | 0.971 | 0.003 |

分层 Recall（节选）：S-Istio-offline 在 L-Dynamic=**0**；D-Ours 在 L-Dynamic=**1.0**、L-Static=**0**；H-Ours 两侧均为 **1.0**。

详见 `results/BASELINE_SUMMARY.md`。后续：安装 kube-linter（可选）、部署探测负载后 `--cluster`、S/H 换接生产分析器。
