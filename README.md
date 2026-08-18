# MeshScope - Istio 配置验证与可视化系统

> 端到端的 Istio 服务网格配置分析、动态验证与一致性检测平台

## 系统概述

MeshScope 通过**静态分析**、**动态验证**和**一致性检测**三大模块，验证 Istio 配置是否与运行时行为一致。

```text
[K8s 集群]
    ↓ 配置采集 (istio_monitor)
控制面 / 数据面 / Ingress Gateway 快照
    ↓ 静态分析 (istio_config_parser)
配置图谱、IR、冲突报告
    ↓ 动态验证 (istio_Dynamic_Test)
HTTP/gRPC 流量 + Envoy/Prometheus 观测 + 策略校验
    ↓ 一致性检测 (consistency_checker)
一致性图谱、偏差分析、Web 可视化
```

## 三大核心模块

### 模块一：静态配置分析 (`istio_config_parser/`)

| 项 | 说明 |
|----|------|
| 功能 | 解析 VirtualService、DestinationRule、EnvoyFilter 等，构建 IR 与拓扑 |
| 配置来源 | `istio_monitor/` 导出的控制面、Sidecar、Ingress Gateway 目录 |
| 输出 | 功能模型、一致性摘要、可视化数据 |
| 入口 | `python -m istio_config_parser.main_parser` |

详见 [istio_config_parser/README.md](istio_config_parser/README.md)、[配置监控说明](istio_config_parser/istio_monitor/README.md)。

### 模块二：动态测试与验证 (`istio_Dynamic_Test/`)

| 项 | 说明 |
|----|------|
| 功能 | 正交用例生成 → 发流量 → 采集观测 → 多策略验证 |
| 协议 | **HTTP**（curl / hey）、**gRPC**（grpcurl，需远程或 Pod 内安装） |
| 流水线 | `testcase` → `traffic` → `telemetry` → `validation`（`DynamicTester`） |
| 输出 | `results/http_results`、`results/grpc_results`、Envoy 日志、验证报告 |
| 入口 | `python -m istio_Dynamic_Test.cmd` |

详见 [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md)。

### 模块三：一致性验证与可视化 (`consistency_checker/`)

| 项 | 说明 |
|----|------|
| 功能 | 融合静态 IR 与动态结果，判定配置–行为一致性 |
| 输出 | 一致性图谱、三层图、HTML 报告、Web UI |
| 入口 | `python -m consistency_checker.main --mode full` / `--mode web` |

详见 [consistency_checker/README.md](consistency_checker/README.md)。

---

## 快速开始

### 前置条件

- Python 3.8+（推荐 3.10+）
- 可访问 Kubernetes 集群（本地 `kubectl` 或经 **SSH** 到节点执行）
- 动态测试远程节点建议具备：`curl`、`hey`（可选）、**grpcurl**（gRPC 用例）、`kubectl`

```bash
pip install -r requirements.txt
```

### 方式 1：统一入口（推荐）

```bash
# 完整流水线
python -m configpilot run --namespace default

# Web 可视化（浏览器访问 http://localhost:8080）
python -m configpilot web --port 8080

# 分步
python -m configpilot collect --vm-host 192.168.92.100 --vm-user root --vm-password <password>
python -m configpilot static --namespace default --export
python -m configpilot dynamic -- --from-control-plane --ingress-url http://192.168.92.100:30476/productpage
python -m configpilot check --namespace default
```

### 方式 2：Docker 部署

```bash
docker build -t meshscope:latest -f docker/Dockerfile .

docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.168.92.100 \
  --vm-user root \
  --vm-password <password>
```

更多命令见 [docker/DOCKER_README.md](docker/DOCKER_README.md)、[docker/DOCKER_COMPLETE_GUIDE.md](docker/DOCKER_COMPLETE_GUIDE.md)。

### 方式 3：一致性一站式

```bash
python -m consistency_checker.main --mode full --namespace default

# Web 可视化
python -m consistency_checker.main --mode web --port 8080
# 浏览器访问 http://localhost:8080
```

### 方式 4：分步执行

