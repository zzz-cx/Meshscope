# Istio 动态测试框架

Istio 动态测试框架是一个全面的自动化测试系统，用于验证 Istio 服务网格配置的正确性和一致性。通过自动化生成测试用例、驱动流量、收集指标和验证结果，确保微服务治理策略的有效性。

## 📋 项目概述

本框架提供了从测试用例生成到结果验证的完整动态测试流程，支持多种 Istio 策略的自动化验证：

- **路由匹配验证**：检查请求是否正确路由到期望的服务版本
- **流量分布验证**：验证权重分流配置是否生效
- **故障注入验证**：测试故障注入策略的行为
- **熔断器验证**：验证熔断策略的触发和恢复
- **重试策略验证**：检查重试机制的有效性
- **限流策略验证**：验证速率限制配置

## 🚀 快速开始

### 前置要求

- Python 3.8+
- Kubernetes 集群（带有 Istio）
- SSH 访问权限到集群节点
- 已部署的示例应用（如 BookInfo）

### 基本使用流程

```bash
# 1. 生成测试用例矩阵
cd generator
python test_case_generator.py -c istio_config.json -o ../output_matrix.json

# 2. 执行测试流量
cd ../checker
python traffic_driver.py -i ../output_matrix.json \
  --ssh-host 192.168.92.131 --ssh-user root --ssh-password password

# 3. 验证测试结果
cd ../verifier
python main_verifier.py --matrix ../output_matrix.json \
  --logs ../recorder/logs --output ./reports

# 4. 查看测试报告
open ./reports/comprehensive_report.html
```

## 📁 项目结构

```
istio_Dynamic_Test/
├── generator/              # 测试用例生成器
│   ├── test_case_generator.py    # 主生成器
│   ├── istio_config.json         # Istio配置文件
│   └── __init__.py
├── checker/                # 测试执行与检查
│   ├── traffic_driver.py         # 流量驱动器
│   ├── fault_injector.py         # 故障注入器
│   └── __init__.py
├── recorder/               # 数据收集器
│   ├── envoy_log_collector.py    # Envoy日志收集
│   ├── prometheus_collector.py   # 指标收集
│   ├── jaeger_trace_collector.py # 链路追踪收集
│   └── __init__.py
├── verifier/               # 结果验证器
│   ├── main_verifier.py          # 主验证程序
│   ├── log_parser.py             # 日志解析器
│   ├── behavior_model.py         # 行为模型
│   ├── result_comparator.py      # 结果比较器
│   ├── report_generator.py       # 报告生成器
│   └── __init__.py
├── utils/                  # 工具模块
│   ├── ssh_utils.py              # SSH工具
│   ├── envoy_log_utils.py        # Envoy日志工具
│   ├── istio_global_config.py    # Istio配置工具
│   └── __init__.py
├── scripts/                # 测试脚本
│   ├── route_match.sh            # 路由匹配测试
│   ├── weight_split.sh           # 权重分流测试
│   ├── circuit_breaker.sh        # 熔断测试
│   └── ...
├── test/                   # 测试用例
├── results/                # 测试结果
├── output_matrix.json      # 测试矩阵文件
├── service_dependencies.json    # 服务依赖关系
└── README.md
```

## 🔄 完整测试流程

### 阶段 1：配置分析与用例生成

**目标**：解析 Istio 配置文件，生成标准化的测试用例矩阵

```bash
cd generator
python test_case_generator.py \
  --config istio_config.json \
  --deps ../service_dependencies.json \
  --output ../output_matrix.json \
  --ingress-url http://192.168.92.131:30476/productpage
```

**生成的测试用例类型**：
- **路由匹配用例**：基于 VirtualService 的 match 规则生成正向测试
- **流量分布用例**：基于权重配置计算所需请求数量，生成负载测试
- **故障注入用例**：结合重试/熔断策略，生成故障模拟测试
- **性能验证用例**：基于连接池/限流配置，生成并发测试

**输出文件**：`output_matrix.json`
```json
{
  "global_settings": {
    "ingress_url": "http://192.168.92.131:30476/productpage"
  },
  "test_cases": [
    {
      "case_id": "case_001",
      "description": "正向匹配路由测试 for host 'reviews'",
      "type": "single_request",
      "request_params": {
        "host": "reviews",
        "headers": {"user-agent": "jason"}
      },
      "expected_outcome": {
        "destination": "v2"
      }
    }
  ]
}
```

### 阶段 2：流量驱动与数据收集

**目标**：根据测试矩阵执行实际的网络请求，自动收集相关日志和指标

```bash
cd checker
python traffic_driver.py \
  -i ../output_matrix.json \
  --ssh-host 192.168.92.131 \
  --ssh-user root \
  --ssh-password 12345678 \
  --namespace default
```

**执行过程**：

1. **预处理阶段**
   - 解析测试矩阵，识别所有目标服务
   - 为相关服务启用 Envoy access log
   - 根据需要注入故障策略

