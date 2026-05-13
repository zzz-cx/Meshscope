# Istio Dynamic Test Framework

Istio 配置动态验证框架 —— 通过真实流量验证 Istio 策略的运行时行为一致性。

## 架构概览

本框架采用 **四层流水线** 架构，将动态验证过程标准化为：

```
┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌───────────┐
│  Generator   │ ──▶ │ Executor │ ──▶ │ Collector │ ──▶ │ Validator │
│  (测试生成)   │     │ (流量执行) │     │ (数据采集)  │     │ (结果验证)  │
└─────────────┘     └──────────┘     └───────────┘     └───────────┘
     TestCase      ExecutionResult   CollectionResult  ValidationResult
```

### 核心优势

1. **扩展性强** —— 新增功能只需实现对应的 Generator / Executor / Collector / Validator
2. **代码复用率高** —— HttpExecutor 和 LoadExecutor 被所有策略复用
3. **统一数据模型** —— `TestCase → ExecutionResult → CollectionResult → ValidationResult` 贯穿全流程

---

## 动态验证流程详解

以 BookInfo 示例应用为目标，完整的动态验证流程如下：

### 第一步：解析 Istio 配置 → 生成测试用例

`ConfigGenerator` 读取集群中实际部署的 VirtualService 和 DestinationRule 配置，
基于**四维正交原则**自动生成测试用例矩阵：

```
Istio 配置                         生成的测试用例
┌──────────────────────┐           ┌─────────────────────────────────┐
│ VirtualService        │           │ case_001: 路由匹配 (header匹配) │
│   reviews:            │           │ case_002: 流量分割 80/20        │
│     header match      │    ──▶    │ case_003: 路由匹配 (另一服务)    │
│     weight 20/80      │           │ case_004: 重试策略              │
│   productpage:        │           │ case_005: 熔断+连接池+重试+路由  │
│     retries: 3        │           │           (正交组合)             │
│ DestinationRule       │           └─────────────────────────────────┘
│   outlierDetection    │
│   connectionPool      │
└──────────────────────┘
```

正交设计的四个维度：

| 维度 | 说明 | 示例 |
|------|------|------|
| 匹配条件正交 | 不同 header/path 条件组合 | `end-user: jason` → v2 |
| 功能策略间正交 | 同一请求路径中多策略不互斥 | fault + retry + timeout |
| 全局/局部策略正交 | VirtualService(局部) + DestinationRule(全局) | 路由 + 熔断组合 |
| 触发机制正交 | 不同生命周期阶段的策略可组合 | 入口触发 + 失败触发 + 负载触发 |

### 第二步：执行流量 + 故障注入

对于每个测试用例，`DynamicTester` 自动选择合适的执行器：

| 用例类型 | Executor | 故障注入方式 |
|----------|----------|-------------|
| 单次请求（路由匹配） | `HttpExecutor` (curl) | 无 |
| 负载测试（流量分割） | `MeshExecutor` (kubectl exec 从 Pod 内发请求) | 无 |
| 重试验证 | `HttpExecutor` | `FaultInjector` patch VS 注入 503 |
| 熔断验证 | `LoadExecutor` | `FaultInjector` 路由到不存在服务 |

> **流量分割为何用 MeshExecutor？** 内部服务（如 reviews）的 sidecar 日志只能从网格内请求触发。从 Ingress 发起的请求经 productpage 转发，reviews 的入站日志才能被正确采集。`MeshExecutor` 通过 `kubectl exec` 在 productpage Pod 内执行 curl，确保流量走网格内部路径。

故障注入的工作原理：
```
原始 VirtualService                    注入后
┌─────────────────────┐     patch     ┌─────────────────────────────┐
│ route:               │    ──────▶   │ route:                       │
│   - host: productpage│              │   - host: nonexistent (80%) │
│                      │              │   - host: productpage (20%) │
└─────────────────────┘              └─────────────────────────────┘
                                      测试完成后自动恢复原始配置
```

### 第三步：采集观测数据

执行结束后，`EnvoyCollector` 并行采集：

