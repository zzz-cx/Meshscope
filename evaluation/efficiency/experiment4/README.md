# 实验四：效率评估实验

## 实验目标

本实验旨在评估不同测试用例生成方法在Istio配置验证中的效率，特别关注正交测试用例生成方法的性能表现。

## 实验问题

**Q4：正交测试用例生成方法是否能够高效地生成高质量的测试用例？**

通过对比分析穷举、正交、配对、随机等不同测试用例生成方法，评估各方法在覆盖率、生成成本、执行效率等方面的表现。

## 实验设计

### 1. 静态准备

- **配置样本准备**：准备小、中、大三种规模的Istio配置样本
  - 小规模：5个服务，3个VirtualService，2个DestinationRule
  - 中规模：10个服务，6个VirtualService，4个DestinationRule  
  - 大规模：20个服务，12个VirtualService，8个DestinationRule

- **配置路径提取**：从配置中提取所有可能的执行路径
  - 匹配条件路径（Header、URI匹配）
  - 路由目标路径
  - 策略配置路径（负载均衡、连接池、异常检测）
  - Gateway配置路径

### 2. 测试用例生成方法

#### 2.1 穷举方法（Exhaustive）
- 生成所有可能的配置组合
- 基于配置维度的笛卡尔积
- 适用于小规模配置验证

#### 2.2 正交方法（Orthogonal）- 我们的方法
基于四条正交原则：
- **匹配条件维度正交**：HTTP Header、URI、地域等匹配条件正交
- **功能策略间正交**：负载均衡、连接池、异常检测等策略正交
- **全局/局部策略正交**：全局策略与局部策略正交
- **策略触发机制正交**：请求级、服务级触发机制正交

#### 2.3 配对方法（Pairwise）
- 基于两两配对覆盖生成测试用例
- 使用贪心算法选择最优组合
- 平衡测试覆盖率和用例数量

#### 2.4 随机方法（Random）
- 基于随机采样生成测试用例
- 支持多次运行和统计分析
- 作为基准对比方法

#### 2.5 手动方法（Manual）
- 基于专家经验手动设计的测试用例
- 作为质量基准对比

### 3. 执行与数据收集

#### 3.1 测试用例执行
- 集成`istio_Dynamic_Test`执行器
- 模拟真实流量验证配置正确性
- 收集执行日志和性能指标

#### 3.2 覆盖率计算
- **配置路径覆盖率**：计算测试用例覆盖的配置路径比例
- **策略路径覆盖率**：计算策略配置的覆盖情况
- **依赖关系覆盖率**：分析路径依赖关系的覆盖情况

#### 3.3 成本与效率统计
- **生成成本**：测试用例生成时间、资源消耗
- **执行成本**：测试执行时间、HTTP请求数、资源使用
- **效率指标**：覆盖率/时间、测试用例数/时间、成本/覆盖率

### 4. 重复实验

- 每种方法执行多次独立实验
- 计算均值和95%置信区间
- 分析结果的稳定性和一致性

### 5. 统计测试

#### 5.1 Wilcoxon符号秩检验
- 比较不同方法效率分数的显著性差异
- 非参数统计检验，适用于小样本

#### 5.2 McNemar检验
- 比较不同方法覆盖率的一致性
- 分析分类结果的相关性

### 6. 敏感性分析

#### 6.1 正交值变化敏感性
- 改变正交维度的值范围
- 分析对覆盖率的影响

#### 6.2 t-way覆盖敏感性
- 调整t-way覆盖参数（2-way, 3-way等）
- 评估覆盖策略的效果

### 7. 规模敏感性

- 在不同规模配置上测试各方法
- 分析方法随规模变化的性能表现
- 识别可扩展性瓶颈

## 目录结构

```
experiment4/
├── configs/                    # 配置文件
│   ├── small_config.yaml      # 小规模配置
│   ├── medium_config.yaml     # 中规模配置
│   └── large_config.yaml      # 大规模配置
├── generators/                 # 测试用例生成器
│   ├── exhaustive_generator.py    # 穷举生成器
│   ├── orthogonal_generator.py    # 正交生成器
│   ├── pairwise_generator.py      # 配对生成器
│   └── random_generator.py        # 随机生成器
├── coverage/                   # 覆盖率计算
│   └── coverage_calculator.py     # 覆盖率计算器
├── cost/                      # 成本分析
│   └── cost_analyzer.py           # 成本分析器
├── visualizations/            # 可视化
│   └── plot_generator.py          # 图表生成器
├── results/                   # 结果目录
├── run_experiment4.py         # 主运行器
├── config.yaml               # 实验配置
└── README.md                 # 本文档
```

