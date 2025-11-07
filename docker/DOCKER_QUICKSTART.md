# Docker 快速开始指南

## 🚀 快速启动（3步）

### 1. 构建镜像

```bash
# Linux/Mac
docker build -t meshscope:latest .

# 或使用脚本
./docker-run.sh --build

# Windows PowerShell
.\docker-run.ps1 -Build
```

### 2. 运行容器

```bash
# Linux/Mac
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python e2e_validator.py \
    --vm-host 192.168.92.131 \
    --vm-user root \
    --vm-password 12345678 \
    --namespace default

# 或使用脚本
VM_HOST=192.168.92.131 VM_PASSWORD=12345678 ./docker-run.sh --run

# Windows PowerShell
.\docker-run.ps1 -Run -VmHost "192.168.92.131" -VmPassword "12345678"
```

### 3. 查看结果

```bash
# 结果保存在 ./results 目录
ls -la results/e2e_validation/
```

## 📦 使用 Docker Compose

```bash
# 1. 创建 .env 文件（可选）
cat > .env << EOF
VM_HOST=192.168.92.131
VM_USER=root
VM_PASSWORD=12345678
NAMESPACE=default
INGRESS_URL=http://192.168.92.131:30476/productpage
EOF

# 2. 启动服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 停止服务
docker-compose down
```

## 🌐 启动 Web 服务

```bash
# 使用 Docker Compose
docker-compose --profile web up -d meshscope-web

# 或直接运行
docker run -it --rm -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest \
  python -m consistency_checker.main --mode web --port 8080

# 访问 http://localhost:8080
```

## 📝 常用命令

```bash
# 查看镜像
docker images | grep meshscope

# 查看运行中的容器
docker ps

# 进入容器
docker run -it --rm meshscope:latest /bin/bash

# 查看容器日志
docker logs <container_id>

# 清理未使用的镜像
docker image prune -a
```

## ⚙️ 配置说明

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `VM_HOST` | 虚拟机IP | `192.168.92.131` |
| `VM_USER` | SSH用户 | `root` |
| `VM_PASSWORD` | SSH密码 | `12345678` |
| `NAMESPACE` | K8s命名空间 | `default` |
| `INGRESS_URL` | Ingress地址 | `http://192.168.92.131:30476/productpage` |

### 挂载目录

- `./results` → 结果输出
- `./istio_config_parser/istio_monitor/istio_control_config` → 控制平面配置
- `./istio_config_parser/istio_monitor/istio_sidecar_config` → 数据平面配置
- `~/.kube/config` → Kubernetes配置（可选）

## 🔧 故障排除

### 问题1: 无法访问 Kubernetes

```bash
# 挂载 kubeconfig
docker run -it --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  meshscope:latest
```

### 问题2: SSH 连接失败

```bash
# 检查网络连接
docker run -it --rm meshscope:latest ping <vm_host>

# 挂载 SSH 密钥（如果需要）
docker run -it --rm \
  -v ~/.ssh:/root/.ssh:ro \
  meshscope:latest
```

### 问题3: 权限问题

```bash
# 使用 root 用户
docker run -it --rm --user root meshscope:latest

# 或修复结果目录权限
sudo chown -R $USER:$USER results/
```

## 📚 更多信息

详细文档请参考 [DOCKER_README.md](DOCKER_README.md)

