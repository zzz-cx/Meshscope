# 不修改 VS 的重试与连接池验证

更新日期：2026 年 11 月 16 日。

统一 CLI 和默认 Web API 使用受控执行工作流；除下述契约外，也支持通用无状态 HTTP 与 /2 分流批次。执行器提供容量预算、共享回执采集、逐探针证据日志、记录上限和安全释放。后文 2026-11-11 的实验按当时部署边界记录，未覆盖部署运行中的远程 Web。

## 1 触发方式

采用隔离的受控后端。VS 和 DR 在准备阶段安装完成，探针执行期间保持不变。通过请求模式让后端产生失败序列或响应延迟，不再临时向入口 VS 插入 abort 或 delay 规则。

| 验证目标 | 触发方式 | 必须检查的证据 |
|---|---|---|
| 重试恢复 | 后端针对同一请求前 N 次返回 503，之后返回 200 | N+1 个唯一尝试事件、状态序列与客户端最终结果 |
| 总超时与重试预算 | 每次后端响应慢于单次尝试预算 | 实际尝试、客户端 504、总耗时；不替代恢复探针 |
| 连接池溢出 | 后端保持连接，发送固定并发突发 | 成功与溢出拒绝并存，并有代理 UO 标志或隔离 overflow 增量 |
| 异常实例摘除 | 需要指定实例失败及摘除、恢复状态 | 本次未提供通用适配，不能用 503 数量证明摘除 |

连接池保护和 outlierDetection 是不同验证目标。本次完成前者，后者仍为未支持项。

## 2 默认流程的变化

- SemanticGenerator 不再为重试生成 `simulate_config_fault + abort 503`。
- 旧矩阵即使保留该触发参数，重试、连接池和熔断用例也不执行 VS 注入、无触发保证的负载或采集预热，保留为 INCONCLUSIVE 并指向新入口。
- 日志条目数、503 比例以及“清除注入后出现 200”不再作为这些策略的通过依据。
- 报告单列未判定，不算 PASS 或实际 FAIL；可判定通过率仅使用 PASS 与 FAIL。
- 本次没有删除单独验证故障注入策略的其他路径，也没有把限流改成修改 VS 触发。

业务服务不会因为带了测试 Header 就自动具备失败开关。没有对应能力时，不自动重写业务路由，不假装完成验证。

## 3 启动隔离后端

```bash
python -m istio_Dynamic_Test.cmd.controlled_backend \
  --namespace my-controlled-lab \
  --backend retry-backend:19401 \
  --backend pool-backend:19402 \
  --bind 0.0.0.0 \
  --control-port 19490
```

此命令只启动后端和回执接口，不创建 Service、VS 或 DR。测试 Service/Endpoints 需提前指向专用端点，不能将它当作已有业务 Service 的替身。回执接口只监听回环地址；执行器在同一主机运行，或使用显式 SSH 隧道。

请求使用唯一 `x-audit-request`。`x-test-mode` 指定 normal、recover、slow、burst 或 fail-once。失败次数和延迟从冻结参照模型推导，写入 `x-audit-failures`、`x-audit-delay`。不使用会覆盖被测重试策略的 `x-envoy-retry-on` 等 Header。

后端记录实际请求 ID、尝试事件 ID、Service 身份、Header、URI、状态和时间。计数按请求隔离，不使用全局失败开关。回执查询只读并拒绝 reset；新增 `/release` 只释放指定且已完成的记录，workflow 在证据持久化后调用。默认最多 20000 条记录、完成后保留 300 秒，活跃记录不被 TTL 删除；过载会使运行保持未判定。

当前适用 `configpilot.controlled-http-backend/2`：retryOn=5xx、attempts 1–3、perTryTimeout 250–600ms、总 timeout 为两倍 perTryTimeout；连接池契约为 maxConnections=1、http1MaxPendingRequests=1、attempts=0。不在范围内的配置保持未判定。

## 4 规划与执行

先准备隔离配置，并通过现有静态 parser 生成含关系模型的 `aligned_semantic.json`。动态执行器不重新解析 YAML，也不根据错误状态重新生成期望。

profiles 示例：

```json
[
  {
    "kind": "retry-budget",
    "rule_name": "retry-tested",
    "backend_contract": "configpilot.controlled-http-backend/2",
    "request": {"host": "retry.controlled.invalid", "path": "/test/item", "method": "GET", "headers": {}}
  },
  {
    "kind": "pool",
    "rule_name": "pool-tested",
    "backend_contract": "configpilot.controlled-http-backend/2",
    "request": {"host": "pool.controlled.invalid", "path": "/test/item", "method": "GET", "headers": {}}
  }
]
```

准备阶段还需安装代次响应头，保存每个 Host 的期望值到 `activation-headers.json`：

```json
{
  "retry.controlled.invalid": {"x-audit-generation": "prepared-generation"},
  "pool.controlled.invalid": {"x-audit-generation": "prepared-generation"}
}
```

这些值必须对应实际配置，不能随意填 true。代次不符时不会通过。连接池场景还需实验资源提供 `x-audit-response-flags` 等代理响应标志。当前 HTTP 适配器没有实现隔离计数器查询，使用 UO 标志与后端回执，不把业务 503 当作溢出。

```bash
python -m istio_Dynamic_Test.cmd.relations \
  --aligned aligned_semantic.json \
  --profiles profiles.json \
  --execute \
  --ingress-url http://PROXY_HOST:PORT \
  --backend-control-url http://127.0.0.1:19490/ \
  --activation-headers activation-headers.json \
  --workers 2 \
  --output-dir results/controlled-run
```

追加 `--no-reuse` 执行独立探针对照。不传 `--execute` 时仍只规划；`--execute` 不与离线 `--evidence` 同用。产物包含计划、覆盖决策、实际证据、逐义务结果和执行统计。

客户端不自动重试或跟随重定向。慢请求结束后仍等待上游尝试收尾；期间让出 worker，但保留规则和实际 DR 对应的状态预留。超过收尾期限仍有尝试执行时，整个运行报错停止，不继续启动依赖同一状态的任务。

执行器中没有 kubectl、VS patch 或配置恢复操作。容量仅在最多 4 worker 和契约负载内得到验证；不同进程不能绕过当前进程内调度器，在同一状态资源上另行并发。

## 5 部署与验证边界

在隔离命名空间中准备专用后端和配置，先冻结健康配置的参照模型，再分别改变重试次数和连接池阈值。独立与复用计划使用相同义务和判定器，逐项比较结果。缺陷只在执行前植入自有资源，探针执行期间不写 VS/DR。

执行前后核对测试资源的 UID、resourceVersion 和 spec；结束后确认自有资源及后端端口已回收。环境准备、缺陷变异和清理涉及配置写入，与探针执行阶段分别计量。

实验脚本、原始证据和评估报告在本地单独保存，不随源码发布。
