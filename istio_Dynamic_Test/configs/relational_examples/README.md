# 分流、重试与连接池熔断实验配置

这些配置来自 2026-11-05 的真实 Envoy 对照实验，供检查模型和复现实验。命名空间 `configpilot-lab` 是模板占位；`backend-0/1` 必须由受控测试后端提供，不是已有业务 Service 的别名。Gateway 对应实验集群的 `default/bookinfo-gateway`。

| 配置 | 触发与判定 |
|---|---|
| traffic-split.yaml | 两个独立 Service 70/30 分流；400 请求、并发 4；按请求关联目标回执 |
| retry-budget.yaml | 2 次重试、5xx、每次 250ms、总预算 500ms；恢复模式先两次 503 后 200，慢模式每次延迟 400ms |
| connection-pool.yaml | maxConnections=1、http1MaxPendingRequests=1、attempts=0；16 请求并发、后端保持 500ms；检查 Envoy UO 与成功请求并存 |

各配置同时包含路径改写、请求 Header 设置/删除、响应 Header 设置，用来验证单个执行可以分别提供多个义务的证据。熔断例子只覆盖连接池请求溢出，未覆盖 outlierDetection。

`*-profiles.json` 提供受控执行契约，不包含策略正确值；正确值从 parser 生成的固定关系模型读取。先生成对应命名空间的 `aligned_semantic.json`，然后：

```bash
python -m istio_Dynamic_Test.cmd.relations \
  --aligned aligned_semantic.json \
  --profiles traffic-split-profiles.json \
  --output-dir probe-plan
```

该命令生成计划；提供 `--evidence` 才判定实际结果。它自身不创建后端或发送流量。

完整生命周期脚本：`output/complex-validation-20261105/benchmark_complex.py`。它在 master 上启动受控后端、创建带 owner 标记的临时命名空间、调用真实静态 parser、冻结期望、应用变异、等待数据面就绪、逐探针执行并清理。重试证据来自后端实际尝试事件；503 不自动代表熔断，需 Envoy 响应标志。脚本的全部临时资源由脚本管理，无需手动 apply 这些模板。