2. **流量生成阶段**
   ```bash
   # 单次请求示例
   curl -s -H "Host: reviews" -H "user-agent: jason" http://192.168.92.131:30476/productpage
   
   # 负载测试示例
   hey -n 62 -c 1 -H "Host: reviews" http://192.168.92.131:30476/productpage
   ```

3. **日志收集阶段**
   - 收集 Envoy access logs
   - 收集 Prometheus 指标
   - 收集 Jaeger 链路追踪数据

**输出文件**：
- `recorder/logs/case_001_reviews-v2-*.log`：Envoy 访问日志
- `recorder/metrics/case_001_metrics.json`：性能指标
- `recorder/traces/case_001_traces.json`：链路追踪数据

### 阶段 3：结果解析与验证

**目标**：分析收集的数据，验证实际行为是否符合预期配置

```bash
cd verifier
python main_verifier.py \
  --matrix ../output_matrix.json \
  --logs ../recorder/logs \
  --output ./reports
```

**验证逻辑**：

1. **行为建模**
   ```python
   # 定义期望行为
   expected = ExpectedBehavior(
       test_type=TestType.TRAFFIC_SPLIT,
       policy_type=PolicyType.ROUTING,
       target_distribution={'v1': 0.8, 'v3': 0.2},
       tolerance=0.1
   )
   ```
2. **日志解析**
   ```python
   # 解析 Envoy access log
   log_entry = parser.parse_log_entry(
   '[2024-01-15T10:30:45.123Z] "GET /productpage HTTP/1.1" 200 - 0 4421 45 44 "192.168.1.100" "curl/7.68.0" "uuid" "reviews:9080" "10.244.0.15:9080"'
   )
   ```

3. **结果比较**
   ```python
   # 权重分布验证
   result = comparator.verify_traffic_distribution(
       actual_counts={'v1': 48, 'v3': 14},
       expected_weights={'v1': 0.8, 'v3': 0.2},
       tolerance=0.1
   )
   ```

**验证类型**：
- **路由验证**：检查请求是否路由到正确的服务版本
- **权重验证**：统计流量分布，验证是否符合配置权重
- **故障验证**：检查故障注入是否按预期生效
- **性能验证**：验证响应时间、成功率等指标

### 阶段 4：报告生成与结果展示

**目标**：生成可视化的测试报告，提供详细的验证结果

**输出格式**：

1. **HTML 报告**：`reports/comprehensive_report.html`
   - 可视化的测试结果仪表板
   - 交互式图表和统计信息
   - 详细的错误分析和建议

2. **JSON 报告**：`reports/detailed_results.json`
   - 完整的机器可读数据
   - 适合集成到 CI/CD 流水线

3. **文本摘要**：`reports/summary.txt`
   ```
   ===== 测试结果摘要 =====
   总测试用例: 5
   通过: 4 (80.0%)
   失败: 1 (20.0%)
   警告: 0 (0.0%)
   跳过: 0 (0.0%)
   
   失败用例详情:
   - case_002: 权重分布验证失败 (偏差: 15.2%)
   ```

## 🛠️ 核心模块详解

### Generator - 测试用例生成器

**功能**：智能解析 Istio 配置，生成精准的测试用例

**主要特性**：
- 支持 VirtualService、DestinationRule 解析
- 自动计算权重分流所需的统计学样本大小
- 基于服务依赖关系生成故障注入用例
- 根据连接池配置调整并发度

**使用示例**：
```python
from generator.test_case_generator import TestCaseGenerator

generator = TestCaseGenerator(
    config_path='istio_config.json',
    service_deps_path='service_dependencies.json'
)
test_cases = generator.generate()
```

### Checker - 测试执行器

**功能**：执行测试用例，驱动实际流量

**主要特性**：
- SSH 远程执行支持
- 自动故障注入和清理
- 实时状态码统计
- 支持多种负载测试工具（curl、hey）

**使用示例**：
```python
from checker.traffic_driver import TrafficDriver

driver = TrafficDriver(
    matrix_file='output_matrix.json',
    ssh_config={'host': '192.168.92.131', 'username': 'root'}
)
driver.run()
```

### Recorder - 数据收集器

**功能**：收集测试过程中的各种观测数据

**支持的数据源**：
- **Envoy Access Logs**：详细的请求响应信息
- **Prometheus Metrics**：服务性能指标
- **Jaeger Traces**：分布式链路追踪
- **K8s Events**：集群事件日志

### Verifier - 结果验证器

**功能**：分析测试数据，验证配置一致性

**验证算法**：
- **权重分布验证**：使用卡方检验或置信区间
- **路由匹配验证**：基于正则表达式和标签匹配
- **故障注入验证**：状态码分布分析
- **性能指标验证**：统计学阈值检查

## 📊 测试类型与验证方法

