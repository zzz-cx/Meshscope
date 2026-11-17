# ConfigPilot 动态验证模块

动态验证通过义务生成、覆盖规划、受控执行和逐义务证据判定完成。总入口见 [根 README](../README.md)，完整模块边界见 [架构](../docs/ARCHITECTURE.md)。

```bash
python -m configpilot plan --aligned aligned_semantic.json --output-dir results/relational/plan
python -m configpilot evaluate --plan results/relational/plan/probe_plan.json --evidence evidence.json --output-dir results/relational/replay
```

执行需要已准备的真实代理路径、匹配的受控后端和代次响应头；执行器只在触发和证据条件明确时发送探针。

```bash
python -m configpilot dynamic --aligned aligned_semantic.json --profiles profiles.json --execute \
  --endpoint-url http://HOST:PORT --backend-control-url http://127.0.0.1:19490/ \
  --activation-headers activation.json --workers 4 --capacity 32 \
  --output-dir results/relational/run
```

可选 `--verify-config-versions` 会在执行前后只读采集实际 VS、DR、Gateway、Service 的 UID/RV/spec。没有开启时，静态代次头本身不能证明不存在未标记的外部变更；部署需由调用者冻结。

| 目录 | 职责 |
|---|---|
| `internal/planning/relational.py` | 策略与关系义务、保守覆盖、逐义务判定 |
| `internal/planning/behavior_profiles.py` | 分流、重试预算和小容量连接池显式契约 |
| `internal/planning/engine.py` | 索引闭包、Python 进程/可选 Go 预计算 |
| `internal/pipeline/scheduling/` | 共享读取、独占状态、容量预算与等待让出 |
| `internal/traffic/controlled.py` | 无配置写入的 HTTP 执行适配 |
| `internal/traffic/controlled_backend.py` | 一个进程多个目标端口、按请求触发与记录 |
| `internal/traffic/receipts.py` | 批量共享采集和持久化后的定向释放 |
| `internal/traffic/leases.py` | 同主机独立运行之间的入口/后端排他 |

`python -m istio_Dynamic_Test.cmd` 和 `.cmd.relations` 均为统一入口的兼容别名。矩阵兼容路径仅通过 `python -m configpilot legacy-dynamic -- ...` 或 `python -m istio_Dynamic_Test.cmd --legacy ...` 明确调用。gRPC transport、聚合 collector、fault 注入等保留为兼容能力，不表示受控 HTTP oracle 已覆盖所有协议和策略。



```bash
python -m unittest discover -s istio_Dynamic_Test/tests -v
```

当前可执行范围和未实现项见 [实现核对表](../docs/IMPLEMENTATION_STATUS.md)。
