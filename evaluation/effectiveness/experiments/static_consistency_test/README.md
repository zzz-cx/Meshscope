# 静态一致性检验实验

## 实验目标
验证系统在静态分析阶段能够检测配置间的逻辑/依赖不一致性问题。

## 实验设计

### 输入
- **正确配置**: 无不一致性的标准配置
- **不一致配置**: 人为构造的包含各种不一致性的配置
- **混合配置**: 正确配置与不一致配置的混合

### 检测目标
1. **VirtualService与DestinationRule不匹配**
2. **路由权重配置错误**
3. **服务引用错误**
4. **Gateway选择器错误**
5. **策略冲突**
6. **重复配置定义**

### 输出
- 不一致性检测报告
- 配置依赖关系图
- 问题定位和严重程度分级

### 评价指标
- **检测率**: 发现预设错误的比例
- **误报率**: 错误报告不存在问题的比例
- **覆盖率**: 检测到的不一致类型覆盖度
- **检测时间**: 静态分析所需时间

## 实验文件结构

```
static_consistency_test/
├── README.md                    # 本文件
├── experiment_config.yaml      # 实验配置
├── input_configs/              # 输入配置文件
│   ├── correct/                # 正确配置
│   ├── inconsistent/           # 不一致配置
│   └── mixed/                  # 混合配置
├── expected_results/           # 预期检测结果
├── scripts/                    # 实验脚本
│   ├── run_static_test.py      # 主实验脚本
│   ├── config_analyzer.py      # 配置分析器
│   └── result_validator.py     # 结果验证器
└── results/                    # 实验结果输出
    ├── detection_reports/      # 检测报告
    ├── graphs/                 # 依赖关系图
    └── metrics/                # 评价指标
```

## 运行方式

```bash
# 运行单个测试用例
python scripts/run_static_test.py --config input_configs/inconsistent/case_001.yaml

# 运行完整测试套件
python scripts/run_static_test.py --suite all

# 生成检测报告
python scripts/run_static_test.py --generate-report
```

## 实验用例说明

### Case 1: VirtualService-DestinationRule不匹配
- **问题**: VirtualService路由到不存在的subset
- **预期**: 检测到subset引用错误

### Case 2: 权重分配错误
- **问题**: 权重总和不等于100%
- **预期**: 检测到权重配置错误

### Case 3: 重复EnvoyFilter冲突
- **问题**: 多个EnvoyFilter配置相同的过滤器
- **预期**: 检测到策略冲突

### Case 4: 服务引用错误
- **问题**: 引用不存在的服务
- **预期**: 检测到服务引用错误

### Case 5: Gateway选择器错误
- **问题**: Gateway选择器指向不存在的标签
- **预期**: 检测到选择器配置错误