- **Envoy Sidecar 日志** — 从目标服务 Pod 的 `istio-proxy` 容器获取 access log
- **Gateway 日志** — 从 `istio-ingressgateway` 获取入口流量日志
- **HTTP 结果** — 直接从 Executor 的返回值获取状态码分布、响应时间等

### 第四步：多维度验证

`CompositeValidator` 根据用例的 `policy_types` 自动分发到对应的 Validator：

```
TestCase(policy_types=[circuit_breaker, retry, routing])
    │
    ├──▶ CircuitBreakerValidator  →  检查 503 错误率、连续错误模式
    ├──▶ RetryValidator           →  检查响应时间分布、错误后恢复
    └──▶ RoutingValidator         →  检查 HTTP 状态码、日志目标版本
    │
    └──▶ 综合判定：任一维度 PASS → 整体 PASS
```

每个 Validator 进行的具体检查：

| Validator | HTTP 维度 | 日志维度 |
|-----------|----------|---------|
| RoutingValidator | 2xx 状态码 | Envoy log 中目标 pod 版本匹配 |
| TrafficSplitValidator | — | 统计各版本请求数，与期望权重对比（含动态容错） |
| CircuitBreakerValidator | 503 数量 + 错误率 | 连续错误模式、快速失败检测 |
| RetryValidator | 成功率 | P95/P50 响应时间比（>3 表示有重试延迟） |
| FaultInjectionValidator | 故障状态码比例 | 故障请求数量 |

---

## 真实集群验证示例

### 测试环境

- **集群**：Kubernetes v1.28 + Istio 1.24.0
- **应用**：BookInfo（productpage-v1/v2, reviews-v1/v2/v3, details-v1, ratings-v1）
- **入口**：`http://192.168.92.131/productpage`（MetalLB LoadBalancer）

### 输入配置

```json
{
  "virtualServices": [
    {
      "name": "reviews-route",
      "spec": {
        "hosts": ["reviews"],
        "http": [
          { "match": [{"headers": {"end-user": {"exact": "jason"}}}],
            "route": [{"destination": {"host": "reviews", "subset": "v2"}}] },
          { "route": [
              {"destination": {"host": "reviews", "subset": "v1"}, "weight": 20},
              {"destination": {"host": "reviews", "subset": "v2"}, "weight": 80}
          ]}
        ]
      }
    },
    {
      "name": "productpage",
      "spec": {
        "hosts": ["productpage"],
        "http": [
          { "match": [{"headers": {"end-user": {"exact": "zcx"}}}],
            "route": [{"destination": {"host": "productpage", "subset": "v1"}}] },
          { "route": [{"destination": {"host": "productpage", "subset": "v2"}}],
            "retries": {"attempts": 3, "per_try_timeout": "2s"} }
        ]
      }
    }
  ],
  "destinationRules": [
    {
      "name": "productpage-dr",
      "spec": {
        "host": "productpage",
        "trafficPolicy": {
          "connectionPool": {"http": {"http1MaxPendingRequests": 1}, "tcp": {"maxConnections": 1}},
          "outlierDetection": {"consecutiveGatewayErrors": 5, "interval": "30s", "baseEjectionTime": "1m"}
        }
      }
    }
  ]
}
```

### 自动生成的测试用例

| case_id | 描述 | 类型 | 策略 |
|---------|------|------|------|
| case_001 | 路由匹配：`end-user: jason` → reviews-v2 | single_request | routing |
| case_002 | 流量分割：reviews v1(20%) / v2(80%) | load_test (62次) | traffic_split |
| case_003 | 路由匹配：`end-user: zcx` → productpage-v1 | single_request | routing |
| case_004 | 重试策略：注入 503 后验证重试行为 | single_request | retry |
| case_005 | 正交组合：熔断+连接池+重试+路由 | load_test (75次) | circuit_breaker, connection_pool, retry, routing |

### 验证结果

