# pkg — 可复用基础组件

与业务无关，可被 `internal/` 各域引用，**不得**反向依赖 `internal`。

- `k8s/` — 集群环境、Ingress 分片、Meshscope 命名
- `runtime/` — SSH / 本地命令执行
- `observability/` — Prometheus/Jaeger 地址发现、全局 ConfigMap
