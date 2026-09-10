# MeshScope 模块接口与数据流

本文描述三个模块之间的**当前契约**。旧文档里的 `control_plane_graph.json`、`generator/`、`checker/`、`consistency_verification/` 路径已废弃。

## 总览

```text
istio_monitor 快照
       │
       ▼
istio_config_parser.parse_static_semantic()
       │
       ▼
results/consistency/aligned_semantic.json
       │
       ├──────────────► istio_Dynamic_Test（期望元组）
       │                         │
       │                         ▼
       │                  动态结果 / 验证报告
       │                         │
       └──────────────► consistency_checker
                                 │
                                 ▼
                    报告 + 三层图 JSON + Web
```

统一入口：`python -m configpilot`。配置文件：项目根目录 `configpilot.json`。

## parser：`istio_config_parser`

### 输入

- 控制面：`istio_config_parser/istio_monitor/istio_control_config/`（VS / DR / EF / Gateway / Service …）
- 数据面：`istio_config_parser/istio_monitor/istio_sidecar_config/`（`routes.json` / `clusters.json` / `listeners.json`）
- 可选 Ingress：`istio_ingress_config/`

### 处理

1. `UnifiedParser` 将两侧投影为 `FunctionModel`，再对齐为 `AlignedFunctionPair`
2. 语义元组比较（容差 `tau` 来自 `configpilot.json`）
3. `analyze_cross_resource_conflicts`：缺 subset、路由优先级、Gateway 选择器等
4. `_simple_graph_from_pairs`：静态资源图（服务 + Istio 资源，带 namespace、声明式 spec、数据面摘要）

### 输出

`dump_aligned_semantic()` → 默认 `results/consistency/aligned_semantic.json`

动态侧只应使用 `alignment_status` 为 `matched` 或 `partial_matched` 的元组（`expected_tuples`）。

CLI：

```bash
python -m configpilot static --namespace default --export
python -m istio_config_parser.main_parser --namespace default --export
```

Web：`POST /api/static/analyze` 调用同一套 `parse_static_semantic`，返回 `summary`、`conflicts`、`graph_data`。

## 动态验证：`istio_Dynamic_Test`

### 输入

- **必须**已有 `aligned_semantic.json`
- Ingress URL、SSH、可选 Prometheus（`configpilot.json` 或 CLI）

没有对齐产物时 `load_aligned_semantic()` 抛错，**不**再解析控制面 YAML，也**不**把 `configs/istio_config.json` 当作期望来源。

### 流水线

```text
Generator → Executor → Collector → Validator
```

| 阶段 | 代码 |
|------|------|
| 生成 | `internal/testcase/generators/semantic_generator.py` |
| 执行 | `internal/traffic/` |
| 采集 | `internal/telemetry/` |
| 验证 | `internal/validation/` |
| 编排 | `internal/pipeline/`（`DynamicTester`） |

`validation` 不得 import `traffic`。

CLI：

```bash
python -m configpilot dynamic -- --from-control-plane --ingress-url http://HOST:PORT/productpage
python -m istio_Dynamic_Test.cmd --help
```

## checker：`consistency_checker`

### 输入

- `aligned_semantic.json`（`StaticAnalyzer` 只读此文件）
- 动态结果目录 / 测试矩阵

### 处理

- 一致性判定、报告
- `ThreeLayerGraphGenerator`：全局 / 服务 / 配置三层，控制面期望权重 vs 数据面实测权重可画成双轨边

### 输出

- `results/consistency/report_*.json`
- `results/visualization/*_three_layer_graph.json`
- Web：`python -m configpilot web`

不要在 checker 里重新实现 parser。

## Web API（摘要）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/static/analyze` | parser 静态对齐 |
| POST | `/api/dynamic/generate` | 从对齐模型生成矩阵 |
| POST | `/api/dynamic/run` | 执行动态测试 |
| POST | `/api/consistency/graph` | 生成三层图 |
| GET | `/api/three_layer_graph/latest` | 最新三层图 JSON |
| GET | `/three_layer_graph` | 三层图查看器 |

静态图画在主页面「静态分析」；三层图是独立 Cytoscape 查看器（iframe / `/three_layer_graph`）。

## 目录约定

详见 [DIRECTORY_STRUCTURE.md](DIRECTORY_STRUCTURE.md)。采集目录在 `istio_monitor/` 下，分析结果在 `results/`，不要把集群快照提交进 git。
