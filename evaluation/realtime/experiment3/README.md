# 实验三：配置变更响应能力评估

## 实验目标

评估系统在频繁配置变更场景下的响应能力，包括：
- 配置变更检测的响应速度
- 不同验证方法的性能对比
- 系统在高频变更下的稳定性
- 动静态结合验证的有效性

## 实验流程

### 场景设置
- **配置规模**：小 / 中 / 大
- **变更速率**：低（5分钟1次）/ 中（10秒1次）/ 高（1秒1次或批量提交）
- **重复试验**：每个配置规模 × 变更速率 × 对比方案，至少运行10次

### 打点 Instrumentation
在以下阶段记录时间戳（UTC ISO格式）：
- **Monitor**：配置变更事件被监听到
- **Parser**：控制面配置解析
- **Scheduler**：任务调度
- **Generator**：测试用例生成
- **Executor**：动态流量执行
- **Detector**：最终检测/报告输出
- **端到端延迟** = Detector - Monitor

### 资源监控
- 使用 kubectl top、Node Exporter、cAdvisor 采集 CPU、内存、网络流量

### Verification Cost 统计
- 记录每次验证的 HTTP 请求数、总字节量

### 准确性对照
- 每个配置样本带有 ground truth（是否存在不一致、类型）
- 计算 Precision / Recall / F1

### 统计检验
- **延迟差异**：Wilcoxon 检验
- **检测率差异**：McNemar 检验
- **平均延迟**：bootstrap CI

## 对比方案

1. **Static-only**：仅解析配置，不进行动态验证
2. **Dynamic-only**：仅运行时流量验证
3. **Hybrid (Our)**：动静态结合，静态指导用例生成并融合结果
4. **Delta/Incremental Static**：仅对受影响的配置子图进行增量检查
5. **Event-driven Fast-path**：先做快速检查，再异步执行深度验证
6. **Continuous Monitoring**：依赖 Prometheus/Jaeger 的持续监控与告警

## 文件结构

```
experiment3/
├── configs/                  # 存放配置样本（小/中/大 × 正常/异常）
│   ├── small/
│   │   ├── baseline_config.yaml
│   │   └── inconsistent_config.yaml
│   ├── medium/
│   │   ├── baseline_config.yaml
│   │   └── inconsistent_config.yaml
│   └── large/
│       ├── baseline_config.yaml
│       └── inconsistent_config.yaml
├── runners/                  # 各对比方案的执行器
│   ├── static_runner.py
│   ├── dynamic_runner.py
│   ├── hybrid_runner.py
│   ├── delta_runner.py
│   ├── fastpath_runner.py
│   └── monitoring_runner.py
├── monitor/                  # 配置变更监听
│   └── watcher.py
├── utils/
│   ├── instrumentation.py   # 打点工具（时间戳、日志记录）
│   ├── metrics.py           # Precision/Recall/F1 计算
│   ├── resource_collector.py# kubectl top + cAdvisor 接口
│   └── cost_collector.py    # HTTP 请求/字节量统计
├── run_experiment3.py       # 主实验入口（调度不同对比方法）
├── analyze_results.py       # 结果统计与可视化（箱线图/曲线图/散点）
└── README.md
```

## 使用方法

### 1. 运行完整实验

```bash
python run_experiment3.py --config config.yaml --output results/
```

### 2. 运行特定配置

```bash
python run_experiment3.py \
    --scales small medium \
    --rates low medium \
    --methods static_only hybrid \
    --repetitions 5
```

### 3. 分析实验结果

```bash
python analyze_results.py --results results/experiment3_report_20250101_120000.json
```

### 4. 单独测试某个方法

```bash
# 静态分析
python runners/static_runner.py --config configs/small/ --output static_results.json

# 动态验证
python runners/dynamic_runner.py --config configs/small/ --duration 60

# 混合验证
python runners/hybrid_runner.py --config configs/small/ --duration 60
```

## 配置示例

### 实验配置文件 (config.yaml)

```yaml
experiment_name: "Experiment 3: Configuration Change Response"
description: "评估系统在频繁配置变更场景下的响应能力"
config_scales: ["small", "medium", "large"]
change_rates: ["low", "medium", "high"]
methods: ["static_only", "dynamic_only", "hybrid"]
repetitions: 10
test_duration: 60
output_dir: "results"
namespace: "default"
watch_paths: ["configs"]
metrics:
  confidence_level: 0.95
  bootstrap_samples: 1000
```

## 结果分析

### 可视化图表

1. **延迟箱线图**：配置规模 × 变更速率
2. **延迟曲线图**：首次响应 & 最终确认随时间变化
3. **开销-延迟散点图**：请求数 vs 检测延迟
4. **精度表格**：Precision / Recall / F1 并列展示
5. **性能雷达图**：多维度性能对比
6. **配置规模影响分析**：不同规模下的性能变化
7. **变更速率影响分析**：不同速率下的性能变化

### 关键指标

- **响应时间**：端到端处理延迟
- **准确性**：Precision、Recall、F1分数
- **吞吐量**：单位时间处理能力
- **资源使用**：CPU、内存、网络消耗
- **稳定性**：成功率、错误率

## 成功标准

### 响应时间要求
- 配置变更检测：< 5秒
- 影响分析完成：< 30秒
- 告警发出：< 10秒（严重问题）
- 端到端处理：< 60秒

### 吞吐量要求
- 配置变更处理：≥ 100变更/分钟
- 监控数据处理：≥ 10000点/秒
- 并发处理：≥ 10个同时配置变更

### 可靠性要求
- 配置同步成功率：≥ 99.9%
- 监控数据丢失率：≤ 0.1%
- 系统可用性：≥ 99.95%

## 故障排除

### 常见问题

1. **Kubernetes连接失败**
   - 检查 kubectl 配置
   - 确认集群访问权限

2. **配置文件解析错误**
   - 验证 YAML 语法
   - 检查资源定义完整性

3. **性能测试超时**
   - 调整测试持续时间
   - 检查网络连接

4. **可视化图表生成失败**
   - 安装 matplotlib 和 seaborn
   - 检查中文字体支持

### 日志文件

- `instrumentation.log`：打点日志
- `experiment3.log`：实验运行日志
- `results/`：实验结果和报告

## 扩展功能

### 自定义运行器

可以继承基础运行器类来实现自定义验证方法：

```python
from runners.static_runner import StaticRunner

class CustomRunner(StaticRunner):
    async def run(self, config_files):
        # 实现自定义逻辑
        pass
```

### 自定义指标

在 `utils/metrics.py` 中添加新的指标计算方法：

```python
def calculate_custom_metric(data):
    # 实现自定义指标
    pass
```

### 自定义可视化

在 `analyze_results.py` 中添加新的图表类型：

```python
def _plot_custom_chart(self):
    # 实现自定义图表
    pass
```
