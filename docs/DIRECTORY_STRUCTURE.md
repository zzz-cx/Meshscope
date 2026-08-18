# 项目目录结构（工程级）

## 设计原则

1. **parser / 动态 / checker 分家**：解析只在 `istio_config_parser`，动态只认对齐模型，checker 只消费产物。
2. **动态流水线单向依赖**：testcase → traffic → telemetry → validation。
3. **`cmd/` 只做启动**，业务在 `internal/`；`pkg/` 放 SSH / K8s 等基础设施。
4. **统一 CLI** 在 `configpilot/`，不要再发明并列入口。

## 当前布局

```text
istio_check/
├── configpilot/                  # python -m configpilot
├── configpilot.json
├── istio_config_parser/          # 静态解析与对齐
│   ├── main_parser.py            # parse_static_semantic → aligned_semantic.json
│   ├── parsers/
│   ├── models/                   # FunctionModel、语义元组、IR
│   └── istio_monitor/            # 采集；快照目录不要提交
├── istio_Dynamic_Test/
│   ├── cmd/                      # python -m istio_Dynamic_Test.cmd
│   ├── internal/
│   │   ├── models/
│   │   ├── testcase/generators/  # 期望来自 aligned_semantic
│   │   ├── traffic/
│   │   ├── telemetry/
│   │   ├── validation/
│   │   └── pipeline/
│   ├── pkg/
│   └── configs/
├── consistency_checker/
│   ├── core/                     # StaticAnalyzer 等只读产物
│   ├── visualizer/               # 三层图
│   └── web/                      # Flask、静态资源图、三层图查看器
├── evaluation/
├── docker/
├── docs/
└── results/                      # aligned_semantic、报告、三层图 JSON
```

## 动态验证依赖

```text
pipeline
  → validation → telemetry → traffic → testcase → models
  → pkg (runtime, k8s)
```

`validation` **不得** import `traffic`。

## 快速入口

```bash
python -m configpilot --help
python -m configpilot web --port 8080
python -m istio_config_parser.main_parser --help
python -m istio_Dynamic_Test.cmd --help
python -m consistency_checker.main --help
```
