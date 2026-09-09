# Experiment 2: Accuracy评估实验

## 实验目标

本实验旨在评估不同检测方法在识别Istio配置错误方面的准确性，通过对比静态检测、动态检测、混合检测和现有工具的性能，验证动静态结合方法的优势。

## 实验设计

### 1. 数据集构造

#### 样本来源
- **人为构造错误配置**: 基于常见配置错误模式人工设计
- **真实仓库错误案例**: 从开源项目中收集的实际错误配置
- **配置变异生成**: 通过mutation技术自动生成错误变体

#### 每个样本包含
- 配置文件（YAML格式）
- Ground Truth标签：是否存在故障、故障类型、严重程度

### 2. 对比方法

| 方法 | 描述 | 实现 |
|------|------|------|
| **Static-only** | 仅静态配置解析与一致性检测 | `methods/static_only.py` |
| **Dynamic-only** | 仅运行时流量验证与行为分析 | `methods/dynamic_only.py` |
| **Hybrid (Our)** | 动静态结合，静态建模辅助生成正交用例，结果融合 | `methods/hybrid.py` |
| **Existing Tools** | 现有工具：istioctl analyze, kube-linter | `methods/existing_tools.py` |

### 3. 实验流程

1. **配置部署**: 将配置样本应用到测试环境
2. **方法检测**: 针对每个配置样本，运行所有检测方法
3. **结果对比**: 对比检测结果与ground truth
4. **指标计算**: 统计TP/FP/FN/TN，计算Precision/Recall/F1
5. **性能记录**: 记录检测延迟、流量开销
6. **重复实验**: 多次重复以降低随机性

### 4. 评估指标

#### 主要指标
- **Precision**: TP / (TP + FP)
- **Recall**: TP / (TP + FN)  
- **F1-score**: 2 × (Precision × Recall) / (Precision + Recall)

#### 次要指标
- **检测延迟**: 从配置应用到检测完成的时间
- **流量开销**: 动态检测产生的网络流量
- **误报率**: FP / (FP + TN)
- **漏报率**: FN / (FN + TP)

#### 统计检验
- **Bootstrap CI**: 置信区间估计
- **McNemar测试**: 配对方法比较
- **Wilcoxon检验**: 非参数统计检验

## 目录结构

```
experiment2_accuracy/
├── README.md                    # 本文件
├── configs/                     # 配置样本集（带标签）
│   ├── human_errors/            # 人为构造错误配置
│   │   ├── conflict_vs.yaml
│   │   ├── missing_subset.yaml
│   │   ├── weight_error.yaml
│   │   ├── duplicate_envoyfilter.yaml
│   │   ├── missing_service_ref.yaml
│   │   └── gateway_selector_error.yaml
│   ├── real_world/              # 真实仓库错误案例
│   │   ├── case1.yaml
│   │   ├── case2.yaml
│   │   └── ...
│   ├── mutated/                 # 配置变异生成
│   │   ├── vs_mut_01.yaml
│   │   ├── dr_mut_01.yaml
│   │   └── ...
│   └── ground_truth.json        # 存储每个配置的GT标签
├── methods/                     # 各检测方法实现
│   ├── static_only.py           # 静态解析与一致性检测
│   ├── dynamic_only.py          # 动态流量验证
│   ├── hybrid.py                # 动静态结合方法
│   └── existing_tools.py        # 调用istioctl/kube-linter
├── runner/                      # 实验运行器
│   ├── run_experiment.py        # 主控脚本
│   ├── evaluator.py             # 结果对比、指标计算
│   └── utils.py                 # 公共工具
└── results/                     # 实验结果
    ├── raw_logs/                # 每个方法的原始输出
    ├── metrics.json             # 统计指标结果
    └── plots/                   # 绘图（柱状图、CDF、ROC）
```

## 快速开始

