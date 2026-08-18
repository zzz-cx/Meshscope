# MeshScope - Istio 配置验证与可视化系统

> 端到端的 Istio 服务网格配置分析、动态验证与一致性检测平台

统一入口为 **ConfigPilot**（`python -m configpilot`）。底层三个模块职责分开，不要交叉解析：

| 模块 | 目录 | 职责 |
|------|------|------|
| parser | `istio_config_parser/` | YAML + Envoy dump → 一套语义模型，做控制面↔数据面对齐和跨资源冲突 |
| 动态验证 | `istio_Dynamic_Test/` | 期望只来自对齐模型，发流量并对照观测 |
| checker | `consistency_checker/` | 消费产物，做一致性判定、三层图和 Web UI |

```text
[K8s 集群]
    ↓ 采集 (istio_monitor)
控制面 YAML / Sidecar dump / Ingress dump
    ↓ 静态对齐 (parser)
aligned_semantic.json（语义元组 + 冲突 + 静态资源图）
    ↓ 动态验证 (istio_Dynamic_Test)
期望仅用 matched / partial_matched 元组，不再回退解析 YAML
    ↓ 一致性与可视化 (consistency_checker)
三层依赖图、报告、Web（静态资源图 / 三层图）
```

## 三大核心模块

### 模块一：静态配置分析 (`istio_config_parser/`)

| 项 | 说明 |
|----|------|
| 功能 | 将 VirtualService、DestinationRule、EnvoyFilter 等与 Envoy dump 映射到同一套语义元组，做平面对齐和跨资源冲突（缺 subset、路由优先级、Gateway 选择器等） |
| 配置来源 | `istio_monitor/` 导出的控制面、Sidecar、Ingress Gateway 目录 |
| 产物 | `results/consistency/aligned_semantic.json`（pairs、conflicts、expected_tuples、graph_data） |
| 入口 | `python -m configpilot static --namespace default` |

详见 [istio_config_parser/README.md](istio_config_parser/README.md)、[配置监控说明](istio_config_parser/istio_monitor/README.md)。

### 模块二：动态测试与验证 (`istio_Dynamic_Test/`)

| 项 | 说明 |
|----|------|
| 功能 | 从对齐模型生成正交用例 → 发流量 → Envoy/Prometheus 观测 → 策略校验 |
| 协议 | HTTP（curl / hey）、gRPC（grpcurl） |
| 约束 | 没有 `aligned_semantic.json` 时直接报错，不回退 YAML / `istio_config.json` |
| 入口 | `python -m configpilot dynamic -- --ingress-url http://HOST:PORT/productpage` |

详见 [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md)。

### 模块三：一致性验证与可视化 (`consistency_checker/`)

| 项 | 说明 |
|----|------|
| 功能 | 只消费静态对齐产物和动态结果，不再自己解析 YAML |
| 输出 | 一致性报告、三层配置依赖图、Web UI |
| 入口 | `python -m configpilot run` / `python -m configpilot web --port 8080` |

详见 [consistency_checker/README.md](consistency_checker/README.md)、[三层图](docs/THREE_LAYER_GRAPH.md)。

---

## 快速开始

### 前置条件

- Python 3.8+（推荐 3.10+）
- 可访问 Kubernetes 集群（本地 `kubectl` 或经 SSH 到节点执行）
- 动态测试远程节点建议具备：`curl`、`hey`（可选）、**grpcurl**（gRPC 用例）、`kubectl`

```bash
pip install -r requirements.txt
```

运行时可改项写在项目根目录 `configpilot.json`（集群地址、快照目录、Ingress、Prometheus、Web 端口）。Web 总览页改探测地址会写回同一文件。

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

Web 页面：

| 页 | 作用 |
|----|------|
| 总览 | 连通探测、运行时配置 |
| 静态分析 | 对齐摘要；按命名空间看服务 / Istio 资源，点节点看声明式 YAML 和对应数据面规则 |
| 动态验证 | 从对齐模型生成矩阵并执行 |
| 一致性 | 消费静/动产物，生成三层图 |
| 三层依赖图 | 控制面 / 数据面 / 配置资源；不一致边、Exp/Obs 流量权重、搜索与路径 |

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

### 方式 3：模块入口（仍可用）

```bash
python -m consistency_checker.main --mode full --namespace default
python -m consistency_checker.main --mode web --port 8080
python -m istio_config_parser.main_parser --namespace default --export
python -m istio_Dynamic_Test.cmd --help
```

