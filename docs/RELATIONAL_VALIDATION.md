# 基于关系语义模型的验证规划：实现说明

2026-11-16：验证规划已接入统一 CLI 和默认 Web API；通用 HTTP 与 /2 分流、重试、连接池执行共享批量回执采集，并支持负载预算、证据日志和安全回收。计算使用索引闭包及可选 Python 进程/Go。原生生产遥测的通用共享仍未完成。入口和实现范围以 [整体架构](ARCHITECTURE.md)、[实现核对](IMPLEMENTATION_STATUS.md) 为准。

## 模型与来源

`parse_static_semantic()` 在 `aligned_semantic.json` 中增加 `relational_model`：

```text
M_ref = ⟨Π, R; Σ⟩
  Π = 带资源身份、HTTP 规则身份及 if/what/when/where 的策略节点
  R = 带参与者、条件、来源的关系
  Σ = semantic_rules 与 semantics_version
```

模型是管理员声明的控制面参照，**不是数据面行为正确性的证明**。不从被植入错误的配置重新生成期望。源资源、规则索引、原始参数、UID/版本和模型摘要用于追溯。

它由 parser 从原始快照构造，避免按服务聚合后丢失 retry/timeout 的具体所属路由。现有语义元组和旧对齐输出保持兼容；新规划器只消费 parser 产物，不读取 YAML。按命名空间规划时仍保留快照中的跨命名空间引用及竞争规则上下文。

关系范围：

| 关系 | 第一版的处理 |
|---|---|
| precedes | 同一 VS 中的完整前序关系；寻找重叠请求，生成可观测的顺序选择义务 |
| attached_to | 将指令绑定到所属规则；依赖切片包含同规则共同生效的指令 |
| references | 保留 Service、Gateway、DR 和子集引用信息；解析失败阻止相关授权，不能当作运行证明 |
| shared_time_budget | 通用场景保留未完成项；显式受控后端契约可分别执行重试恢复、预算截断探针 |
| may_short_circuit | 保存 fault 与 retry/timeout 的潜在截断关系，动态结果保持未完成 |
| inherits_overrides | 保存父级/子集策略关系；字段级继承解析尚未实现，不能授权合并 |

当前还没有把 Envoy dump 的全部关系投影到同一关系 schema。静态 parser 保留原控制面/数据面对齐，并新增两侧已投影模型的有限行为比较；默认动态流程以固定参照模型和实际证据验证有限行为。

## 义务、候选与覆盖

`SemanticGenerator.generate_obligation_plan()` 生成：

- 策略义务、可动态验证的顺序关系义务，以及未实现关系的显式未完成项；
- 方向性行为切片：前序规则、共同生效指令及引用；
- 有限候选请求及实际选择路径；搜索失败仅表示 unknown，不证明不可达；
- eligible/ineligible/unknown 三态覆盖决策；只有 eligible 对应 W=1；
- 保留全部义务的覆盖规划及将来的资源影响范围。

通用复用规则 `same-effective-rule-observations/2` 允许已确认属于同一有效规则、满足各自触发条件的目标、请求 Header set/remove、响应 Header set、字面量 URI 改写及可观测选择关系共享探针。Header 删除必须先发出该字段；前缀改写保留未匹配后缀和查询参数，多个 OR 分支给出不同改写结果时不猜测。其他服务/路径不因同属 routing 被删除。遇到未知共同指令、跨 VS 选择歧义、未解析引用或未知共享策略范围时保守退回，不套用两两兼容推导。

支持 HTTP 精确/前缀路径、有限的普通 Header、方法和查询参数匹配。Host、伪 Header 和传输相关 Header 不套用普通 Header 规则。有限搜索不是完备求解器；正则等未支持条件显式阻止相关授权。当前每个规则寻找一个激活见证，不代表已枚举所有 OR 分支或所有边界。DR 按实际目标 Service 的规范化身份匹配，其他精确主机的 DR 不阻止本组规划；相关 DR 仍需受支持契约。通配主机、exportTo、workloadSelector、无法解释的 DR 范围和 EnvoyFilter 仍采用保守限制，不能理解为策略已通过或必然冲突。

