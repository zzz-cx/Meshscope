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

### 模块三：一致性验证与可视化模块 (`consistency_checker/`)
- **功能**：融合静态与动态结果，进行一致性判定与可视化
- **输出**：一致性图谱、偏差分析、修复建议、Web可视化界面
- **技术**：双重验证、根因分析、影响路径追踪、交互式图谱

## 🚀 快速开始

### 方式1：使用端到端验证框架（推荐）⭐

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整端到端验证流程
python e2e_validator.py \
  --vm-host 192.168.92.131 \
  --vm-user root \
  --vm-password 12345678 \
  --namespace default \
  --ingress-url http://192.168.92.131:30476/productpage
```

**功能**：
- ✅ 自动获取配置（控制平面 + 数据平面）
- ✅ 解析静态配置并生成 IR
- ✅ 生成正交测试策略
- ✅ 执行动态请求并收集日志
- ✅ 动态验证和一致性分析
- ✅ 生成完整报告

### 方式2：使用 Docker 部署（推荐）🐳

```bash
# 构建镜像
docker build -t meshscope:latest -f docker/Dockerfile .

# 运行端到端验证
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.168.92.131 \
  --vm-user root \
  --vm-password 12345678

# 或使用便捷脚本
cd docker
./docker-run.sh --build
./docker-run.sh --run
```

**优势**：
- ✅ 环境隔离，无需本地安装依赖
- ✅ 支持所有功能模块
- ✅ 统一入口，易于使用
- ✅ 跨平台支持

详细说明请参考 [Docker 部署文档](docker/DOCKER_README.md)

### 方式3：使用统一流水线

```bash
# 安装依赖
pip install -r requirements.txt

# 运行完整验证流程（包含静态分析+动态测试+一致性检查）
python -m consistency_checker.main --mode full --namespace default

# 或启动Web可视化界面
python -m consistency_checker.main --mode web --port 8080
# 访问 http://localhost:8080
```

### 方式4：分步执行

```bash
# 1. 静态分析
python -m istio_config_parser.main_parser --namespace default

# 2. 动态测试
cd istio_Dynamic_Test
python generator/test_case_generator.py -i generator/istio_config.json \
  --service-deps service_dependencies.json \
  --ingress-url http://192.168.92.131:30476/productpage \
  -o output_matrix.json

python checker/traffic_driver.py -i output_matrix.json \
  --ssh-host 192.168.92.131 --ssh-user root --ssh-password 12345678

python verifier/main_verifier.py --matrix output_matrix.json \
  --logs results/envoy_logs --output results/verification

# 3. 一致性验证
cd ..
python -m consistency_checker.main --mode consistency --namespace default

