# 熔断与连接池验证逻辑及可观测性增强方案

## 验证框架（已实现）

- **response_flags=UO**：熔断最直接证据，LogEntry 已支持解析
- **CircuitBreakerEffectiveness**：RejectedRequests / TotalRequests
- **hey + -disable-keepalive**：熔断/连接池测试时禁用 keep-alive
- **Prometheus**：query_503_count、query_response_flags_uO
- **Gateway 日志合并**：采集 Gateway 日志并入 envoy_logs，供 CircuitBreakerValidator 解析 UO

---

## 一、当前验证逻辑

### 1. 熔断验证 (CircuitBreakerValidator)

**数据来源**：ExecutionResult (HTTP 状态码) + Envoy access log（含 Gateway 日志）+ Prometheus（可选）

| 维度 | 逻辑 | 判定 |
|------|------|------|
| **HTTP 错误率** | 503 数量、错误率、熔断有效性(Rejected/Total) | 有 503 且 error_rate > 10% → PASSED，否则 WARNING |
| **熔断行为** | 解析 Envoy 日志（含 Gateway）中的 response_flags=UO | UO 存在 → 熔断直接证据；连续错误 ≥ 5 次、503 快速失败 → 辅助指标 |
| **Prometheus** | query_503_count、query_response_flags_uO 交叉验证 | 与 Execution 503 偏差 ≤ 20% 或 UO > 0 → PASSED |

**Gateway 日志**：503 UO 出现在 Gateway 出站日志中，EnvoyCollector 已将 Gateway 日志合并进 `envoy_logs`，供 CircuitBreakerValidator 解析。

### 2. 连接池验证 (ConnectionPoolValidator)

**已实现**：`ConnectionPoolValidator` 已注册到 CompositeValidator。

| 维度 | 逻辑 | 判定 |
|------|------|------|
| **高负载** | 总请求 ≥ 50 且 policy_types 含 CONNECTION_POOL | 有 503 或 error_rate > 5% → PASSED |
| **连接相关错误** | 解析 Envoy 日志中的 503/0 状态码 | 有相关日志 → PASSED |

---

## 二、可观测性指标（Prometheus / Envoy）

### Istio 默认暴露的指标

| 指标 | 用途 |
|------|------|
| `istio_requests_total{response_code="503"}` | 503 请求数，熔断/故障注入验证 |
| `istio_requests_total` by response_code | 各状态码分布 |
| `istio_request_duration_milliseconds_*` | 延迟分布，快速失败检测 |
| `istio_tcp_connections_opened_total` | TCP 连接数（连接池相关） |

### Envoy 集群指标（需 proxyStatsMatcher 开启）

Istio 默认会过滤大部分 `envoy_cluster_*`，需在 IstioOperator 中配置：

```yaml
meshConfig:
  defaultConfig:
    proxyStatsMatcher:
      inclusionPrefixes:
        - "cluster.outbound"
      inclusionRegexps:
        - ".*circuit_breakers.*"
        - ".*upstream_cx_.*"
        - ".*upstream_rq_.*"
```

| 指标 | 含义 |
|------|------|
| `envoy_cluster_*.circuit_breakers.*.rq_open` | 熔断器打开时的请求数 |
| `envoy_cluster_*.circuit_breakers.*.rq_pending_open` | 熔断打开期间被拒绝的请求 |
| `envoy_cluster_*.upstream_cx_overflow` | 连接数超限（连接池） |
| `envoy_cluster_*.upstream_rq_pending_overflow` | 挂起请求超限 |
| `envoy_cluster_*.upstream_cx_active` | 当前活跃连接数 |
| `envoy_cluster_*.upstream_cx_total` | 累计建立连接数 |
| `envoy_cluster_*.upstream_cx_connect_fail` | 连接失败数 |

---

## 三、增强方案

### 方案 A：基于 istio_* 指标（无需改 Istio 配置）

1. **熔断**：查询 `sum(istio_requests_total{response_code="503"})` 增量，与 ExecutionResult 交叉验证
2. **连接池**：暂无直接指标，可保留日志分析或延后

### 方案 B：增加 Prometheus 采集器 + 验证器扩展

1. 在 `prometheus_utils.py` 增加：
   - `query_503_count(prom_url, service, namespace, start?, end?)`
   - `query_request_duration_p99(prom_url, service, ...)`
2. 在 CircuitBreakerValidator 中：
   - 若提供 `prometheus_url`，优先用 Prometheus 503 增量验证
   - 与 ExecutionResult 对比，偏差过大则 WARNING
3. 新建 ConnectionPoolValidator（可选）：
   - 若有 `envoy_cluster_*.upstream_cx_overflow`，则验证连接池溢出
   - 否则回退到“负载下错误率/连接失败”等间接指标

### 方案 C：直接读取 Envoy sidecar /stats

通过 `kubectl exec` 或 SSH 访问 Pod `:15090/stats/prometheus`，获取完整 Envoy 指标，包括熔断、连接池。实现成本较高，适合深度调试。

---

## 四、推荐实施顺序

1. **短期**：扩展 CircuitBreakerValidator，增加 Prometheus `istio_requests_total{response_code="503"}` 查询，与 execution 交叉验证
2. **中期**：新增 ConnectionPoolValidator，先基于现有数据（高并发下的 503/连接失败）做基础验证
3. **长期**：若需精确验证，配置 proxyStatsMatcher 暴露 Envoy 集群指标，再接入验证逻辑