2026-11-11 的多配置预跑发现：直接枚举所有同组规则的 Header/query 笛卡尔积，会因无关维度提前耗尽有限搜索额度。候选生成现先按目标规则约束构造输入，再尝试与同组规则条件的精确/前缀交集，最后保留原有限枚举。所有候选仍须经过完整规则选择与覆盖条件检查；构造出输入不等于已证明目标规则生效。遮蔽、正则、未知前提仍保留未完成义务，搜索也不因此变成完备求解器。

### 统计与状态策略的显式执行契约

`behavior_profiles.py` 新增 `controlled-whole-route-context/1`。它首先检查完整路由的指令集合、引用和共享策略范围，然后按实际触发阶段建立覆盖矩阵。预期权重、重试次数、超时和连接池参数来自固定模型；profiles 仅指定受控后端、请求和负载能力。它是实验用的有限白名单，不是任意服务的通用执行器，也没有改动默认 Web 的 Validator。

| 契约 | 当前准入范围与证据 | 复用约束 |
|---|---|---|
| split | 不含子集的独立 Service 加权转发；200–10000 个请求；完整目标回执；实际比例与配置比例绝对偏差不超过 0.12 | 批量请求可兼顾 Header/改写；基线的这些普通义务只各发一次请求，不复制整个统计批次 |
| retry-budget | 2 次重试、retryOn=5xx、perTryTimeout=250ms、总 timeout=500ms；受控后端先两次 503 后 200，另一个模式每次延迟 400ms | 恢复探针不能由超时探针替代；慢请求可同时判总超时与联合预算；用后端尝试事件去重，不能把两个采集点当成两次重试 |
| pool | 单个 DR 的 maxConnections=1、http1MaxPendingRequests=1，路由显式 attempts=0；16 请求并发且后端保持 500ms | 独立保留首次 503 不重试探针；饱和探针需要服务成功请求及 Envoy UO 响应标志或隔离集群 overflow 增量 |

pool 仅检验连接池饱和时能否产生请求溢出，**不证明阈值的每个边界，也不覆盖 outlierDetection 异常实例摘除**。网关默认可能不导出 overflow 计数器；实验在自己拥有的 VS 中加入 `%RESPONSE_FLAGS%` 响应头，用 UO 区分 Envoy 溢出和业务返回的 503。业务状态共享、子集继承、未知共同指令和不在上述参数范围内的组合仍保留未完成义务。实验条件和容差均写入计划，不能当作普适正确性保证。

profile 证据的每条 observation 表示一次逻辑探针，内含 `samples[]`：每个下游请求的唯一 request_id、实际响应、起止时间和多个 backend_receipts。采集器必须声明尝试事件完整，检查重复事件和跨运行归因；客户端取消后等待后端结束再释放状态。批量不足、代次不符、传输错误或证据缺失保持 INCONCLUSIVE。上述 `/1` 实验探针之间串行；探针内部的并发是触发分流/饱和的负载要求。

2026-11-06 增加可选 `configpilot.controlled-http-backend/2` 和 `parameterized-controlled-context/2`：重试范围为 attempts 1–3、perTryTimeout 250–600ms、总 timeout 恰为两倍 perTryTimeout。恢复模式失败次数、恢复/慢请求延迟均从冻结模型推导，写入带模型摘要的 stimulus；后端回执必须声明 `/2` 和相符的计划延迟。受控字段 `x-audit-request`、`x-test-mode`、`x-audit-delay`、`x-audit-failures` 不允许被被测规则改写，以免刺激与归因失真。旧 `/1` 契约和证据继续按旧范围检查。

`/2` 可以交由外部调度器并发执行，但计划本身不授予并发许可：必须另行检查完整运行的配置、状态、容量与证据隔离。连接池探针使用实际 DR 身份形成状态域，同池互斥保留到后端尝试结束；不同池在满足容量预算时可并发。多服务实验使用 `ObservationWait` 释放等待证据的线程，并保留资源预留。1 worker 也可在等待期间处理其他任务，不等于整个探针生命周期严格串行。