```bash
# 0. （推荐）从集群拉取最新 Istio 配置快照
python -m istio_config_parser.istio_monitor.export_control_plane_config
python -m istio_config_parser.istio_monitor.export_data_plane_config --method istioctl
# 或一键监控导出
python -m istio_config_parser.istio_monitor.istio_sidecar_monitor \
  --vm-host ${SSH_HOST} --vm-user root --vm-password ${SSH_PASSWORD} --update-now

# 1. 静态分析（默认读取 istio_monitor 下目录）
python -m istio_config_parser.main_parser --namespace default --export

# 1b. （可选）Ingress Gateway 配置 + 入口 VS 一致性
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method kubectl-exec
python -m istio_config_parser.main_parser \
  --ingress-plane-dir istio_config_parser/istio_monitor/istio_ingress_config \
  --summary --details

# 2. 动态验证（CLI 入口）
export SSH_HOST=192.168.92.100
export SSH_PASSWORD=<password>

# 从 Istio JSON 生成用例并执行（可同步控制面目录）
python -m istio_Dynamic_Test.cmd \
  -i istio_Dynamic_Test/configs/istio_config.json \
  --ingress-url http://${SSH_HOST}:${INGRESS_PORT:-30476}/productpage \
  --ssh-host ${SSH_HOST} --ssh-user ${SSH_USER:-root} --ssh-password ${SSH_PASSWORD}

# 或直接从控制面快照生成用例（无需 -i）
python -m istio_Dynamic_Test.cmd \
  --from-control-plane \
  --ingress-url http://${SSH_HOST}:${INGRESS_PORT:-30476}/productpage \
  --ssh-host ${SSH_HOST} --ssh-user ${SSH_USER:-root} --ssh-password ${SSH_PASSWORD}

# 或从已有测试矩阵运行
python -m istio_Dynamic_Test.cmd \
  --matrix istio_Dynamic_Test/configs/output_matrix.json \
  --ingress-url http://${SSH_HOST}:${INGRESS_PORT:-30476}/productpage \
  --ssh-host ${SSH_HOST} --ssh-user ${SSH_USER:-root} --ssh-password ${SSH_PASSWORD}

# 流量分割等场景可附加 Prometheus
python -m istio_Dynamic_Test.cmd \
  -i istio_Dynamic_Test/configs/istio_config.json \
  --prometheus-url http://${SSH_HOST}:31012 \
  --ssh-host ${SSH_HOST} --ssh-user root --ssh-password ${SSH_PASSWORD}

# 3. 一致性验证
python -m consistency_checker.main --mode consistency --namespace default

# 4. 查看报告
# results/visualization/          — 一致性 HTML
# results/verification/         — 动态验证报告
# istio_Dynamic_Test/results/   — 单次动态运行产物
```

### gRPC 动态验证（可选）

矩阵或 `request_params` 中设置 `"protocol": "grpc"`，并指定方法名，例如：

```json
{
  "protocol": "grpc",
  "host": "reviews",
  "path": "/grpc.health.v1.Health/Check",
  "grpc_data": "{}"
}
```