### 方式 4：采集与分步

```bash
# 0. 从集群拉取快照
python -m istio_config_parser.istio_monitor.export_control_plane_config
python -m istio_config_parser.istio_monitor.export_data_plane_config --method istioctl
python -m istio_config_parser.istio_monitor.istio_sidecar_monitor \
  --vm-host ${SSH_HOST} --vm-user root --vm-password ${SSH_PASSWORD} --update-now

# 1. 静态对齐（写出 aligned_semantic.json）
python -m istio_config_parser.main_parser --namespace default --export

# 1b. （可选）Ingress Gateway dump
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method kubectl-exec

# 2. 动态验证（需已有对齐模型）
export SSH_HOST=192.168.92.100
python -m istio_Dynamic_Test.cmd \
  --from-control-plane \
  --ingress-url http://${SSH_HOST}:${INGRESS_PORT:-30476}/productpage \
  --ssh-host ${SSH_HOST} --ssh-user ${SSH_USER:-root} --ssh-password ${SSH_PASSWORD}

# 3. 一致性（只消费产物）
python -m configpilot check --namespace default
```

产物目录：

- `results/consistency/aligned_semantic.json` — 静态对齐模型
- `results/visualization/` — HTML 报告与三层图 JSON
- `istio_Dynamic_Test/results/` — 单次动态运行产物

### gRPC 动态验证（可选）

矩阵或 `request_params` 中设置 `"protocol": "grpc"`。SSH 主机或 mesh 内应用 Pod 需安装 **grpcurl**。详见 [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md#gRPC-用例示例矩阵-json)。

---

## 项目结构

```text
istio_check/
├── configpilot/                   # 统一 CLI：python -m configpilot
├── configpilot.json               # 运行时配置（集群、快照目录、Web 端口）
├── istio_config_parser/           # 静态解析与对齐
│   ├── main_parser.py             # parse_static_semantic / aligned_semantic
│   ├── parsers/                   # 统一解析器
│   └── istio_monitor/             # 控制面 / 数据面 / Ingress 采集
├── istio_Dynamic_Test/            # 动态验证流水线
│   ├── cmd/
│   ├── internal/                  # testcase / traffic / telemetry / validation
│   └── pkg/                       # SSH、K8s、观测发现
├── consistency_checker/           # 一致性判定 + 可视化 + Web
│   ├── core/                      # 只消费产物
│   ├── visualizer/                # 三层图生成
│   └── web/                       # Flask + 静态资源图 / 三层图查看器
├── evaluation/                    # 实验脚本
├── docker/
├── docs/
├── results/                       # 运行产物（建议 gitignore）
└── requirements.txt
```

工程级目录说明：[docs/DIRECTORY_STRUCTURE.md](docs/DIRECTORY_STRUCTURE.md)。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统设计与模块边界 |
| [docs/module_architecture.md](docs/module_architecture.md) | 数据契约与数据流 |
| [docs/THREE_LAYER_GRAPH.md](docs/THREE_LAYER_GRAPH.md) | 三层依赖图与查看器 |
| [docs/INGRESS_GATEWAY_CONFIG.md](docs/INGRESS_GATEWAY_CONFIG.md) | Ingress dump 采集 |
| [docs/REMOTE_CLUSTER_SETUP.md](docs/REMOTE_CLUSTER_SETUP.md) | 远程集群 kubeconfig |
| [docs/E2E_VALIDATOR_README.md](docs/E2E_VALIDATOR_README.md) | 端到端验证框架 |
| [istio_config_parser/README.md](istio_config_parser/README.md) | 静态解析 |
| [istio_config_parser/istio_monitor/README.md](istio_config_parser/istio_monitor/README.md) | 配置采集 |
| [istio_Dynamic_Test/README.md](istio_Dynamic_Test/README.md) | 动态验证 |
| [consistency_checker/README.md](consistency_checker/README.md) | 一致性与 Web |
| [docker/DOCKER_README.md](docker/DOCKER_README.md) | Docker 总览 |

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

```bash
git clone <repository-url>
cd istio_check
pip install -r requirements.txt
```

---

## 贡献

欢迎 Issue / PR。开发前请阅读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 与各模块 README。parser 负责解析与对齐，动态模块不要回退解析 YAML，checker 不要重新解析配置。避免使用已移除路径（如 `istio_Dynamic_Test/generator/`、`checker/`、`verifier/`）。

## 许可证

MIT License
