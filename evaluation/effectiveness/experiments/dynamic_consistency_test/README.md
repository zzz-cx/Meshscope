# 动态一致性检验实验

## 实验目标
验证系统在运行时能够检测配置与实际行为之间的不一致性问题。

## 实验设计

### 输入
- **Istio配置文件**: VirtualService、DestinationRule、EnvoyFilter等
- **运行中的微服务系统**: Bookinfo或Online Boutique应用
- **实时流量**: 模拟用户请求和系统调用

### 检测目标
1. **流量分发异常**: 实际流量分配与VirtualService配置不符
2. **故障注入失效**: 配置的故障注入策略未生效
3. **限流策略失效**: 配置的限流规则在运行时未按预期工作
4. **重试策略异常**: 重试配置与实际重试行为不一致
5. **熔断器状态异常**: 熔断器未按配置条件触发
6. **超时策略失效**: 超时配置与实际响应时间不符

### 输出
- 动态行为检测报告
- 配置与实际行为对比分析
- 实时监控数据和Trace分析
- 不一致性根因分析

### 评价指标
- **检测覆盖率**: 能发现多少与配置不符的行为
- **检测时延**: 从异常行为发生到被检测出的时间
- **资源开销**: 监控和检测过程的资源消耗
- **误报率**: 错误报告正常行为的比例

## 实验文件结构

```
dynamic_consistency_test/
├── README.md                    # 本文件
├── experiment_config.yaml      # 实验配置
├── scenarios/                  # 测试场景
│   ├── traffic_split/          # 流量分发测试
│   ├── fault_injection/        # 故障注入测试
│   ├── rate_limiting/          # 限流测试
│   ├── retry_policy/           # 重试策略测试
│   ├── circuit_breaker/        # 熔断器测试
│   └── timeout_policy/         # 超时策略测试
├── configs/                    # 测试配置文件
│   ├── baseline/               # 基准配置
│   ├── faulty/                 # 故意配置错误的配置
│   └── mixed/                  # 混合场景配置
├── scripts/                    # 实验脚本
│   ├── run_dynamic_test.py     # 主实验脚本
│   ├── traffic_generator.py    # 流量生成器
│   ├── behavior_analyzer.py    # 行为分析器
│   ├── config_applier.py       # 配置应用器
│   └── result_collector.py     # 结果收集器
├── monitoring/                 # 监控配置
│   ├── prometheus_config.yaml  # Prometheus配置
│   ├── jaeger_config.yaml      # Jaeger配置
│   └── custom_metrics.yaml     # 自定义指标
└── results/                    # 实验结果
    ├── behavior_reports/       # 行为分析报告
    ├── traces/                 # 分布式追踪数据
    ├── metrics/                # 指标数据
    └── logs/                   # 系统日志
```

## 运行方式

```bash
# 环境准备
python scripts/setup_environment.py --cluster-config configs/cluster.yaml

# 运行单个场景测试
python scripts/run_dynamic_test.py --scenario traffic_split --duration 10m

# 运行完整测试套件
python scripts/run_dynamic_test.py --suite all --duration 30m

# 实时监控模式
python scripts/run_dynamic_test.py --monitor --realtime
```

## 测试场景说明

### 场景1: 流量分发异常检测
- **配置**: VirtualService设置70%流量到v1，30%到v2
- **异常注入**: 人为修改Envoy配置使实际分发为50%:50%
- **预期检测**: 检测到流量分发与配置不符

### 场景2: 故障注入失效检测  
- **配置**: EnvoyFilter配置30%请求延迟2秒
- **异常注入**: 禁用故障注入功能
- **预期检测**: 检测到故障注入策略未生效

### 场景3: 限流策略失效检测
- **配置**: 限制每分钟3个请求
- **异常注入**: 绕过限流机制
- **预期检测**: 检测到请求速率超过限制但未被拦截

### 场景4: 重试策略异常检测
- **配置**: 失败时重试3次
- **异常注入**: 禁用重试机制
- **预期检测**: 检测到失败请求未进行重试

### 场景5: 熔断器异常检测
- **配置**: 连续5次错误后熔断30秒
- **异常注入**: 禁用熔断器
- **预期检测**: 检测到达到熔断条件但未触发熔断

### 场景6: 超时策略失效检测
- **配置**: 请求超时时间3秒
- **异常注入**: 禁用超时机制
- **预期检测**: 检测到请求时间超过配置但未超时

## 数据收集

### 监控数据
- **Prometheus指标**: QPS、延迟、错误率、重试次数等
- **Envoy访问日志**: 请求详情、响应码、处理时间
- **Jaeger追踪**: 分布式调用链路和时间消耗

### 行为分析
- **流量模式分析**: 实际流量分发统计
- **错误模式分析**: 错误类型和频率统计  
- **性能模式分析**: 响应时间分布和异常点检测

### 配置对比
- **期望行为**: 基于配置计算的预期行为
- **实际行为**: 从监控数据提取的实际行为
- **差异分析**: 期望与实际的偏差量化
