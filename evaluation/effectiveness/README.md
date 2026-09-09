# 有效性评估 (Effectiveness Evaluation)

## 评估目标
验证系统是否能有效检测到Istio配置中的各种不一致性问题，包括：
- 静态配置冲突
- 动态行为与配置不匹配
- 跨服务策略冲突
- 配置语义错误

## 评估维度

### 1. 静态不一致性检测
- 路由规则冲突
- 策略覆盖问题
- 资源引用错误
- 配置语法错误

### 2. 动态不一致性检测
- 运行时行为与期望不符
- 流量分发异常
- 故障注入不生效
- 重试策略失效

### 3. 跨服务一致性检测
- 服务间依赖关系错误
- 权限策略冲突
- 网络策略不匹配

## 测试用例分类

### A类：已知不一致性场景（阳性对照）
- 预设明确的配置错误
- 期望系统能够检测并标记

### B类：正常配置场景（阴性对照）
- 配置正确且行为符合预期
- 期望系统不产生误报

### C类：边界情况
- 模糊的配置边界
- 复杂的策略组合
- 罕见的配置组合

## 评估指标

### 主要指标
- **检测率 (Detection Rate)**: 成功检测到的不一致性数量 / 总的不一致性数量
- **误报率 (False Positive Rate)**: 错误报告的问题数量 / 总检测数量  
- **漏报率 (False Negative Rate)**: 未检测到的不一致性数量 / 总的不一致性数量
- **准确率 (Accuracy)**: (正确检测 + 正确通过) / 总测试用例数

### 次要指标
- **F1-Score**: 平衡检测率和精确度的综合指标
- **召回率 (Recall)**: 检测到的真实问题 / 实际存在的问题
- **精确度 (Precision)**: 检测到的真实问题 / 总检测数量

## 实验环境要求
- Kubernetes集群：v1.25+
- Istio版本：1.18+
- 测试服务：Bookinfo应用
- 监控工具：Prometheus, Jaeger
- 负载生成器：Apache Bench/wrk

## 文件说明
- `config/`: 测试配置文件
- `test_cases/`: 具体测试用例
- `scripts/`: 自动化测试脚本
- `results/`: 测试结果和报告
- `metrics/`: 评估指标计算工具

## 运行静态实验
cd evaluation/effectiveness/experiments/static_consistency_test

# 运行完整测试套件
python scripts/run_static_test.py --suite all

# 运行特定用例
python scripts/run_static_test.py --config input_configs/inconsistent/vs_dr_mismatch.yaml


## 运行动态实验
cd evaluation/effectiveness/experiments/dynamic_consistency_test

# 环境设置
python scripts/run_dynamic_test.py --setup-only

# 运行所有场景
python scripts/run_dynamic_test.py

# 运行特定场景
python scripts/run_dynamic_test.py --scenario traffic_split_anomaly