```
============================================================
  Istio 动态验证流水线
  用例数量: 5    入口URL: http://192.168.92.131/productpage
============================================================

[1/5] case_001: 正向匹配路由测试 for host 'reviews'
  [PASS] [routing] HTTP状态码: 200
  [PASS] [routing] 路由目标: 目标版本 v2 已命中
  => PASSED    0.310s

[2/5] case_002: 流量分割测试 reviews v1(20%)/v2(80%)
  [PASS] [traffic_split] 流量分布: v1 21.0%, v2 79.0% (期望 20/80, 容差 ±10%)
  HTTP: 62 次全部 200    avg 0.191s
  => PASSED

[3/5] case_003: 正向匹配路由测试 for host 'productpage'
  [PASS] [routing] HTTP状态码: 200
  [PASS] [routing] 路由目标: 目标版本 v1 已命中
  => PASSED    0.169s

[4/5] case_004: 重试策略测试 for host 'productpage'
  注入故障: patch VS 'productpage' 注入 HTTP 503
  [PASS] [retry] HTTP状态码: 成功率 100%（重试后恢复）
  清理故障: 恢复原始 VS 配置
  => PASSED    0.392s

[5/5] case_005: 正交组合测试 (熔断+连接池+重试+路由)
  注入故障: 上游错误 80%（路由到不存在服务）
  [PASS] [circuit_breaker] HTTP错误率: 503×51, 200×24, 错误率 68.0%
  [PASS] [retry]           HTTP状态码: 成功率 32.0%
  [PASS] [routing]         HTTP状态码: 503×51, 200×24
  清理故障: 恢复原始 VS 配置
  => PASSED    0.229s avg

============================================================
  流水线完成    耗时: 25.8s
  通过: 5    失败: 0    通过率: 100%
============================================================
```

### 结果分析

| case_id | 状态 | 关键发现 |
|---------|------|---------|
| case_001 | **PASS** | header `end-user: jason` 正确路由到 reviews-v2，Envoy 日志确认命中 |
| case_002 | **PASS** | 使用 `MeshExecutor` 从 productpage Pod 内发起请求，采集 reviews sidecar 入站日志；`EnvoyLogParser` 过滤出站调用后统计分布，v1/v2 实测 21%/79% 符合 20/80 配置 |
| case_003 | **PASS** | header `end-user: zcx` 正确路由到 productpage-v1 |
| case_004 | **PASS** | 注入 503 故障后，最终请求仍返回 200，说明 Istio 重试机制（3次, 2s/次）成功恢复 |
| case_005 | **PASS** | 注入 80% 上游错误后，实际观测到 68% 的 503（51/75），与配置的 80% 误差可接受（部分请求在故障生效前完成）。熔断 + 重试 + 路由三个维度均通过 |

---

## 目录结构

```
istio_Dynamic_Test/
│
├── main.py                          # DynamicTester 统一流水线入口
│
├── models/                          # 统一数据模型
│   └── test_case.py                 # TestCase, ExecutionResult, CollectionResult, ValidationResult
│
├── generators/                      # 第一层：测试用例生成
│   ├── base.py                      # BaseGenerator (ABC)
│   ├── config_generator.py          # 从 Istio 配置文件生成正交测试用例
│   └── test_case_generator.py       # 核心正交测试矩阵生成逻辑
│
├── executors/                       # 第二层：流量执行
│   ├── base.py                      # BaseExecutor (ABC)
│   ├── http_executor.py             # 单次 HTTP 请求 (curl)
│   ├── load_executor.py             # 负载测试 (hey / 批量 curl 自动回退)
│   ├── mesh_executor.py             # 网格内请求 (kubectl exec 从 Pod 内发 curl，用于流量分割)
│   └── fault_injector.py            # 故障注入 (patch VirtualService)
│
├── collectors/                      # 第三层：数据采集
│   ├── base.py                      # BaseCollector (ABC)
│   ├── envoy_log_collector.py       # Envoy access log + Gateway 日志采集
│   └── prometheus_collector.py      # Prometheus 指标采集
│
├── validators/                      # 第四层：结果验证
│   ├── base.py                      # BaseValidator (ABC)
│   ├── routing_validator.py         # 路由匹配验证
│   ├── traffic_split_validator.py   # 流量分割验证（含动态容错）
│   ├── circuit_breaker_validator.py # 熔断策略验证
│   ├── retry_validator.py           # 重试策略验证
│   ├── fault_injection_validator.py # 故障注入验证
│   ├── rate_limit_validator.py      # 限流验证（429 / 日志 / Prometheus）
│   ├── composite_validator.py       # 组合验证器（按策略自动分发）
│   └── report_generator.py          # JSON / TXT 报告生成
│
├── configs/                         # 配置文件
│   └── istio_config.json            # Istio VirtualService / DestinationRule 配置
│                                    # （可通过 --control-plane-config 从控制面同步更新）
│
├── utils/                           # 工具模块
│   ├── ssh_utils.py                 # SSH 客户端（自动检测本地/远程环境）
│   ├── log_parser.py                # Envoy access log 解析器
│   ├── envoy_log_utils.py           # Envoy access log 启用工具
│   ├── pod_log_utils.py             # Pod 日志获取
│   ├── prometheus_utils.py          # Prometheus 查询客户端
│   ├── env_detector.py              # K8s 环境检测
│   ├── trace_utils.py               # 链路追踪工具
│   └── trace_to_deps.py             # trace → 服务依赖
│
├── scripts/                         # Shell 测试脚本（可独立使用）
│
└── results/                         # 测试结果输出
    ├── envoy_logs/                  # Envoy sidecar + Gateway 日志
    ├── http_results/                # HTTP 状态码 / 响应时间
    └── reports/                     # JSON + TXT 验证报告
```

