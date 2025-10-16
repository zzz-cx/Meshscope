# Istio API 客户端

这是一个用于连接 Istio 服务网格的 Python API 客户端，支持获取控制平面和数据平面的配置信息。

## 功能特点

- 支持通过 HTTP API 和 kubectl 命令行工具获取 Istio 配置
- 支持通过 SSH 连接到远程虚拟机执行命令
- 支持 Windows 和 Linux/Mac 环境
- 提供丰富的 API 获取各种 Istio 资源
- 包含配置解析器，可以解析和提取 Istio 配置中的关键信息
- 支持定时监控 Istio 配置变更，自动更新本地数据

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本用法

```python
from istio_api import IstioAPI

# 初始化 API 客户端
istio = IstioAPI(
    host="localhost",
    port=8080,
    namespace="istio-system",
    use_vm=True,
    vm_host="192.168.1.100",  # 虚拟机 IP
    vm_port=22,
    vm_user="root",
    vm_password="password"  # 虚拟机密码
)

# 获取 Istio 版本
version = istio.get_istio_version()
print(version)

# 获取虚拟服务
vs = istio.get_virtual_services()
print(vs)

# 获取服务网格概览
overview = istio.get_service_mesh_overview()
print(overview)
```

### 使用配置解析器

```python
from istio_config_parser import IstioConfigParser

# 初始化配置解析器
parser = IstioConfigParser()

# 解析配置文件
result = parser.parse_yaml_files('services.yaml', 'istio-config.yaml')

# 提取限流配置
rate_limits = parser.extract_rate_limits()
print(rate_limits)

# 提取流量路由配置
routing = parser.extract_traffic_routing()
print(routing)
```

### 运行测试脚本

```bash
python test_istio_api.py
```

### 使用配置监控工具

配置监控工具可以定时检查 Istio 配置变更，并自动更新本地数据。

```bash
# 1. 定期监控模式（支持即时更新）
python istio_sidecar_monitor.py --vm-host <虚拟机IP>
# 运行后，按 Enter 键可以触发即时更新

# 2. 立即更新模式
python istio_sidecar_monitor.py --vm-host <虚拟机IP> --update-now

# 3. 更新指定代理
python istio_sidecar_monitor.py --vm-host <虚拟机IP> --update-now --proxy-ids "proxy1,proxy2"
```

#### 在代码中使用监控器

```python
from istio_sidecar_monitor import IstioMonitor

# 定义配置变更回调函数
def my_callback(changes):
    print(f"配置已变更，变更项数量: {len(changes)}")
    for key in changes.keys():
        print(f"  - {key}")

# 创建监控器
monitor = IstioMonitor(
    interval=60,  # 检查间隔（秒）
    output_dir="./istio_config",
    vm_host="192.168.1.100",
    vm_user="root",
    vm_password="password",
    callback=my_callback  # 配置变更时的回调函数
)

# 导出当前配置
monitor.export_current_config()

# 启动监控
monitor.start()

# ... 应用程序逻辑 ...

# 停止监控
monitor.stop()
```

## API 参考

### 控制平面 API

- `get_istio_version()`: 获取 Istio 版本信息
- `get_control_plane_status()`: 获取控制平面状态
- `get_gateways()`: 获取所有网关
- `get_virtual_services(namespace=None)`: 获取虚拟服务
- `get_destination_rules(namespace=None)`: 获取目标规则
- `get_envoy_filters(namespace=None)`: 获取 Envoy 过滤器
- `get_service_entries(namespace=None)`: 获取服务条目
- `get_authorization_policies(namespace=None)`: 获取授权策略

### 数据平面 API

- `get_proxies()`: 获取所有代理（Sidecar）的列表
- `get_proxy_config(proxy_id, config_type)`: 获取代理配置
- `get_proxy_metrics(proxy_id)`: 获取代理指标

### 辅助方法

- `get_service_mesh_overview()`: 获取服务网格概览
- `get_service_dependencies(namespace=None)`: 获取服务依赖关系
- `get_rate_limits(namespace=None)`: 获取限流配置
- `get_fault_injection(namespace=None)`: 获取故障注入配置
- `export_config(output_dir)`: 导出 Istio 配置

### 监控器方法

- `start()`: 启动监控
- `stop()`: 停止监控
- `export_current_config()`: 导出当前配置

## 注意事项

1. 在 Windows 环境下，需要安装 `paramiko` 库来支持 SSH 连接
2. 确保虚拟机上已安装 `kubectl` 和 `istioctl` 命令行工具
3. 如果使用密钥文件连接，请确保密钥文件权限正确设置
4. 监控器会在检测到配置变更时自动更新本地数据，并调用回调函数

## 故障排除

- 如果无法连接到虚拟机，请检查 IP 地址、用户名和密码是否正确
- 如果 `kubectl` 命令执行失败，请确保虚拟机上已正确配置 Kubernetes 环境
- 如果 `istioctl` 命令执行失败，请确保虚拟机上已正确安装 Istio
- 如果监控器无法检测到配置变更，请检查检查间隔是否合适，以及是否有足够的权限访问配置