SSH 主机或 mesh 内应用 Pod 需安装 **grpcurl**；Envoy 访问日志会记录 `grpc_status` 字段用于采集与校验。详见 [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md#gRPC-用例示例矩阵-json)。

---

## 项目结构

```text
istio_check/
├── istio_config_parser/           # 静态解析
│   ├── main_parser.py
│   ├── parsers/                   # 统一解析器
│   └── istio_monitor/             # 控制面/数据面/Ingress 配置采集
│       ├── export_control_plane_config.py
│       ├── export_data_plane_config.py
│       ├── export_ingress_gateway_config.py
│       ├── istio_sidecar_monitor.py
│       ├── istio_control_config/  # 控制面快照（VS/DR/Service…）
│       ├── istio_sidecar_config/  # Sidecar Envoy 快照
│       └── istio_ingress_config/  # Ingress Gateway 快照
├── istio_Dynamic_Test/            # 动态验证流水线
│   ├── cmd/                       # python -m istio_Dynamic_Test.cmd
│   ├── internal/                  # models / testcase / traffic / telemetry / validation / pipeline
│   ├── pkg/                       # SSH、K8s、观测发现
│   └── configs/                   # istio_config.json、output_matrix.json 等
├── consistency_checker/           # 一致性 + 可视化 + Web
├── evaluation/                    # 准确性 / 有效性 / e2e 等实验脚本
├── docker/                        # 镜像、entrypoint、Compose
├── docs/                          # 架构与设计文档
├── results/                       # 全局运行结果（建议 gitignore）
├── e2e_validator.py               # 端到端编排入口
└── requirements.txt
```

工程级目录说明：[docs/DIRECTORY_STRUCTURE.md](docs/DIRECTORY_STRUCTURE.md)。

---

## 文档索引

### 核心

| 文档 | 内容 |
|------|------|
| [docs/E2E_VALIDATOR_README.md](docs/E2E_VALIDATOR_README.md) | 端到端验证框架 |
| [docs/module_architecture.md](docs/module_architecture.md) | 模块接口与数据流 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统设计（部分章节可能与 v2 目录并存，以模块 README 为准） |

### Docker

| 文档 | 内容 |
|------|------|
| [docker/DOCKER_README.md](docker/DOCKER_README.md) | Docker 总览 |
| [docker/DOCKER_COMPLETE_GUIDE.md](docker/DOCKER_COMPLETE_GUIDE.md) | 完整功能与示例 |
| [docker/DOCKER_USAGE.md](docker/DOCKER_USAGE.md) | 详细用法 |
| [docker/DOCKER_QUICKSTART.md](docker/DOCKER_QUICKSTART.md) | 快速入门 |

### 模块

| 文档 | 内容 |
|------|------|
| [istio_config_parser/README.md](istio_config_parser/README.md) | 静态解析 |
| [istio_config_parser/istio_monitor/README.md](istio_config_parser/istio_monitor/README.md) | 配置采集与监控 |
| [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md) | 动态验证流水线 |
| [consistency_checker/README.md](consistency_checker/README.md) | 一致性检测 |

---

## 核心价值

- **全链路**：配置采集 → 静态 IR → 动态 HTTP/gRPC → 一致性图谱
- **高效**：正交设计压缩用例规模
- **可观测**：Envoy 日志（含 `grpc_status`）、Prometheus 增量校验
- **可集成**：CLI / Docker / Web，适合 CI 与人工排查

---

## 系统要求

| 组件 | 要求 |
|------|------|
| Python | 3.8+ |
| 集群 | Kubernetes + Istio（BookInfo / online-boutique 等样例） |
| 网络 | 入口 URL（NodePort / LB）及可选 Prometheus |
| 远程执行 | SSH 到可执行 `kubectl` 的节点（动态测试） |
| gRPC | 远程或 Pod 内 **grpcurl** |
| Docker | 可选 |

---

## 安装

```bash
git clone <repository-url>
cd istio_check
pip install -r requirements.txt
```

Docker：

```bash
docker build -t meshscope:latest -f docker/Dockerfile .
```

---

## 常用命令速查

```bash
# 静态
python -m istio_config_parser.main_parser --namespace default --export

# 配置监控（立即导出）
python -m istio_config_parser.istio_monitor.istio_sidecar_monitor --vm-host <host> --update-now

# 动态（帮助）
python -m istio_Dynamic_Test.cmd --help

# 一致性 Web
python -m consistency_checker.main --mode web --port 8080

# 端到端
python e2e_validator.py --vm-host <host> --vm-user root --vm-password <pwd> \
  --ingress-url http://<host>:30476/productpage
```

---

## 贡献

欢迎 Issue / PR。开发前建议阅读 [docs/DIRECTORY_STRUCTURE.md](docs/DIRECTORY_STRUCTURE.md) 与各模块 README，避免使用已移除的旧路径（如 `istio_Dynamic_Test/generator/`、`checker/`、`verifier/`）。

## 许可证

MIT License

---

**让 Istio 配置验证更简单、更可靠。**
