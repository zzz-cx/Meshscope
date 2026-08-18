# Istio 动态验证（`istio_Dynamic_Test`）

基于 **parser 写出的对齐语义模型** 生成测试用例、在集群入口发流量、采集 Envoy/Prometheus 观测，并校验行为是否与期望一致。

期望只来自 `aligned_semantic.json` 里 `matched` / `partial_matched` 的元组。没有该文件会直接报错，**不会**回退解析 YAML 或把 `configs/istio_config.json` 当期望源。请先：

```bash
python -m configpilot static --namespace default
```

## 快速开始

```bash
# 统一入口（推荐）
python -m configpilot dynamic -- --from-control-plane \
  --ingress-url http://<ingress-host>:<port> \
  --ssh-host <node-ip> --ssh-user root --ssh-password <pwd>

# 模块入口
python -m istio_Dynamic_Test.cmd --from-control-plane \
  --ingress-url http://<ingress-host>:<port> \
  --ssh-host <node-ip> --ssh-user root --ssh-password <pwd>

python -m istio_Dynamic_Test.cmd --help
```

编程调用：

```python
from istio_Dynamic_Test import DynamicTester
from istio_Dynamic_Test.internal.testcase.generators import ConfigGenerator, TestCaseGenerator
from istio_Dynamic_Test.internal.validation import run_verification, analyze_single_case
from istio_Dynamic_Test.internal.models import TestCase, TestSuite, Protocol
```

`main.py` 仅作兼容薄封装，内部转发到 `internal.pipeline.cli`，新代码请使用 `python -m istio_Dynamic_Test.cmd`。

---

## 四层流水线

```text
┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌───────────┐
│  Generator   │ ──▶ │ Executor │ ──▶ │ Collector │ ──▶ │ Validator │
└─────────────┘     └──────────┘     └───────────┘     └───────────┘
  TestCase         ExecutionResult    CollectionResult   ValidationResult
```

| 阶段 | 输入 | 输出 | 主要代码 |
|------|------|------|----------|
| 生成 | Istio JSON / 矩阵 / 控制面快照 | `TestCase` / `TestSuite` | `internal/testcase/generators/` |
| 执行 | `TestCase` | `ExecutionResult` | `internal/traffic/` |
| 采集 | 执行上下文 + SSH/K8s | `CollectionResult` | `internal/telemetry/` |
| 验证 | 期望 + 采集结果 | `ValidationResult` | `internal/validation/` |
| 编排 | 上述四步串联 | `PipelineResult` 列表 | `internal/pipeline/`（`DynamicTester`） |

**依赖约束**：`validation` 不得 import `traffic`（只消费 `ExecutionResult` / `CollectionResult` 等模型）。`pkg/` 不依赖 `internal/` 业务层。

---

## 目录结构

```text
istio_Dynamic_Test/
├── cmd/                    # CLI：python -m istio_Dynamic_Test.cmd
├── main.py                 # 兼容入口（转发 cli.main）
├── __init__.py             # 对外导出 DynamicTester
│
├── internal/               # 全部业务逻辑（按领域划分）
│   ├── models/             # 数据模型与 Protocol 枚举
│   ├── testcase/           # 用例生成
│   │   └── generators/
│   ├── traffic/            # 发流量、故障注入、协议适配
│   │   ├── executors/      # HTTP / 负载 / 网格 / 连接池专项等
│   │   ├── fault/          # VirtualService 故障注入
│   │   ├── protocols/      # http（curl/hey）与 grpc（预留）
│   │   └── registry.py     # 按 TestCase 选择 Executor
│   ├── telemetry/          # 观测采集
│   │   ├── collectors/     # Envoy 日志、Prometheus、组合采集
│   │   ├── logs/           # 日志解析、Pod 拉取、访问日志开关
│   │   ├── metrics/        # Prometheus 查询
│   │   └── traces/         # 链路依赖辅助
│   ├── validation/         # 策略验证与报告
│   │   └── policies/       # 路由、分流、重试、超时、熔断等
│   └── pipeline/           # DynamicTester、CLI、并行调度
│       └── scheduling/     # 正交故障捆绑、并行锁
│
├── pkg/                    # 可复用基础设施（无 internal 业务依赖）
│   ├── k8s/                # 命名、Ingress 分片、环境探测
│   ├── runtime/            # SSH 客户端
│   └── observability/      # Istio 全局配置发现
│
├── configs/                # 示例 Istio 配置、output_matrix.json 等
└── results/                # 运行产物（日志、矩阵、报告，建议 gitignore）
```

更细的 `internal/` 说明见 [internal/README.md](internal/README.md)。

---

## `internal/` 各包职责

### `internal/models/`

- `protocol.py`：`Protocol.HTTP` / `Protocol.GRPC`
- `testcase.py`：`TestCase`、`TestSuite`、`ExecutionResult`、`CollectionResult`、`ValidationResult`、`PolicyType` 等

所有层之间只通过这些类型传递数据。

### `internal/testcase/generators/`

