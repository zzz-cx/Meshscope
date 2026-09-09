# Effectiveness评估实验

## 概述

本目录包含两个核心实验，用于评估Istio动静态结合一致性配置检验系统的有效性：

1. **静态一致性检验实验** - 评估静态配置分析和不一致性检测能力
2. **动态一致性检验实验** - 评估运行时行为与配置一致性的检测能力

## 实验目标

### 静态一致性检验
- **输入**: 人为构造或收集的配置文件（控制面配置 + 数据面配置）
- **目标**: 检查配置间是否存在逻辑/依赖不一致
- **输出**: 
  - 报告配置冲突（如VirtualService路由目标与DestinationRule不匹配）
  - 标记图中的不一致边/节点
- **评价指标**: 检测率、误报率、漏报率

### 动态一致性检验
- **输入**: 与静态实验同样的配置，系统在运行态下加载这些配置
- **目标**: 验证配置是否和实际行为一致（如限流是否生效、故障注入是否体现）
- **输出**:
  - 报告配置与行为不符的问题
  - 日志、trace和metrics数据
- **评价指标**: 检测覆盖率、时延与资源开销

## 目录结构

```
effectiveness/experiments/
├── README.md                           # 本文件
├── static_consistency_test/            # 静态一致性检验实验
│   ├── README.md                       # 实验说明
│   ├── experiment_config.yaml          # 实验配置
│   ├── input_configs/                  # 测试配置文件
│   │   ├── correct/                    # 正确配置
│   │   ├── inconsistent/               # 不一致配置
│   │   └── mixed/                      # 混合配置
│   ├── expected_results/               # 预期检测结果
│   │   └── expected_detections.json    # 期望检测的问题
│   └── scripts/                        # 实验脚本
│       └── run_static_test.py          # 主实验脚本
└── dynamic_consistency_test/           # 动态一致性检验实验
    ├── README.md                       # 实验说明
    ├── experiment_config.yaml          # 实验配置
    ├── scenarios/                      # 测试场景
    │   ├── traffic_split/              # 流量分发测试
    │   ├── fault_injection/            # 故障注入测试
    │   ├── rate_limiting/              # 限流测试
    │   ├── retry/                      # 重试策略测试
    │   ├── circuit_breaker/            # 熔断器测试
    │   └── timeout/                    # 超时策略测试
    └── scripts/                        # 实验脚本
        ├── run_dynamic_test.py         # 主实验脚本
        ├── traffic_generator.py        # 流量生成器
        ├── behavior_analyzer.py        # 行为分析器
        ├── config_applier.py           # 配置应用器
        └── result_collector.py         # 结果收集器
```

## 快速开始

### 环境准备

1. **Kubernetes集群**: v1.25+
2. **Istio**: v1.18+
3. **测试应用**: Bookinfo或Online Boutique
4. **监控工具**: Prometheus、Jaeger、Grafana
5. **Python环境**: 3.8+ 并安装依赖

```bash
# 安装Python依赖
pip install aiohttp numpy pandas scipy pyyaml

# 确保kubectl和istioctl可用
kubectl version
istioctl version

# 部署测试应用（如果未部署）
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.18/samples/bookinfo/platform/kube/bookinfo.yaml
```

### 运行静态一致性检验实验

```bash
cd static_consistency_test

# 运行完整测试套件
python scripts/run_static_test.py --suite all

# 运行特定测试用例
python scripts/run_static_test.py --config input_configs/inconsistent/vs_dr_mismatch.yaml

# 生成检测报告
python scripts/run_static_test.py --generate-report
```

### 运行动态一致性检验实验

```bash
cd dynamic_consistency_test

# 环境设置
python scripts/run_dynamic_test.py --setup-only

# 运行所有场景
python scripts/run_dynamic_test.py

# 运行特定场景
python scripts/run_dynamic_test.py --scenario traffic_split_anomaly

# 实时监控模式
python scripts/run_dynamic_test.py --monitor --realtime
```

## 测试用例说明

### 静态测试用例

