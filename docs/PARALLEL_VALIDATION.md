# 验证规划与执行的并行边界

2026-11-16：主入口新增 `--compute-backend serial|thread|process|go`，该选项控制索引化依赖闭包预计算，后续全局规划仍在 Python 中执行；下述 `parallel.plan_partitions/evaluate_batch` 是完整分组计算接口，两者不要混为同一计时口径。流量并行使用 `--workers` 和 `--capacity`，使用统一 CLI 参数，矩阵兼容路径的环境变量不控制该工作流。见 [整体架构](ARCHITECTURE.md)。

验证规划、流量执行、证据判定是不同阶段。流量 worker 使用现有线程就绪队列；无配置冲突且具备可信证据隔离时，可以重叠网络等待。纯 Python 规划与判定可使用新增的可选进程后端，是否更快需要实测启动、序列化、结果传回与计算成本。

## 完整模型上的分组规划

`plan_obligations(..., resource_ids=[...])` 仅限制本组生成的义务来源，继续读取完整参照模型。前序规则、竞争 VS、DR、EnvoyFilter、未解析引用仍参与判断，不能先删掉其他资源再声称独立。

`parallel.plan_partitions()` 接受带 `job_id`、`resource_ids` 的分组，可选 `profiles` 指定该组的受控行为契约，支持 `serial`、`thread`、`process`。使用进程时，每个 worker 初始化完整模型，按任务选择义务范围。调用方须让目标范围完整、互不重复，并校验生成的义务并集；分组不代表跨组运行许可。

```python
from istio_Dynamic_Test.internal.planning.parallel import plan_partitions, evaluate_batch

# model 是 parser 产出的完整 relational_model。
targets = sorted({p['resource_id'] for p in model['policies']})
jobs = [{'job_id': resource, 'resource_ids': [resource]} for resource in targets]
plans = plan_partitions(model, jobs, backend='process', max_workers=2)

# evidence_jobs 中每项有 job_id、plan、evidence；证据先由受约束的执行器采集。
results = evaluate_batch(evidence_jobs, backend='process', max_workers=2,
                         chunksize=16)
```

进程后端采用 spawn。独立脚本应在 `if __name__ == '__main__':` 保护内调用。函数保持输入顺序，要求唯一 job_id，工作任务失败会向调用方抛错；不会把异常当作 PASS。

## 配置和外部状态仍由一个调度器管理

`run_ready_cases()` 在交给线程池前原子预留资源。读配置可共享；配置写入与对应读写互斥。冲突任务留在队列，不占工作线程；执行、等待及恢复期间保留必要的资源预留。新进程后端仅执行不可变模型/证据上的计算，不直接发流量或修改集群，因此不会绕开进程内资源锁。

默认业务流程仍使用原有 worker 和观测锁。新接口没有自动把 Web 流程切换为多进程，也没有自动释放同服务观测互斥。

## 请求级归因的实验许可

大规模实验调用真实就绪队列，并使用受控 HTTP 后端接入模型生成的探针。该后端提供唯一请求 ID、实际 Service 身份、完整请求 Header、路径和时间窗口；实验前用两个真实并发请求验证回执能够分别归因，运行后继续逐项检查。

只有闭合的无共享状态路由/Header/改写配置获得请求级观测许可。粗粒度对照仍锁住整个后端 Service；配置写控制组仍持有 VS 的写锁，直到恢复并确认数据面就绪。不能把本实验的请求回执能力推广成标准 Prometheus 已有用例维度，也不能据此解除连接池、限流、重试预算或实例摘除的共享状态约束。

## 时间与 CPU 口径

- 实际执行耗时单列；解析、规划、判定、配置就绪和文件写入分别记录。
- 客户端平均使用核心数 = 客户端与已回收工作子进程的 user+system CPU 秒 / 墙钟秒。1.0 表示平均占用一个逻辑 CPU。
- 受控后端单独运行、单独计 CPU；真实 Envoy 位于另一个节点，不计入客户端 CPU。全机每核忙碌率另列，不能替代进程归因。
- CPU 阶段停止流量后比较 1/2/4 线程与 1/2/4 进程，包含进程启动、模型传输和结果回传成本。
- 真实证据的重复回放仅用于稳定吞吐测量，不计作新增独立准确性试验。

实验脚本、原始证据和性能评估报告在本地单独保存，不随源码发布。
