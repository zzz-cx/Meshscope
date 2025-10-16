# MeshScope - Istio 配置验证与可视化系统

> 一个完整的 Istio 服务网格配置分析、动态验证与一致性检测平台

## 🎯 系统概述

MeshScope 是一个端到端的 Istio 配置验证解决方案，通过**静态分析**、**动态验证**和**一致性检测**三大模块，确保 Istio 服务网格配置的正确性与一致性。

```
配置文件 → [静态分析] → 配置图谱 → [动态验证] → 行为数据 → [一致性检测] → 验证报告
```

## 📐 三大核心模块

### 模块一：静态配置分析模块 (`istio_config_parser/`)
- **功能**：解析 Istio 控制面配置，构建服务拓扑图谱
- **输出**：配置图谱、策略清单、冲突报告
- **技术**：配置解析、拓扑构建、可视化展示

### 模块二：动态测试与验证模块 (`istio_Dynamic_Test/`)
- **功能**：基于正交设计生成测试用例，执行动态流量验证
- **输出**：HTTP 结果、Envoy 日志、验证报告
- **技术**：正交设计、自动故障注入、多维度验证

### 模块三：一致性验证与可视化模块 (`consistency_checker/`) ⭐ 新增
- **功能**：融合静态与动态结果，进行一致性判定与可视化
- **输出**：一致性图谱、偏差分析、修复建议、Web可视化界面
- **技术**：双重验证、根因分析、影响路径追踪、交互式图谱

## 🚀 快速开始

### 方式1：使用统一流水线（推荐）⭐

```bash
# 安装依赖
cd consistency_checker
pip install -r requirements.txt

# 运行完整验证流程（包含静态分析+动态测试+一致性检查）
python -m consistency_checker.main --mode full --namespace online-boutique

# 或启动Web可视化界面
python -m consistency_checker.main --mode web --port 8080
# 访问 http://localhost:8080
```

### 方式2：分步执行

```bash
# 1. 静态分析
cd istio_config_parser
python main_parser.py --namespace default

# 2. 动态测试
cd ../istio_Dynamic_Test
python generator/test_case_generator.py -i generator/istio_config.json \
  --service-deps service_dependencies.json \
  --ingress-url http://192.168.92.131:30476/productpage \
  -o output_matrix.json

python checker/traffic_driver.py -i output_matrix.json \
  --ssh-host 192.168.92.131 --ssh-user root --ssh-password 12345678

python verifier/main_verifier.py --matrix output_matrix.json \
  --logs results/envoy_logs --output results/verification

# 3. 一致性验证 ⭐
cd ..
python -m consistency_checker.main --mode consistency --namespace online-boutique

# 4. 查看报告
open results/visualization/report_*_report.html  # HTML报告
open results/verification/istio_verification_*.html  # 动态测试报告
```

## 📚 详细文档

- **[完整使用指南](SYSTEM_GUIDE.md)** - 端到端使用流程与最佳实践 🔥
- **[模块架构与通信设计](docs/module_architecture.md)** - 三大模块接口、数据流与通信规范 🔥
- [完整架构文档](ARCHITECTURE.md) - 三大模块详细设计与协作流程
- [静态分析模块文档](istio_config_parser/README.md)
- [动态测试模块文档](istio_Dynamic_Test/README.md)
- [一致性验证模块文档](consistency_checker/README.md) ⭐

## 🎯 核心价值

- ✅ **全面覆盖**：静态+动态+一致性三位一体验证
- 🚀 **高效验证**：正交设计减少50%+测试用例
- 🎯 **精准定位**：自动根因分析与修复建议
- 📊 **可视化展示**：交互式图谱与报告
- 🔧 **DevOps友好**：支持CI/CD集成

## 🤝 贡献

欢迎贡献代码、文档或提出建议！详见 [ARCHITECTURE.md](ARCHITECTURE.md)

## 📄 许可证

MIT License

---

**让 Istio 配置验证更简单、更可靠！** 🚀