# 4. 查看报告
open results/visualization/report_*_report.html  # HTML报告
open results/verification/istio_verification_*.html  # 动态测试报告
```

## 📁 项目结构

```
istio_check/
├── istio_config_parser/      # 静态配置分析模块
├── istio_Dynamic_Test/        # 动态测试与验证模块
├── consistency_checker/       # 一致性验证与可视化模块
├── evaluation/                # 评估模块
├── docker/                    # Docker 部署文件
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── entrypoint.sh
│   └── *.md                   # Docker 相关文档
├── docs/                      # 项目文档
│   ├── ARCHITECTURE.md
│   ├── E2E_VALIDATOR_README.md
│   └── module_architecture.md
├── scripts/                   # 辅助脚本
├── results/                   # 运行结果输出
├── e2e_validator.py          # 端到端验证主程序
└── requirements.txt          # Python 依赖
```

详细目录结构请参考 [DIRECTORY_STRUCTURE.md](DIRECTORY_STRUCTURE.md)

## 📚 详细文档

### 核心文档

- **[端到端验证框架](docs/E2E_VALIDATOR_README.md)** - 完整端到端验证流程使用指南 🔥
- **[模块架构与通信设计](docs/module_architecture.md)** - 三大模块接口、数据流与通信规范 🔥
- **[系统架构文档](docs/ARCHITECTURE.md)** - 三大模块详细设计与协作流程

### Docker 部署文档

- **[Docker 完整指南](docker/DOCKER_COMPLETE_GUIDE.md)** - Docker 部署完整功能支持 🔥
- **[Docker 使用说明](docker/DOCKER_USAGE.md)** - Docker 详细使用文档
- **[Docker 快速开始](docker/DOCKER_QUICKSTART.md)** - Docker 快速入门
- **[Docker 构建说明](docker/BUILD.md)** - Docker 构建详细说明

### 模块文档

- [静态分析模块文档](istio_config_parser/README.md)
- [动态测试模块文档](istio_Dynamic_Test/README.md)
- [一致性验证模块文档](consistency_checker/README.md)

## 🎯 核心价值

- ✅ **全面覆盖**：静态+动态+一致性三位一体验证
- 🚀 **高效验证**：正交设计减少50%+测试用例
- 🎯 **精准定位**：自动根因分析与修复建议
- 📊 **可视化展示**：交互式图谱与报告
- 🔧 **DevOps友好**：支持CI/CD集成
- 🐳 **容器化部署**：Docker 支持，环境隔离

## 🛠️ 主要功能

### 端到端验证 (`e2e_validator.py`)

一键运行完整的验证流程：

```bash
python e2e_validator.py \
  --vm-host <host> \
  --vm-user <user> \
  --vm-password <password> \
  --namespace <namespace> \
  --ingress-url <url>
```

**流程包括**：
1. 监控器获取配置（控制平面 + 数据平面）
2. 解析静态配置
3. 生成 IR 中间表示
4. 生成正交测试策略
5. 发送动态请求
6. 收集日志数据
7. 动态验证
8. 一致性分析和可视化

### Docker 部署

支持完整的 Docker 容器化部署：

```bash
# 构建镜像
docker build -t meshscope:latest -f docker/Dockerfile .

# 运行各种功能
docker run -it --rm meshscope:latest e2e --vm-host 192.168.92.131
docker run -it --rm meshscope:latest static --namespace default
docker run -it --rm meshscope:latest consistency --mode full
docker run -it --rm -p 8080:8080 meshscope:latest web --port 8080
```

### Web 可视化界面

启动交互式 Web 界面查看验证结果：

```bash
python -m consistency_checker.main --mode web --port 8080
# 访问 http://localhost:8080
```

## 📋 系统要求

- **Python**: 3.7+
- **依赖**: 见 `requirements.txt`
- **Kubernetes**: 需要访问 Kubernetes 集群（或通过 SSH）
- **Docker**: 可选，用于容器化部署

## 🔧 安装

### 本地安装

```bash
# 克隆项目
git clone <repository-url>
cd istio_check

# 安装依赖
pip install -r requirements.txt
```

### Docker 安装

```bash
# 构建镜像
docker build -t meshscope:latest -f docker/Dockerfile .

# 或使用 docker-compose
cd docker
docker-compose build
```

## 📖 使用示例

### 示例1：端到端验证

```bash
python e2e_validator.py \
  --vm-host 192.168.92.131 \
  --vm-user root \
  --vm-password 12345678 \
  --namespace default \
  --ingress-url http://192.168.92.131:30476/productpage \
  --output-dir results/my_test
```

### 示例2：Docker 部署

```bash
# 使用 Docker Compose
cd docker
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 示例3：Web 可视化

```bash
# 启动 Web 服务
python -m consistency_checker.main --mode web --port 8080

# 或使用 Docker
docker run -it --rm -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest web --port 8080
```

## 🤝 贡献

欢迎贡献代码、文档或提出建议！

- 查看 [架构文档](docs/ARCHITECTURE.md) 了解系统设计
- 查看 [目录结构](DIRECTORY_STRUCTURE.md) 了解项目组织
- 提交 Issue 或 Pull Request

## 📄 许可证

MIT License

---

**让 Istio 配置验证更简单、更可靠！** 🚀