## 快速开始

### 方式 1: 编程调用（推荐）

```python
from istio_Dynamic_Test.main import DynamicTester
from istio_Dynamic_Test.generators import ConfigGenerator
from istio_Dynamic_Test.collectors import EnvoyCollector
from istio_Dynamic_Test.validators import CompositeValidator

tester = DynamicTester(
    generator=ConfigGenerator(
        "istio_Dynamic_Test/configs/istio_config.json",
        service_deps_path="istio_Dynamic_Test/service_dependencies.json",
        ingress_url="http://192.168.92.131/productpage",
    ),
    collector=EnvoyCollector(namespace="default"),
    validator=CompositeValidator(),
)

results = tester.run()
```

### 方式 2: CLI

```bash
# 从 Istio 配置生成并执行（默认会从控制面配置目录同步最新 VS/DR）
python -m istio_Dynamic_Test.main \
    -i istio_Dynamic_Test/configs/istio_config.json \
    --ingress-url http://192.168.92.131/productpage \
    --service-deps istio_Dynamic_Test/service_dependencies.json

# 指定控制面配置目录（istio_config_parser 解析输出）
python -m istio_Dynamic_Test.main \
    -i istio_Dynamic_Test/configs/istio_config.json \
    --control-plane-config istio_config_parser/istio_monitor/istio_control_config \
    --ingress-url http://192.168.92.131/productpage

# 从旧版矩阵文件执行
python -m istio_Dynamic_Test.main --matrix output_matrix.json

# 只运行单个用例
python -m istio_Dynamic_Test.main --matrix output_matrix.json --single-case case_005

# SSH 远程执行
python -m istio_Dynamic_Test.main \
    --matrix output_matrix.json \
    --ssh-host 192.168.92.131 --ssh-user root --ssh-password xxx
```

## 限流（Rate Limit）验证

已内置 `RateLimitValidator`，并在 `CompositeValidator` 中注册 `PolicyType.RATE_LIMIT`。

### 启用方式

1. 在 `istio_config.json` 的 `enabled_policies` 中设置 `"rate_limit": true`（且存在 `envoyFilters` 等限流配置时，推断亦为 true）。
2. `TestCaseGenerator` 会在矩阵末尾追加 **2 条最小正交用例**：低压基线（期望极少 429）与突发高压（期望出现 429）。可通过同一 `enabled_policies` 下的可选参数微调：
   - `rate_limit_baseline_requests`、`rate_limit_baseline_max_429`
   - `rate_limit_over_requests`、`rate_limit_over_concurrency`、`rate_limit_min_429`
3. CLI 建议传入 `--prometheus-url`，以便与 `istio_requests_total{response_code="429"}` 交叉验证；Executor 使用 `LoadExecutor`（`load_test`）。