# Istio Sidecar 配置监控工具

这是一个用于监控 Istio 数据平面 Sidecar 配置的工具。它支持定期监控和即时更新两种模式，能够自动检测配置变更并保存最新配置。

## 功能特点

### 1. 多种监控模式

- **定期监控**：按设定的时间间隔自动检查配置变化
- **即时更新**：支持手动触发和自动触发的即时更新
- **文件系统监控**：监控 Istio 配置文件的变化
- **Kubernetes API 监控**：监听 Istio 相关资源的变更事件

### 2. 自动检测机制

工具通过以下三种方式自动检测配置变更：

1. **文件系统监控**
   - 监控指定目录下的 `.yaml` 和 `.yml` 文件变化
   - 当检测到文件变更时自动触发配置更新
   - 支持递归监控子目录

2. **Kubernetes API 监控**
   - 监听 Istio 相关资源（如 VirtualService）的变更事件
   - 实时响应 Kubernetes API 中的配置变化
   - 自动处理资源的增加、修改和删除事件

3. **定期配置检查**
   - 定期获取并比对配置，确保不会遗漏任何变化
   - 使用哈希值比对检测配置变更
   - 支持检查多种配置类型（clusters、listeners、routes、endpoints 等）

### 3. 配置管理

- 为每个代理创建独立的配置目录
- 按类型分别保存配置文件（JSON 格式）
- 支持导出当前完整配置
- 提供配置变更通知回调机制

## 安装

1. 安装依赖：
```bash
pip install -r requirements.txt
```

主要依赖包括：
```
requests>=2.25.0
paramiko>=2.7.0
kubernetes>=12.0.0
watchdog>=2.1.0
```

2. 确保有正确的权限访问：
   - Kubernetes 集群（如果使用 Kubernetes API 监控）
   - Istio 配置文件目录（如果使用文件系统监控）
   - 虚拟机访问权限（用于执行 istioctl 命令）

## 使用方法

### 1. 基本用法

```bash
python istio_sidecar_monitor.py --vm-host <虚拟机IP>
```

### 2. 完整参数说明

```bash
python istio_sidecar_monitor.py \
    --vm-host <虚拟机IP> \
    --vm-user root \
    --vm-password <密码> \
    --interval 60 \
    --namespace default \
    --output-dir ./istio_sidecar_config \
    --config-types clusters,listeners,routes,endpoints \
    --config-dir /path/to/istio/config
```

参数说明：
- `--interval`：检查间隔（秒）
- `--output-dir`：配置输出目录
- `--namespace`：要监控的命名空间（使用 'all' 监控所有命名空间）
- `--config-types`：要获取的配置类型，用逗号分隔
- `--vm-host`：虚拟机主机（必需）
- `--vm-port`：虚拟机 SSH 端口（默认 22）
- `--vm-user`：虚拟机用户名（默认 root）
- `--vm-password`：虚拟机密码
- `--vm-key-file`：虚拟机 SSH 密钥文件
- `--config-dir`：Istio 配置文件目录（用于文件系统监控）
- `--export-only`：仅导出当前配置，不启动监控
- `--update-now`：立即更新配置
- `--proxy-ids`：要更新的代理ID列表，用逗号分隔

### 3. 运行模式

1. **监控模式**（默认）：
```bash
python istio_sidecar_monitor.py --vm-host <虚拟机IP> --config-dir /path/to/istio/config
```
- 启动后会持续监控配置变化
- 按 Enter 键可触发即时更新
- 按 Ctrl+C 停止监控

2. **立即更新模式**：
```bash
python istio_sidecar_monitor.py --vm-host <虚拟机IP> --update-now
```
- 获取并保存当前配置后退出

3. **导出模式**：
```bash
python istio_sidecar_monitor.py --vm-host <虚拟机IP> --export-only
```
- 导出当前所有配置后退出

### 4. 配置变更通知

工具提供了配置变更通知机制：
- 可以通过回调函数处理配置变更事件
- 默认回调函数会打印变更信息
- 可以自定义回调函数进行扩展处理

## 输出说明

1. **日志输出**：
   - 所有操作日志保存在 `istio_sidecar_monitor.log`
   - 同时在控制台显示重要信息

2. **配置文件**：
   - 保存在指定的输出目录中（默认 `./istio_sidecar_config`）
   - 按代理 ID 创建子目录
   - 每种配置类型保存为独立的 JSON 文件

## 注意事项

1. 确保有足够的权限执行 istioctl 命令
2. 建议使用 SSH 密钥文件而不是密码进行认证
3. 监控大量代理时，建议适当增加检查间隔
4. 配置文件监控需要读取权限
5. Kubernetes API 监控需要集群访问权限

## 故障排除

1. 如果无法连接虚拟机：
   - 检查网络连接
   - 验证认证信息
   - 确认 SSH 服务状态

2. 如果配置更新失败：
   - 检查 istioctl 命令是否可用
   - 验证代理 ID 是否正确
   - 查看详细错误日志

3. 如果文件监控不工作：
   - 确认配置目录路径正确
   - 检查目录权限
   - 验证文件系统支持 inotify 