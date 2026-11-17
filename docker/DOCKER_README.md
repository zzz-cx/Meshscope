# MeshScope Docker 部署指南

本文档介绍如何使用 Docker 部署和运行 MeshScope 系统。

## 📋 目录

- [快速开始](#快速开始)
- [构建镜像](#构建镜像)
- [运行容器](#运行容器)
- [使用 Docker Compose](#使用-docker-compose)
- [配置说明](#配置说明)
- [常见问题](#常见问题)

## 🚀 快速开始

### 方式1：使用 Docker Compose（推荐）

```bash
# 1. 构建并启动服务
docker-compose up -d

# 2. 查看日志
docker-compose logs -f

# 3. 停止服务
docker-compose down
```

### 方式2：使用 Docker 命令

```bash
# 1. 构建镜像
docker build -t meshscope:latest .

# 2. 运行容器
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/istio_config_parser/istio_monitor/istio_control_config:/app/istio_config_parser/istio_monitor/istio_control_config:ro \
  -v $(pwd)/istio_config_parser/istio_monitor/istio_sidecar_config:/app/istio_config_parser/istio_monitor/istio_sidecar_config:ro \
  meshscope:latest \
  python e2e_validator.py \
    --vm-host 192.0.2.10 \
    --vm-user root \
    --vm-password <SSH_PASSWORD> \
    --namespace default \
    --ingress-url http://192.0.2.10:30476/productpage
```

## 🔨 构建镜像

### 基本构建

```bash
docker build -t meshscope:latest .
```

### 指定标签

```bash
docker build -t meshscope:v1.0.0 .
```

### 使用构建缓存

```bash
# 首次构建
docker build -t meshscope:latest .

# 后续构建（使用缓存）
docker build --cache-from meshscope:latest -t meshscope:latest .
```

## 🏃 运行容器

### 基本运行

```bash
docker run -it --rm meshscope:latest
```

### 挂载数据卷

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python e2e_validator.py --vm-host 192.0.2.10
```

### 访问 Kubernetes 集群

如果需要从容器内访问 Kubernetes 集群：

```bash
# 方式1：挂载 kubeconfig
docker run -it --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  meshscope:latest

# 方式2：使用 host 网络（仅 Linux）
docker run -it --rm \
  --network host \
  meshscope:latest
```

### 使用环境变量

```bash
docker run -it --rm \
  -e VM_HOST=192.0.2.10 \
  -e VM_USER=root \
  -e VM_PASSWORD=<SSH_PASSWORD> \
  -e NAMESPACE=default \
  meshscope:latest \
  python e2e_validator.py
```

## 🐳 使用 Docker Compose

### 基本使用

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f meshscope

# 停止服务
docker-compose down
```

### 使用环境变量文件

创建 `.env` 文件：

```env
VM_HOST=192.0.2.10
VM_USER=root
VM_PASSWORD=<SSH_PASSWORD>
NAMESPACE=default
INGRESS_URL=http://192.0.2.10:30476/productpage
OUTPUT_DIR=results/e2e_validation
```

然后运行：

```bash
docker-compose up -d
```

### 启动 Web 服务

```bash
# 启动 Web 可视化界面
docker-compose --profile web up -d meshscope-web

# 访问 http://localhost:8080
```

### 自定义配置

编辑 `docker-compose.yml` 文件，修改以下配置：

- **volumes**: 挂载的目录
- **ports**: 端口映射
- **environment**: 环境变量
- **command**: 启动命令

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `VM_HOST` | 虚拟机主机地址 | `192.0.2.10` |
| `VM_USER` | SSH 用户名 | `root` |
| `VM_PASSWORD` | SSH 密码 | - |
| `NAMESPACE` | Kubernetes 命名空间 | `default` |
| `INGRESS_URL` | Ingress URL | - |
| `OUTPUT_DIR` | 输出目录 | `results/e2e_validation` |

### 挂载目录

- `./results` → `/app/results`: 结果输出目录
- `./istio_config_parser/istio_monitor/istio_control_config` → 控制平面配置（只读）
- `./istio_config_parser/istio_monitor/istio_sidecar_config` → 数据平面配置（只读）
- `~/.kube/config` → `/root/.kube/config`: Kubernetes 配置（只读）

### 端口映射

- `8080`: Web 服务端口
- `5000`: Flask 开发服务器端口（可选）

## 📝 使用示例

### 示例1：运行端到端验证

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python e2e_validator.py \
    --vm-host 192.0.2.10 \
    --vm-user root \
    --vm-password <SSH_PASSWORD> \
    --namespace default \
    --ingress-url http://192.0.2.10:30476/productpage
```

### 示例2：运行静态分析

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python -m istio_config_parser.main_parser \
    --namespace default
```

### 示例3：运行一致性检查

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python -m consistency_checker.main \
    --mode full \
    --namespace default
```

### 示例4：启动 Web 界面

```bash
docker run -it --rm \
  -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python -m consistency_checker.main \
    --mode web \
    --port 8080
```

然后访问 http://localhost:8080

## 🔧 常见问题

### Q1: 容器内无法访问 Kubernetes 集群

**解决方案：**

```bash
# 方式1：挂载 kubeconfig
docker run -it --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  meshscope:latest

# 方式2：使用 host 网络（仅 Linux）
docker run -it --rm --network host meshscope:latest
```

### Q2: SSH 连接失败

**解决方案：**

1. 确保 SSH 服务在目标主机上运行
2. 检查防火墙设置
3. 验证 SSH 凭据是否正确
4. 如果需要 SSH 密钥，挂载密钥目录：

```bash
docker run -it --rm \
  -v ~/.ssh:/root/.ssh:ro \
  meshscope:latest
```

### Q3: 权限问题

**解决方案：**

```bash
# 使用 root 用户运行（默认）
docker run -it --rm --user root meshscope:latest

# 或者指定用户 ID
docker run -it --rm --user $(id -u):$(id -g) meshscope:latest
```

### Q4: 结果文件权限问题

**解决方案：**

```bash
# 在主机上创建结果目录并设置权限
mkdir -p results
chmod 777 results

# 或者在容器内使用 root 用户
docker run -it --rm --user root meshscope:latest
```

### Q5: 内存不足

**解决方案：**

```bash
# 限制内存使用
docker run -it --rm --memory="2g" meshscope:latest

# 或者使用 docker-compose，在配置中添加：
# deploy:
#   resources:
#     limits:
#       memory: 2G
```

### Q6: 构建镜像时依赖安装失败

**解决方案：**

1. 检查网络连接
2. 使用国内镜像源（修改 Dockerfile）：

```dockerfile
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

3. 分步安装依赖，便于调试

## 📚 更多信息

- [主项目 README](README.md)
- [架构文档](ARCHITECTURE.md)
- [端到端验证文档](E2E_VALIDATOR_README.md)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