| 测试类型 | 触发方式 | 验证手段 | 预期结果 |
|----------|----------|----------|----------|
| **路由匹配** | `curl -H "user-agent: jason" http://service` | 解析 Envoy log，检查 upstream_cluster | 请求路由到指定版本 |
| **权重分流** | `for i in {1..100}; do curl http://service; done` | 统计版本分布，计算偏差 | 分布符合配置权重 ±容错率 |
| **故障注入** | 注入 HTTP fault filter | 统计错误率和状态码 | 指定比例返回错误码 |
| **熔断器** | `hey -n 200 -c 50 http://service` | 检测连续失败和恢复 | 超过阈值时拒绝请求 |
| **重试策略** | 模拟下游服务 503 错误 | 计算实际重试次数 | 按策略重试指定次数 |
| **超时控制** | 注入延迟或设置超时头 | 测量实际响应时间 | 超时时间内返回或超时 |
| **限流策略** | 突发高并发请求 | 统计被限流的请求 | 超过限制时返回 429 |

## 📈 测试报告示例

### 权重分布验证详情

```
✅ case_002: 分流权重测试 for host 'reviews'
   📊 流量分布详情:
   ✅ v1: 48个请求 (77.4%, 期望80.0%, 偏差-2.6%)
   ✅ v3: 14个请求 (22.6%, 期望20.0%, 偏差+2.6%)
   
   📋 详细统计:
   - 总请求数: 62
   - 平均偏差: 2.6%
   - 容错阈值: 10.0%
   - 验证状态: PASSED
```

### 故障注入验证详情

```
⚠️  case_004: 重试策略-故障注入测试
   🔍 故障注入结果:
   - 触发条件: simulate_503_error
   - 预期状态码: 503
   - 实际状态码: 200 (意外)
   - 重试次数: 3 (符合预期)
   
   📋 分析建议:
   - 检查故障注入配置是否正确应用
   - 确认 EnvoyFilter 是否匹配到目标路由
```

## 🔧 配置文件说明

### Istio 配置文件 (istio_config.json)

```json
{
  "virtualServices": [
    {
      "metadata": {"name": "reviews"},
      "spec": {
        "hosts": ["reviews"],
        "http": [
          {
            "match": [{"headers": {"user-agent": {"exact": "jason"}}}],
            "route": [{"destination": {"host": "reviews", "subset": "v2"}}]
          },
          {
            "route": [
              {"destination": {"host": "reviews", "subset": "v1"}, "weight": 80},
              {"destination": {"host": "reviews", "subset": "v3"}, "weight": 20}
            ]
          }
        ]
      }
    }
  ],
  "destinationRules": [
    {
      "metadata": {"name": "reviews"},
      "spec": {
        "host": "reviews",
        "trafficPolicy": {
          "outlierDetection": {
            "consecutiveGatewayErrors": 5,
            "interval": "30s",
            "baseEjectionTime": "30s"
          }
        },
        "subsets": [
          {"name": "v1", "labels": {"version": "v1"}},
          {"name": "v2", "labels": {"version": "v2"}},
          {"name": "v3", "labels": {"version": "v3"}}
        ]
      }
    }
  ]
}
```

### 服务依赖关系 (service_dependencies.json)

```json
{
  "productpage": ["details", "reviews"],
  "reviews": [],
  "details": []
}
```

## 🚀 高级功能

### 演示模式

快速体验框架功能：

```bash
cd verifier
python main_verifier.py --demo
```

自动生成示例数据并运行完整验证流程。

### 单用例分析

分析特定测试用例：

```bash
python main_verifier.py --case case_002 \
  --matrix output_matrix.json \
  --logs recorder/logs
```

### 自定义验证规则

```python
from verifier.behavior_model import BehaviorModel, ExpectedBehavior

# 自定义期望行为
custom_behavior = ExpectedBehavior(
    test_type=TestType.CUSTOM,
    policy_type=PolicyType.ROUTING,
    custom_validators=[
        lambda result: result.success_rate > 0.95,
        lambda result: result.avg_response_time < 100
    ]
)
```

## 🔍 故障排查

### 常见问题

1. **SSH 连接失败**
   ```bash
   # 检查网络连通性
   ping 192.168.92.131
   # 验证 SSH 凭据
   ssh root@192.168.92.131
   ```

2. **Envoy 日志收集失败**
   ```bash
   # 检查 Pod 状态
   kubectl get pods -n default
   # 验证 access log 配置
   kubectl logs deployment/reviews-v1 -c istio-proxy
   ```

3. **权重验证失败**
   ```bash
   # 增加请求数量以减少统计误差
   # 检查 DestinationRule 是否正确应用
   kubectl get destinationrule reviews -o yaml
   ```

### 调试模式

启用详细日志：

```bash
export ISTIO_TEST_DEBUG=1
python main_verifier.py --matrix output_matrix.json --logs recorder/logs
```

## 🤝 贡献指南

1. **新增测试类型**：在 `behavior_model.py` 中添加新的策略类型
2. **扩展数据收集**：在 `recorder/` 中添加新的收集器
3. **改进验证算法**：在 `result_comparator.py` 中优化验证逻辑
4. **增加报告格式**：在 `report_generator.py` 中添加新的输出格式

## 📝 许可证

MIT License

## 📞 联系方式

如有问题或建议，请提交 Issue 或 Pull Request。

---

**注意**：本框架需要对 Kubernetes 集群具有适当的访问权限，包括读取 Pod 日志、修改 Istio 配置等。请确保在安全的测试环境中使用。