references 在本版主要支撑前提检查和切片，并未为所有资源引用分别建立完整动态关系义务；所有关系类型的完整覆盖仍是后续工作。

2026-11-06 增加可选 `resource_ids` 义务范围及 `parallel.plan_partitions()`、`parallel.evaluate_batch()`：分组继续读取完整模型，纯计算可用线程或进程。它们与配置/流量调度分离，未自动切换默认 Web 的执行模式。接口、证据隔离与 CPU 口径见 [并行边界](PARALLEL_VALIDATION.md)。

## 证据与结果

采集兼容、探针复用、并发兼容分别记录。当前没有自动合并原生 Envoy/Prometheus 采集会话，也没有放开同服务观测锁。

`evaluate_obligations()` 消费 `configpilot.obligation-evidence/1`：

```text
run_id + reference_model_hash
  observations[]:
    probe_id + probe_hash + execution_id + request_id
    sent_request + started_at + completed_at
    activation_confirmed
    backend_receipts[]:
      event_id + source_kind + request_id + observed_at
      backend_identity + request_headers + headers_complete
```

生产采集适配器需要真实提供这些信息；`activation_confirmed` 必须代表已确认当前执行配置生效，不能仅因发送了请求头就填 true。此版真实实验采用隔离后端回执和每次更新的代次响应头，不要求业务服务返回该 JSON，也没有将实验适配器假装成通用生产采集能力。

- 可信的错误目标判 FAIL，不因预期规则未命中而掩盖错误。
- 完整后端 Header 中缺少预期字段判 FAIL。
- 缺失、陈旧、跨运行、请求不符、探针不符或有歧义的证据判 INCONCLUSIVE。
- 目标不符时，路由可以 FAIL，而无法确认对应目的地的 Header 义务保持 INCONCLUSIVE。
- FAIL 和 PASS 都计为完成评估；INCONCLUSIVE 保留原因，不从义务集合删除。

## 使用

先重新运行静态分析，得到含关系模型的产物。若模型缺失或摘要不匹配，规划器报错，不回退到旧代表筛选。

```bash
python -m istio_Dynamic_Test.cmd.relations \
  --aligned results/consistency/aligned_semantic.json \
  --output-dir results/obligations/reuse
```

独立探针基准：

```bash
python -m istio_Dynamic_Test.cmd.relations \
  --aligned results/consistency/aligned_semantic.json \
  --output-dir results/obligations/independent --no-reuse
```

追加 `--evidence captured-evidence.json` 可输出逐义务判定。不传 `--execute` 时不发送探针。隔离执行入口可运行 `/2` 重试与连接池契约，通过后端行为触发，不修改 VS/DR；准备要求和兼容路径的执行限制见 [受控触发说明](CONTROLLED_STIMULUS_VALIDATION.md)。

受控契约入口追加 `--profiles profiles.json`，内容为列表，例如：

```json
[{"kind":"split", "rule_name":"tested", "backend_contract":"configpilot.controlled-http-backend/1", "samples":400,
  "request":{"host":"shop.example.com", "path":"/shop/item", "method":"GET", "headers":{}}}]
```

rule_name 必须唯一；也可使用完整 rule_id。没有对应契约的义务不会从覆盖分母消失。

产物：`probe_plan.json`、`validation_obligations.json`、`coverage_decisions.json`、`obligation_results.json`（提供证据时）。

## 验证

单元与接口回归：

```bash
python -m unittest istio_Dynamic_Test.tests.test_relational_planning \
  istio_Dynamic_Test.tests.test_behavior_profiles \
  istio_Dynamic_Test.tests.test_worker_scheduling \
  istio_Dynamic_Test.tests.test_grpc_protocol -q
```

真实 Envoy 验证应固定参照配置与验证义务，分别运行独立和复用计划，并比较逐义务结果、请求量、采集次数及执行时间。环境准备、配置传播和清理时间分别记录。

可复用的配置与契约模板见 [配置示例](../istio_Dynamic_Test/configs/relational_examples/README.md)。实验脚本、原始证据和评估报告在本地单独保存，不随源码发布。
