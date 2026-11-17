# 动态验证 worker 调度

2026-11-16：本文主要记录矩阵兼容调度。受控执行工作流使用 `--workers`、`--capacity`、请求级共享采集及独立状态预留，见 [整体架构](ARCHITECTURE.md)。

2026-11-11 更新：默认代码不再通过 VS 注入执行重试及连接池/异常摘除验证；缺少受控能力时返回 INCONCLUSIVE。下述连接池旧分阶段注入说明属于历史调度设计，新的隔离触发与执行入口见 [受控触发说明](CONTROLLED_STIMULUS_VALIDATION.md)。

用例并发由 `DYNAMIC_TEST_MAX_WORKERS` 控制，使用线程池。配置示例：

```bash
export DYNAMIC_TEST_MAX_WORKERS=4
export DYNAMIC_TEST_EVENT_WAIT=1
export DYNAMIC_TEST_MAX_INFLIGHT=16
python -m configpilot legacy-dynamic -- --matrix /path/to/matrix.json --namespace demo
```

`MAX_WORKERS` 是同时执行 Python 阶段的线程数；`MAX_INFLIGHT` 是已预留资源、正在执行或等待观测的用例总数上限，默认 worker 数的 4 倍。事件等待默认在 worker > 1 时开启。单 worker 保持串行语义；`DYNAMIC_TEST_EVENT_WAIT=0` 可关闭事件等待用于对照测试。

## 资源与观测约束

- 读取当前 VirtualService 清单，按目标服务关联实际配置资源。多个用例可以共享读取同一 VS。
- 只有执行器确实会注入故障时才声明对应 VS 的写访问，不再仅凭熔断、重试、超时等策略标签加入口写锁。
- 写访问与该资源的读/写访问互斥，覆盖从准备、注入到观测、恢复的完整用例周期。
- 同服务观测互斥同时支持普通服务名和合成服务名，并归一化短名与 FQDN，键包含命名空间。
- 对会产生下游流量的用例，可在矩阵用例顶层声明额外观测服务：

```json
{
  "case_id": "case_001",
  "request_params": {"host": "productpage"},
  "observation_services": ["reviews.demo.svc.cluster.local", "ratings.demo.svc.cluster.local"]
}
```

默认仅知道目标服务，不能自动推断完整业务调用链。运行跨服务用例时，应声明可能污染的下游观测范围。

VS 清单读取失败时，使用保守的清单读写互斥；需要故障注入的路径无法确认目标资源时会报错，不猜测资源后写入。连接池恢复和历史故障 bundle 同样进入统一资源调度。

## 等待不占 worker

待运行队列先原子预留所有访问资源，再将用例交给线程池。锁冲突的用例留在队列中，后面的独立用例可先执行；后来的冲突读者不会一直抢在已有写者前面。

普通观测等待、连接池恢复等待和 bundle 等待以单调时钟截止时间登记。等待期间释放执行线程，但保留用例的资源预留，避免其他流量或故障污染观测。截止后重新进入线程池采集、校验、恢复，再释放预留。

因此 4 个线程可以承载多于 4 个在途等待用例，但最多只有 4 个执行阶段同时运行。单个用例仍可以在内部使用 hey 或请求线程池，这与用例 worker 数是不同的并发层。

## 请求标签和指标隔离的边界

`DYNAMIC_TEST_TRACE_HEADER=1` 会为未自行提供标签的请求增加每次运行唯一的 `x-configpilot-case-id` 请求头，用于关联和后续接入日志/遥测。它默认关闭，不覆盖已有标签。

标准 Istio Prometheus 请求计数器没有这个用例维度；本改动没有安装 Telemetry/EnvoyFilter，也没有把请求头直接当作已经存在的指标标签。因此不会因请求头不同而放开同服务观测锁。要安全支持同服务并行，需要另外配置指标维度、按用例过滤查询，并验证真实导出与查询结果；不能仅传一个 `isolated=true` 标记跳过互斥。

同服务互斥也不保证固定的观测 sleep 一定覆盖 Prometheus 抓取延迟或排除先前用例延迟到达的指标。完整归因仍需要样本新鲜度判定或真正的用例指标标签。本改动保留原等待时长与验证逻辑。

资源预留是单次运行内的进程内机制，不是跨进程/跨主机的分布式锁。不要在同一集群观测范围内同时启动互不协调的验证进程。

新的可选进程后端仅处理不可变关系模型的分组规划和已采集证据的判定，不直接执行配置写入或流量，不绕开这些进程内预留。受控请求级证据实验与生产观测锁的边界见 [验证规划与执行的并行边界](PARALLEL_VALIDATION.md)。

## 查看是否真正用上多个 worker

`tester.scheduler_stats` 和 `[SCHED]` 日志包含：

- `peak_busy_workers`：实际同时运行阶段的线程峰值。
- `max_running`：调度器中尚未处理完成通知的阶段 Future 数峰值。
- `max_inflight`：含等待任务的资源预留数峰值。
- `deferred_waits`：转为到期任务的等待次数。
- `lock_blocked_checks`：发现资源冲突的次数，不是锁等待秒数。
- `events`：每条用例的资源键、启动/结束时间和等待次数。

当只剩一个 12 秒的观测窗口时，其他 worker 空闲是正常的；增加 worker 或提前释放同服务锁不会让指标更快到达，也可能使结果失真。

验证命令：

```bash
python -m unittest istio_Dynamic_Test.tests.test_worker_scheduling istio_Dynamic_Test.tests.test_grpc_protocol -v
```