## 使用方法

### 1. 配置实验

编辑`config.yaml`文件，设置实验参数：

```yaml
methods:
  - "exhaustive"
  - "orthogonal" 
  - "pairwise"
  - "random"

parameters:
  orthogonal:
    max_cases: 100
    config_scale: "medium"
```

### 2. 运行实验

```bash
# 运行完整实验
python run_experiment4.py --config config.yaml

# 指定输出目录
python run_experiment4.py --config config.yaml --output-dir ./my_results
```

### 3. 生成可视化

```bash
# 生成所有可视化图表
python visualizations/plot_generator.py --data results/efficiency_evaluation_report_*.json
```

### 4. 单独测试生成器

```bash
# 测试正交生成器
python generators/orthogonal_generator.py --config configs/medium_config.yaml --output orthogonal_cases.json --max-cases 50

# 测试覆盖率计算器
python coverage/coverage_calculator.py --config configs/medium_config.yaml --test-cases test_cases.json
```

## 预期结果

### 1. 覆盖率对比
- 正交方法应达到较高的覆盖率（预期>85%）
- 穷举方法覆盖率最高但成本最高
- 随机方法覆盖率较低但成本最低

### 2. 效率分析
- 正交方法在覆盖率/成本比上表现优异
- 配对方法在中等规模配置上效率良好
- 穷举方法在大规模配置上效率急剧下降

### 3. 可扩展性
- 正交方法具有良好的可扩展性
- 穷举方法随规模增长呈指数级复杂度
- 随机方法可扩展性中等

### 4. 统计显著性
- 正交方法与其他方法存在显著性差异
- 配对方法与正交方法在中等规模上性能接近
- 随机方法显著低于其他方法

## 输出文件

### 1. 综合报告
- `efficiency_evaluation_report_YYYYMMDD_HHMMSS.json`
- 包含完整的实验结果和分析

### 2. 成本分析报告
- `cost_analysis_report_YYYYMMDD_HHMMSS.json`
- 详细的成本和效率分析

### 3. 可视化图表
- `coverage_vs_test_cases.png` - 覆盖率对比图
- `test_case_counts_bar.png` - 测试用例数量柱状图
- `cost_coverage_efficiency_scatter.png` - 成本-覆盖率散点图
- `execution_time_boxplot.png` - 执行时间箱线图
- `coverage_comparison_radar.png` - 覆盖率雷达图
- `efficiency_ranking.png` - 效率排名图
- `comprehensive_comparison.png` - 综合对比图

## 技术特点

### 1. 正交测试理论
- 基于正交数组理论
- 四维度正交原则
- 平衡覆盖率和效率

### 2. 资源监控
- 实时CPU、内存、网络监控
- 精确的成本计算
- 性能瓶颈识别

### 3. 统计分析
- 多种统计检验方法
- 置信区间计算
- 显著性分析

### 4. 可视化分析
- 多种图表类型
- 交互式可视化
- 综合对比分析

## 扩展性

### 1. 新增生成方法
- 在`generators/`目录下添加新的生成器
- 实现标准接口
- 更新配置文件

### 2. 新增评估指标
- 扩展`cost_analyzer.py`中的指标计算
- 添加新的效率评估维度
- 更新可视化图表

### 3. 集成更多工具
- 集成更多Istio配置验证工具
- 支持更多配置格式
- 扩展测试场景

## 注意事项

1. **内存使用**：穷举方法在大规模配置上可能消耗大量内存
2. **执行时间**：完整实验可能需要较长时间，建议在配置较低的参数下先测试
3. **依赖安装**：确保安装了所有必要的Python包（matplotlib、seaborn、numpy等）
4. **权限设置**：确保有足够的文件读写权限

## 联系信息

如有问题或建议，请联系实验负责人。