| 模块 | 说明 |
|------|------|
| `base.py` | 生成器抽象基类 |
| `config_generator.py` | 组装套件；期望来自对齐模型 |
| `semantic_generator.py` | 从 `aligned_semantic.json` 生成用例 |
| `test_case_generator.py` | 正交组合（评估脚本也会调用） |

### `internal/traffic/`

| 模块 | 说明 |
|------|------|
| `registry.py` | `ExecutorRegistry.select(test_case)` 集中选型 |
| `executors/http.py` | 单次 HTTP 请求（curl） |
| `executors/load.py` | 压测（hey） |
| `executors/mesh.py` | 流量分割 / 网格级验证 |
| `executors/connection_pool_outlier.py` | 连接池与 outlier 专项 |
| `executors/prometheus_monitor.py` | 持续 curl + Prometheus 增量验证（可独立 CLI） |
| `fault/injector.py` | VS 级故障注入与清理 |
| `protocols/http/` | URL、Header、curl/hey 封装、结果落盘 |
| `protocols/grpc/` | grpcurl 客户端、状态码解析 |
| `executors/grpc.py` | 入口 / 负载 / mesh 内 gRPC 执行器 |

gRPC 通过 **grpcurl** 发流；Envoy 访问日志含 `grpc_status` 字段用于采集与验证。

### `internal/telemetry/`

| 模块 | 说明 |
|------|------|
| `collectors/envoy.py` | 基于 Envoy 访问日志的采集（默认） |
| `collectors/prometheus.py` | Prometheus 指标采集 |
| `collectors/composite.py` | Envoy + Prometheus 组合 |
| `logs/parser.py` | Envoy 日志解析（路由、状态码、版本标签等） |
| `metrics/prometheus.py` | PromQL 辅助 |
| `traces/` | 服务依赖图、trace 拉取辅助 |

### `internal/validation/`

| 模块 | 说明 |
|------|------|
| `composite.py` | 组合多个策略验证器 |
| `offline.py` | `run_verification` / `analyze_single_case`（离线矩阵验证） |
| `report.py` | 报告生成 |
| `policies/*.py` | 各 Istio 策略的期望 vs 实际判断（routing、traffic_split、retry、timeout 等） |

### `internal/pipeline/`

| 模块 | 说明 |
|------|------|
| `cli.py` | `DynamicTester` 类 + `main()` CLI |
| `scheduling/` | 安全并行调度、正交故障用例捆绑 |

---

## `pkg/` 基础库

| 包 | 用途 |
|----|------|
| `pkg/runtime/ssh.py` | 远程执行 curl/hey、kubectl 等 |
| `pkg/k8s/` | MeshScope 服务命名、Ingress 分片、集群环境检测 |
| `pkg/observability/` | 控制面配置目录发现、全局 Istio 设置 |

评估脚本、Web 服务、一致性检查等模块应通过 `istio_Dynamic_Test.internal.*` 引用，**不要**再使用已删除的顶层 `generators/`、`executors/`、`validators/`、`checker/`、`generator/`、`verifier/` 路径。

---

## CLI 常用参数

| 参数 | 说明 |
|------|------|
| `-i`, `--input` | Istio 配置 JSON（与 `configs/` 下样例格式一致） |
| `--matrix` | 旧版 `output_matrix.json` 测试矩阵 |
| `--ingress-url` | 集群入口 URL |
| `--from-control-plane` | 使用控制面快照目录做补充信息；**期望仍来自对齐模型** |
| `--control-plane-config` | 控制面快照目录（默认指向 `istio_config_parser/istio_monitor/istio_control_config`） |
| `--service-deps` | 服务依赖 JSON（可选） |
| `--namespace` | K8s 命名空间（默认 `default`） |
| `--prometheus-url` | 启用 Prometheus 组合采集（流量分割等） |
| `--ssh-host` / `--ssh-user` / `--ssh-password` / `--ssh-port` | 远程执行与日志采集 |
| `--single-case` | 只运行指定 `case_id` |

---

## gRPC 用例示例（矩阵 JSON）

```json
{
  "case_id": "grpc_health_001",
  "type": "single_request",
  "request_params": {
    "protocol": "grpc",
    "host": "reviews",
    "path": "/grpc.health.v1.Health/Check",
    "grpc_data": "{}"
  },
  "expected_outcome": { "destination": "v1" }
}
```

要求 SSH 节点或 mesh Pod 内已安装 `grpcurl`；Envoy access log 已包含 `grpc_status`（`enable.py` 默认格式已追加）。

---

## 与其他模块的关系

```text
istio_config_parser/     # 写出 aligned_semantic.json
        ↓
istio_Dynamic_Test/      # 期望只认对齐元组
        ↓
consistency_checker/     # 消费静/动产物，三层图与 Web
```

典型工作流：`configpilot static` → `configpilot dynamic` → `configpilot check` / `web`。

---

## 版本与变更说明

- **v2.1+**：目录重组为 `cmd/` + `internal/` + `pkg/`；删除顶层兼容 shim（`generators/`、`executors/`、`validators/` 等）及旧版 `checker/`、`generator/`、`verifier/`。
- 对外稳定入口：`from istio_Dynamic_Test import DynamicTester` 与 `python -m istio_Dynamic_Test.cmd`。
