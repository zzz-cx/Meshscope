# Istio 配置监控与导出（`istio_monitor`）

MeshScope 的配置数据源：从集群拉取控制面与数据面配置，落盘后给 parser 做对齐。动态验证和 checker 不再直接当 YAML 解析入口。

## 在系统中的位置

```text
集群 (K8s + Istio)
    ↓  istio_monitor 导出
istio_control_config / istio_sidecar_config / istio_ingress_config
    ↓  python -m istio_config_parser.main_parser
aligned_semantic.json
    ↓  istio_Dynamic_Test（期望来自对齐模型）
    ↓  consistency_checker（消费产物）
```

| 下游模块 | 使用的目录 / 能力 |
|----------|-------------------|
| `istio_config_parser.main_parser` | `--control-plane-dir`、`--data-plane-dir`、`--ingress-plane-dir` |
| `istio_Dynamic_Test` | `--control-plane-config`（默认本目录下 `istio_control_config`） |
| `consistency_checker` / `e2e_validator` | 通过 `IstioSidecarMonitor` 拉取并解析 |
| `evaluation/*` | 消融 / e2e 实验前刷新控制面快照 |

## 目录结构

```text
istio_monitor/
├── istio_api.py                      # Istio / K8s API 客户端（SSH、kubectl、istioctl）
├── istio_config_parser.py            # 监控目录内 YAML/JSON 的轻量解析
├── export_control_plane_config.py    # 导出控制面 CRD → istio_control_config/
├── export_data_plane_config.py       # 导出 Sidecar Envoy → istio_sidecar_config/
├── export_ingress_gateway_config.py  # 导出 Ingress Gateway → istio_ingress_config/
├── istio_sidecar_monitor.py          # 编排：定期/即时拉取 + 变更回调
├── istio_control_config/             # 控制面快照（按资源类型/命名空间）
├── istio_sidecar_config/             # 数据面快照（routes/clusters/listeners JSON）
└── istio_ingress_config/             # 入口 Gateway 快照
```

## 快速开始

在项目根目录执行（推荐 `python -m` 形式）：

```bash
# 1. 导出控制面（VirtualService、DestinationRule 等）
python -m istio_config_parser.istio_monitor.export_control_plane_config

# 2. 导出数据面 Sidecar（routes / clusters / listeners）
python -m istio_config_parser.istio_monitor.export_data_plane_config --method istioctl

# 3. 导出 Ingress Gateway（入口 VS / Gateway 绑定校验）
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method kubectl-exec

# 4. 静态解析（使用上述目录）
python -m istio_config_parser.main_parser \
  --namespace default \
  --control-plane-dir istio_config_parser/istio_monitor/istio_control_config \
  --data-plane-dir istio_config_parser/istio_monitor/istio_sidecar_config \
  --ingress-plane-dir istio_config_parser/istio_monitor/istio_ingress_config \
  --export
```

远程集群（SSH 到节点执行 kubectl）：

```bash
python -m istio_config_parser.istio_monitor.export_control_plane_config \
  --k8s-host <节点IP> --k8s-user root --k8s-password <密码>

python -m istio_config_parser.istio_monitor.export_data_plane_config \
  --method kubectl-exec --pod <pod名> -n default
```

## 模块说明

### `export_control_plane_config.py`

- **输出**：`istio_control_config/`（按类型分子目录：`virtualservices/`、`destinationrules/`、`services/` …）
- **用途**：静态 IR、正交用例生成输入、动态验证前配置同步

```bash
python -m istio_config_parser.istio_monitor.export_control_plane_config -o ./istio_control_config
python -m istio_config_parser.istio_monitor.export_control_plane_config --k8s-host <host> --k8s-token <token>
```

### `export_data_plane_config.py`

- **输出**：`istio_sidecar_config/` 下 `routes.json`、`clusters.json`、`listeners.json` 等
- **方法**：`istioctl`（推荐）、`kubectl-exec`、`from-yaml`（从已有 dump 解析）

