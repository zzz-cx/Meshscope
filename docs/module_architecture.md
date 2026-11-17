# 模块契约与数据流

更新：2026-11-17。主流程见 [ARCHITECTURE](ARCHITECTURE.md)。

核心模块为**采集、解析、规划、执行、判定**。采集同时覆盖配置快照和运行证据；诊断与报告属于判定的结果解释；CLI、Web、运行配置和统一编排作为公共支撑。

```text
采集配置 → 解析 → 规划 → 执行 → 采集运行证据 → 判定
```

同一采集模块在执行前后提供不同类型的数据。下面的 monitor 和 collector 分别对应配置采集与运行证据采集，oracle 和 diagnostics 分别对应判定与结果解释。

| 生产者 → 消费者 | 数据契约 | 约束 |
|---|---|---|
| monitor → parser | 控制面 YAML 与数据面快照 | 保留来源、时间和资源身份 |
| parser → workflow | `aligned_semantic.json.relational_model` | 期望来自冻结声明模型，不根据错误运行状态重建 |
| 公共语义 → 静态/动态分析 | 已解析规则上的选择、匹配和变换函数 | 不解析第二遍 YAML，不从图边推导未定义语义 |
| planner → executor | `probe_plan.json` | 模型/计划指纹、全部义务、候选与覆盖、资源足迹 |
| executor → collector | 本次运行唯一请求 ID 集合 | 来源和代次匹配、快照不早于请求完成 |
| collector → oracle | `captured_evidence.json` | 唯一事件、时间窗口、完整性与实际目标 |
| workflow → 后端清理 | 已持久化完成观察对应的 ID | 不释放活跃尝试，不允许全局 reset |
| oracle → diagnostics | `obligation_results.json` | FAIL 优先；未知不等于通过，未判定不移除分母 |
| diagnostics → CLI/API | `dependency_graph.json`、`diagnostics.json`、`run_report.json` | 依赖候选不冒充因果结论 |

`pairs`、`expected_tuples`、矩阵、聚合结果和 SQLite 三层图仍用于兼容视图；动态验证规划不因某项未对齐就删除对应声明义务。不可执行项显式保留。

报告状态：PLANNED、PASSED、FAILED、INCONCLUSIVE。执行异常保留 `engine_error` 与已完成证据，不能将异常当作配置通过。

文件身份与版本检查位于 `configpilot/workflow.py` 和 `configpilot check`。配置/流量运行的隔离与纯计算后端分开管理。