1. **vs_dr_mismatch.yaml**: VirtualService引用的subset在DestinationRule中不存在
2. **weight_error.yaml**: 权重总和不等于100%
3. **duplicate_envoyfilter.yaml**: 重复EnvoyFilter配置冲突
4. **missing_service_ref.yaml**: 引用不存在的服务
5. **gateway_selector_error.yaml**: Gateway选择器错误
6. **bookinfo_with_errors.yaml**: 包含多种错误的混合配置

### 动态测试场景

1. **traffic_split_anomaly**: 流量分发异常检测（配置70:30，实际50:50）
2. **fault_injection_failure**: 故障注入失效检测（配置延迟和错误注入被禁用）
3. **rate_limiting_failure**: 限流策略失效检测（限流机制被绕过）
4. **retry_policy_anomaly**: 重试策略异常检测（重试机制被禁用）
5. **circuit_breaker_anomaly**: 熔断器状态异常检测（熔断器被禁用）
6. **timeout_policy_failure**: 超时策略失效检测（超时机制被禁用）

## 评价指标

### 静态实验指标

- **检测率 (Detection Rate)**: 成功检测到的不一致性数量 / 总的不一致性数量
- **误报率 (False Positive Rate)**: 错误报告的问题数量 / 总检测数量
- **漏报率 (False Negative Rate)**: 未检测到的不一致性数量 / 总的不一致性数量
- **准确率 (Accuracy)**: (正确检测 + 正确通过) / 总测试用例数

### 动态实验指标

- **检测覆盖率**: 能发现多少与配置不符的行为
- **检测时延**: 从异常行为发生到检测出的时间
- **资源开销**: 监控和检测过程的资源消耗
- **误报率**: 错误报告正常行为的比例

## 实验数据

### 静态实验数据
- 预设11个已知不一致性问题
- 覆盖6种不同的不一致性类型
- 包含正确配置作为阴性对照

### 动态实验数据
- 6个不同的行为异常场景
- 实时监控数据收集
- Prometheus指标、Envoy日志、Jaeger追踪
- 配置与行为的对比分析

## 成功标准

### 静态实验
- 检测率 ≥ 85%
- 误报率 ≤ 10%
- 分析时间 ≤ 60秒

### 动态实验
- 检测覆盖率 ≥ 80%
- 检测时延 ≤ 5分钟
- 监控开销 ≤ 5%

## 结果分析

实验完成后将生成以下报告：

### 静态实验报告
- `static_consistency_test_report_YYYYMMDD_HHMMSS.json`
- 包含详细的检测结果、指标计算和问题分析

### 动态实验报告
- `dynamic_consistency_test_report_YYYYMMDD_HHMMSS.json`
- 包含行为分析、异常检测结果和性能指标

## 故障排除

### 常见问题

1. **kubectl连接失败**
   - 检查kubeconfig配置
   - 确认集群可访问性

2. **Istio组件未运行**
   - 检查istio-system命名空间的Pod状态
   - 确认Istio正确安装

3. **监控数据收集失败**
   - 检查Prometheus和Jaeger的可访问性
   - 确认监控组件正常运行

4. **测试应用未部署**
   - 使用 `--setup-only` 选项进行环境设置
   - 手动部署Bookinfo应用

### 调试模式

```bash
# 启用详细日志
export PYTHONPATH=$PYTHONPATH:.
python scripts/run_static_test.py --verbose

# 保留中间文件
python scripts/run_dynamic_test.py --no-cleanup
```

## 扩展指南

### 添加新的静态测试用例

1. 在 `input_configs/inconsistent/` 目录下创建新的YAML文件
2. 在 `expected_results/expected_detections.json` 中添加预期结果
3. 更新 `experiment_config.yaml` 中的测试用例配置

### 添加新的动态测试场景

1. 在 `scenarios/` 目录下创建新的场景配置
2. 在 `experiment_config.yaml` 中添加场景定义
3. 在 `behavior_analyzer.py` 中实现相应的分析逻辑

## 相关文档

- [Istio官方文档](https://istio.io/docs/)
- [Bookinfo应用指南](https://istio.io/docs/examples/bookinfo/)
- [Prometheus查询语言](https://prometheus.io/docs/prometheus/latest/querying/)
- [Jaeger追踪分析](https://www.jaegertracing.io/docs/)