### 期望结构 `expected_outcome.rate_limit`

| `mode` | 含义 |
|--------|------|
| `should_pass_all` | 429 ≤ `max_429`（默认容差见 `epsilon_abs`） |
| `should_see_limits` | 429 ≥ `min_429`；可选 `allow_503_as_throttle: true` 时也可用 503 计数满足 `min_429`（慎用，见下文） |
| `proportion` | `allowed_budget` 与总请求数推导「应被拒」；默认可用 `429+503`（若 `allow_503_as_throttle`），`proportion_429_only: true` 则只算 429 |

未配置 `rate_limit` 字段但策略含限流时，验证器使用简单启发式（高压应见 429、低压应极少 429）。`RoutingValidator` 在组合 `routing`+`rate_limit` 时将 **429 视为合法响应**（与 2xx 并列），避免高压用例被误判为路由失败。

### 为何压测只见 503、不见 429？（限流与熔断/连接池耦合）

在同一服务上若 **DestinationRule** 把连接池压得很小（例如 `maxConnections: 1`、`http1MaxPendingRequests: 1`）并开启 **outlierDetection**，并发稍大时 **连接池溢出（response_flags=UO）或熔断** 往往**先于** Envoy `local_ratelimit` 的 **429** 生效，客户端看到的主要是 **503**。这不是「限流没配上」，而是**拒绝链路的优先级**问题：池化/熔断与本地限流在观测上耦合，单靠 HTTP 状态码很难只证「限流」一条策略。

**建议的验证策略：**

1. **隔离验证**：单独挑一个**只有** EnvoyFilter 本地限流、**无**激进 `connectionPool`/`outlierDetection` 的 host/service 做动态用例；或临时放宽 bookinfo `productpage` 的 DR 再测限流。
2. **观测区分**：结合 Envoy access log / Prometheus（429 计数、`envoy_http_ratelimit_*`、与 503+UO 对比）判断拒绝来源。
3. **期望放宽（慎用）**：在 `expected_outcome.rate_limit` 中设置 `allow_503_as_throttle: true` 时，`should_see_limits` 可把 **503 数量**也计入「有拒绝」（默认仍以 429 为准）；**proportion** 模式下可将 `429+503` 作为拒绝数（除非设 `proportion_429_only: true`）。仍建议配合日志甄别，避免把熔断误判为限流。

## 数据模型

所有层之间通过统一的数据模型交互：

| 数据类 | 产生者 | 消费者 | 说明 |
|--------|--------|--------|------|
| `TestCase` | Generator | Executor, Collector, Validator | 测试用例定义 |
| `TestSuite` | Generator | DynamicTester | 测试套件（含全局配置） |
| `ExecutionResult` | Executor | Validator | HTTP 执行结果 |
| `CollectionResult` | Collector | Validator | 观测数据（日志 / 指标） |
| `ValidationResult` | Validator | ReportGenerator | 验证结论 |
| `PipelineResult` | DynamicTester | ReportGenerator | 完整流水线结果 |

## 支持的 Istio 策略

| 策略类型 | Generator | Executor | Collector | Validator |
|----------|-----------|----------|-----------|-----------|
| 路由匹配 | ConfigGenerator | HttpExecutor | EnvoyCollector | RoutingValidator |
| 流量分割 | ConfigGenerator | MeshExecutor | EnvoyCollector | TrafficSplitValidator |
| 故障注入 | ConfigGenerator | HttpExecutor + FaultInjector | EnvoyCollector | FaultInjectionValidator |
| 熔断 | ConfigGenerator | LoadExecutor + FaultInjector | EnvoyCollector | CircuitBreakerValidator |
| 重试 | ConfigGenerator | HttpExecutor + FaultInjector | EnvoyCollector | RetryValidator |
| 限流 | ConfigGenerator（`enabled_policies.rate_limit`） | LoadExecutor | EnvoyCollector（+ 可选 Prometheus） | RateLimitValidator |
| 正交组合 | ConfigGenerator | Auto-select | EnvoyCollector | CompositeValidator |