```bash
python -m istio_config_parser.istio_monitor.export_data_plane_config --method istioctl
python -m istio_config_parser.istio_monitor.export_data_plane_config \
  --pod <pod> -n default --method kubectl-exec
```

### `export_ingress_gateway_config.py`

- **输出**：`istio_ingress_config/`
- **用途**：校验绑定在 Ingress Gateway 上的 VirtualService（如 `frontend-ingress`、`bookinfo`），**不会**出现在普通 Sidecar 配置中

```bash
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method kubectl-exec
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config \
  -o istio_config_parser/istio_monitor/istio_ingress_config
```

### `istio_sidecar_monitor.py`

编排控制面 + 数据面导出，支持定期监控、即时更新、变更回调。

| 模式 | 命令 |
|------|------|
| 持续监控 | `python -m istio_config_parser.istio_monitor.istio_sidecar_monitor --vm-host <IP>` |
| 立即导出 | 加 `--update-now` |
| 仅导出 | 加 `--export-only` |

```bash
python -m istio_config_parser.istio_monitor.istio_sidecar_monitor \
  --vm-host <IP> --vm-user root --vm-password <密码> \
  --interval 60 \
  --output-dir istio_config_parser/istio_monitor
```

### `istio_api.py`

供脚本或评估代码导入的 API 封装：

```python
from istio_config_parser.istio_monitor.istio_api import IstioAPI

api = IstioAPI(
    use_vm=True,
    vm_host="192.168.92.131",
    vm_user="root",
    vm_password="<密码>",
)
vs = api.get_virtual_services(namespace="default")
```

常用方法：`get_virtual_services`、`get_destination_rules`、`get_envoy_filters`、`get_service_mesh_overview`、`export_config` 等。

### `istio_config_parser.py`（本目录）

解析 `istio_control_config` / `istio_sidecar_config` 下的文件，提取限流、路由等片段（与顶层 `istio_config_parser.parsers` 主解析器互补）。

## 与动态验证的衔接

动态模块默认从控制面目录同步最新 VS/DR：

```bash
python -m istio_Dynamic_Test.cmd \
  --from-control-plane \
  --control-plane-config istio_config_parser/istio_monitor/istio_control_config \
  --ingress-url http://<host>:<port>/productpage \
  --ssh-host <host> --ssh-user root --ssh-password <pwd>
```

或先导出再指定本地 JSON：

```bash
python -m istio_Dynamic_Test.cmd \
  -i istio_Dynamic_Test/configs/istio_config.json \
  --ingress-url http://<host>:<port>/productpage \
  --ssh-host <host>
```

动态验证支持 **HTTP**（curl/hey）与 **gRPC**（grpcurl）；Envoy 访问日志含 `grpc_status` 字段（见 `istio_Dynamic_Test` 模块文档）。

## 依赖与环境

- Python 3.7+
- 集群侧：`kubectl`、`istioctl`（按导出方式选用）
- 远程节点：SSH（`paramiko`），见项目根目录 `requirements.txt`
- 可选：`kubernetes`、`watchdog`（API / 文件监控）

## 故障排除

| 现象 | 建议 |
|------|------|
| SSH / kubectl 失败 | 检查 `--vm-host`、账号密码、kubeconfig |
| 缺少 `clusters.json` / `listeners.json` | 运行 `export_data_plane_config --method istioctl` |
| Gateway VS 校验无数据 | 运行 `export_ingress_gateway_config` 并在 `main_parser` 传入 `--ingress-plane-dir` |
| 监控无变更 | 增大 `--interval` 或 `--update-now` 手动刷新 |

## 相关文档

- [静态解析模块 README](../README.md)
- [MeshScope 总览](../../README.md)
- [目录结构说明](../../docs/DIRECTORY_STRUCTURE.md)
- [Ingress Gateway 配置说明](../../docs/INGRESS_GATEWAY_CONFIG.md)
