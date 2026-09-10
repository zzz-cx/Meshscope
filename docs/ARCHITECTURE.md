# MeshScope 系统设计

ConfigPilot（`python -m configpilot`）是统一入口。三个模块只通过落盘产物通信，不要在 checker 或动态模块里再解析 YAML。

## 模块边界

```text
采集 (istio_monitor)
        │  控制面 YAML + Envoy dump
        ▼
parser (istio_config_parser)
        │  aligned_semantic.json
        │  · pairs / expected_tuples
        │  · conflicts
        │  · graph_data（静态资源图）
        ▼
动态验证 (istio_Dynamic_Test)          checker (consistency_checker)
  期望只取 matched /                     读对齐产物 + 动态结果
  partial_matched 元组                    不做 YAML 解析
  无产物则报错，不回退                    出报告 + 三层图 + Web
```

| 模块 | 可以做 | 不可以做 |
|------|--------|----------|
| parser | 读快照、对齐语义元组、跨资源冲突、写出静态图 | 发流量 |
| 动态验证 | 用对齐元组生成期望、发流量、采观测 | 解析 YAML / 回退 `istio_config.json` |
| checker | 读产物、判定一致性、生成三层图和页面 | 再走一遍 parser |

## 数据产物

主对齐文件：`results/consistency/aligned_semantic.json`

| 字段 | 含义 |
|------|------|
| `pairs` | 按服务 × 功能的控制面 / 数据面对齐（含声明式 raw_config 与数据面规则） |
| `expected_tuples` | `matched` / `partial_matched` 的语义元组，供动态期望使用 |
| `conflicts` | VS 缺 subset、路由优先级、Gateway 选择器等跨资源冲突 |
| `graph_data` | 静态资源图：服务节点带 namespace、declarative、data_plane_rules；VS/DR/EF/Gateway 为资源节点 |
| `summary` | 服务数、功能对齐数、冲突数 |

语义元组形态：`S = ⟨predicate, action, scope, constraint⟩`，控制面与数据面投影到同一套结构再比较。

## Web UI

启动：`python -m configpilot web --port 8080`

样式对齐 Kiali / PatternFly 深色控制台（灰底、细边框、语义色表示状态），不做霓虹光晕。

| 页 | 数据 | 交互 |
|----|------|------|
| 总览 | `configpilot.json`、连通探测 | 改集群 / 可观测地址并写回配置 |
| 静态分析 | `POST /api/static/analyze` → parser | 按命名空间分列；点服务看声明式 YAML 与 Envoy 规则；点 VS/DR/EF 看资源及关联服务的数据面 |
| 动态验证 | 对齐模型 → 测试矩阵 | 生成矩阵、执行用例 |
| 一致性 | 静/动产物 | 生成三层图、刷新报告 |
| 三层依赖图 | `/api/three_layer_graph/latest` | 搜索、邻域、路径、仅看不一致、Exp 虚线 / Obs 实线权重 |

三层模型说明见 [THREE_LAYER_GRAPH.md](THREE_LAYER_GRAPH.md)。

## 推荐命令

```bash
python -m configpilot collect --vm-host HOST --vm-user root --vm-password PASS
python -m configpilot static --namespace default
python -m configpilot dynamic -- --from-control-plane --ingress-url http://HOST:PORT/productpage
python -m configpilot check --namespace default
python -m configpilot web --port 8080
python -m configpilot run --namespace default
```

底层模块入口仍然可用，见根目录 [README.md](../README.md)。

## 动态验证流水线（模块内部）

```text
testcase → traffic → telemetry → validation
```

`validation` 只消费执行 / 采集结果，不 import `traffic`。正交原则（匹配条件、功能策略、全局/局部、触发时机）仍由 `istio_Dynamic_Test` 负责压缩用例，期望值来自对齐元组而不是再读 YAML。
