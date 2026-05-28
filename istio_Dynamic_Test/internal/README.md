# 动态验证内部模块（按领域划分）

模块总览与 CLI 说明见上级目录 [../README.md](../README.md)。

## Pipeline 数据流

```text
Config / 矩阵
    ↓  testcase/generators
TestCase
    ↓  traffic/executors + fault
ExecutionResult
    ↓  telemetry/collectors
CollectionResult
    ↓  validation/
ValidationResult
    ↓  validation/report
报告
```

## 目录职责

| 目录 | 职责 | 依赖 |
|------|------|------|
| `models/` | 配置模型 vs 运行时模型（TestCase、ExecutionResult 等） | 无业务依赖 |
| `testcase/` | 正交用例生成 | models, pkg/k8s |
| `traffic/` | 发流量（http/grpc）、故障注入 | models, pkg/runtime |
| `telemetry/` | 观测采集（Envoy/Prometheus/日志解析） | models, pkg |
| `validation/` | 期望 vs 实际行为判断 | models, telemetry |
| `pipeline/` | 编排 DynamicTester、调度、CLI | 以上全部 |
| `../pkg/` | 可复用基础设施（SSH、K8s 命名） | 无 internal 依赖 |

## gRPC 支持

| 组件 | 说明 |
|------|------|
| `traffic/protocols/grpc/` | grpcurl 命令构建、状态解析、端点解析 |
| `traffic/executors/grpc.py` | `GrpcExecutor` / `GrpcLoadExecutor` / `GrpcMeshExecutor` |
| `traffic/registry.py` | `Protocol.GRPC` 自动选型 |
| `telemetry/logs/parser.py` | 解析 `grpc_status=%RESP(GRPC-STATUS)%` |
| `telemetry/collectors/envoy.py` | `CollectionResult.metadata.grpc_metrics` |

用例字段：`protocol: grpc`、`grpc_method`、`grpc_data`（或 `path: /package.Service/Method`）。