### 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 确保测试环境可用
kubectl get nodes
istioctl version
```

### 运行实验

```bash
# 运行完整实验
python runner/run_experiment.py --all-methods --all-configs

# 运行特定方法
python runner/run_experiment.py --method hybrid --configs human_errors

# 运行特定配置
python runner/run_experiment.py --config configs/human_errors/conflict_vs.yaml

# 生成报告
python runner/run_experiment.py --generate-report
```

### 查看结果

```bash
# 查看指标结果
cat results/metrics.json

# 查看可视化图表
ls results/plots/

# 查看原始日志
ls results/raw_logs/
```

## 配置样本说明

### 人为构造错误配置

1. **conflict_vs.yaml**: VirtualService路由冲突
2. **missing_subset.yaml**: DestinationRule子集缺失
3. **weight_error.yaml**: 流量权重配置错误
4. **duplicate_envoyfilter.yaml**: 重复EnvoyFilter配置
5. **missing_service_ref.yaml**: 服务引用不存在
6. **gateway_selector_error.yaml**: Gateway选择器错误

### 真实仓库错误案例

从以下来源收集的实际错误配置：
- Istio官方示例中的问题配置
- GitHub Issues中的配置错误
- 社区报告的问题案例

### 配置变异生成

使用mutation技术自动生成错误变体：
- 字段值变异（如权重、超时时间）
- 结构变异（如缺失必需字段）
- 引用变异（如错误的服务名）

## 检测方法说明

### Static-only方法
- 解析Istio配置YAML
- 检查配置语法和语义
- 验证配置间的一致性
- 检测常见的配置错误模式

### Dynamic-only方法
- 部署配置到测试环境
- 生成测试流量
- 收集运行时指标和日志
- 分析行为异常

### Hybrid方法
- 结合静态分析和动态验证
- 使用静态建模指导动态测试用例生成
- 融合多种检测结果
- 提供更全面的错误检测

### Existing Tools方法
- 调用istioctl analyze进行配置分析
- 使用kube-linter检查Kubernetes配置
- 集成其他社区工具

## 结果分析

### 性能对比
- 各方法的Precision/Recall/F1对比
- 检测延迟和资源开销分析
- 不同错误类型的检测效果

### 统计显著性
- 使用McNemar测试比较配对方法
- 使用Wilcoxon检验比较性能分布
- Bootstrap置信区间估计

### 可视化展示
- 柱状图：各方法指标对比
- ROC曲线：检测性能展示
- CDF图：延迟分布分析
- 热力图：错误类型检测效果

## 预期结果

### 假设
1. **Hybrid方法**在整体准确性上优于单一方法
2. **Static-only方法**在配置语法错误检测上表现良好
3. **Dynamic-only方法**在运行时行为异常检测上更有效
4. **Existing Tools**在已知错误模式检测上表现稳定

### 成功标准
- Hybrid方法的F1-score > 0.85
- 检测延迟 < 5分钟
- 误报率 < 10%
- 统计显著性p < 0.05

## 故障排除

### 常见问题
1. **配置部署失败**: 检查Kubernetes集群状态
2. **检测方法超时**: 调整超时参数
3. **结果不一致**: 检查随机种子设置
4. **内存不足**: 减少并发测试数量

### 调试模式
```bash
# 启用详细日志
python runner/run_experiment.py --verbose --debug

# 单步调试
python runner/run_experiment.py --step-by-step

# 保留中间文件
python runner/run_experiment.py --no-cleanup
```

## 扩展指南

### 添加新的检测方法
1. 在`methods/`目录下创建新的Python文件
2. 实现标准的检测接口
3. 在`runner/run_experiment.py`中注册新方法

### 添加新的配置样本
1. 在`configs/`相应目录下添加配置文件
2. 在`ground_truth.json`中添加标签信息
3. 更新实验配置

### 自定义评估指标
1. 在`runner/evaluator.py`中添加新的指标计算
2. 更新结果输出格式
3. 添加相应的可视化代码
