# Docker 使用指南 - 完整功能支持

## 🎯 概述

本 Docker 镜像包含了整个 `istio_check` 项目的所有功能，可以执行项目中的任何可执行文件。

## 📦 构建镜像

```bash
docker build -t meshscope:latest .
```

## 🚀 使用方式

### 方式1：使用统一入口脚本（推荐）

#### Linux/Mac

```bash
# 使用 docker-exec.sh
chmod +x docker-exec.sh
./docker-exec.sh e2e --vm-host 192.168.92.131
```

#### Windows PowerShell

```powershell
# 使用 docker-exec.ps1
.\docker-exec.ps1 e2e -VmHost "192.168.92.131" -VmPassword "12345678"
```

### 方式2：直接使用 Docker 命令

```bash
# 端到端验证
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.168.92.131 \
  --vm-user root \
  --vm-password 12345678

# 静态分析
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest static \
  --namespace default

# 一致性检查
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest consistency \
  --mode full \
  --namespace default

# Web 服务
docker run -it --rm \
  -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest web \
  --port 8080
```

## 📋 支持的命令

### 1. 端到端验证 (`e2e`)

运行完整的端到端验证流程。

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.168.92.131 \
  --vm-user root \
  --vm-password 12345678 \
  --namespace default \
  --ingress-url http://192.168.92.131:30476/productpage
```

**参数：**
- `--vm-host`: 虚拟机主机地址
- `--vm-user`: SSH 用户名
- `--vm-password`: SSH 密码
- `--namespace`: Kubernetes 命名空间
- `--ingress-url`: Ingress URL
- `--output-dir`: 输出目录

### 2. 静态配置分析 (`static`)

运行静态配置分析。

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest static \
  --namespace default
```

**参数：**
- `--namespace`: Kubernetes 命名空间
- 其他参数参考 `istio_config_parser/main_parser.py --help`

### 3. 一致性检查 (`consistency`)

运行一致性验证。

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest consistency \
  --mode full \
  --namespace default
```

**参数：**
- `--mode`: 运行模式 (full/static/consistency/web)
- `--namespace`: Kubernetes 命名空间
- `--port`: Web 服务端口（web 模式）
- 其他参数参考 `consistency_checker/main.py --help`

### 4. 动态测试 (`dynamic`)

运行动态测试。

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest dynamic \
  -i output_matrix.json \
  --ssh-host 192.168.92.131
```

### 5. Web 服务 (`web`)

启动 Web 可视化界面。

```bash
docker run -it --rm \
  -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest web \
  --port 8080
```

然后访问 http://localhost:8080

### 6. 进入容器 (`shell`)

进入容器的交互式 shell，可以执行任何命令。

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest shell
```

在容器内可以：
```bash
# 执行任何 Python 脚本
python e2e_validator.py --help
python -m istio_config_parser.main_parser --help
python -m consistency_checker.main --help

# 执行其他工具
kubectl version
ssh -V
```

### 7. 执行任意命令 (`exec`)

执行容器内的任意命令。

```bash
# 执行 Python 脚本
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python e2e_validator.py --help

# 执行其他命令
docker run -it --rm \
  meshscope:latest exec \
  kubectl version
```

## 🔧 高级用法

### 挂载额外目录

```bash
# 挂载配置文件
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/config:/app/config:ro \
  meshscope:latest e2e

# 挂载 kubeconfig
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  -v ~/.kube/config:/root/.kube/config:ro \
  meshscope:latest static
```

### 使用环境变量

```bash
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  -e VM_HOST=192.168.92.131 \
  -e VM_USER=root \
  -e VM_PASSWORD=12345678 \
  meshscope:latest e2e
```

### 后台运行

```bash
# 后台运行 Web 服务
docker run -d \
  --name meshscope-web \
  -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest web \
  --port 8080

# 查看日志
docker logs -f meshscope-web

# 停止服务
docker stop meshscope-web
docker rm meshscope-web
```

## 📁 项目中的所有可执行文件

容器内包含以下所有可执行文件：

### 主要入口点

1. **`e2e_validator.py`** - 端到端验证
   ```bash
   docker run -it --rm meshscope:latest exec python e2e_validator.py --help
   ```

2. **`istio_config_parser/main_parser.py`** - 静态配置解析
   ```bash
   docker run -it --rm meshscope:latest exec python -m istio_config_parser.main_parser --help
   ```

3. **`consistency_checker/main.py`** - 一致性检查
   ```bash
   docker run -it --rm meshscope:latest exec python -m consistency_checker.main --help
   ```

### 动态测试模块

4. **`istio_Dynamic_Test/generator/test_case_generator.py`** - 测试用例生成
   ```bash
   docker run -it --rm meshscope:latest exec python -m istio_Dynamic_Test.generator.test_case_generator --help
   ```

5. **`istio_Dynamic_Test/checker/traffic_driver.py`** - 流量驱动
   ```bash
   docker run -it --rm meshscope:latest exec python -m istio_Dynamic_Test.checker.traffic_driver --help
   ```

6. **`istio_Dynamic_Test/verifier/main_verifier.py`** - 验证器
   ```bash
   docker run -it --rm meshscope:latest exec python -m istio_Dynamic_Test.verifier.main_verifier --help
   ```

### 评估模块

7. **`evaluation/performance/config_change_responsiveness.py`** - 性能评估
   ```bash
   docker run -it --rm meshscope:latest exec python -m evaluation.performance.config_change_responsiveness --help
   ```

8. **`evaluation/scalability/scalability_evaluator.py`** - 可扩展性评估
   ```bash
   docker run -it --rm meshscope:latest exec python -m evaluation.scalability.scalability_evaluator --help
   ```

### 监控模块

9. **`istio_config_parser/istio_monitor/istio_sidecar_monitor.py`** - Sidecar 监控
   ```bash
   docker run -it --rm meshscope:latest exec python -m istio_config_parser.istio_monitor.istio_sidecar_monitor --help
   ```

## 🎯 完整工作流示例

### 示例1：完整的验证流程

```bash
# 1. 静态分析
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest static \
  --namespace default

# 2. 生成测试用例
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python -m istio_Dynamic_Test.generator.test_case_generator \
  -i istio_Dynamic_Test/generator/istio_config.json \
  -o results/output_matrix.json

# 3. 执行动态测试
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest dynamic \
  -i results/output_matrix.json \
  --ssh-host 192.168.92.131

# 4. 一致性检查
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest consistency \
  --mode full \
  --namespace default
```

### 示例2：使用 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  meshscope:
    image: meshscope:latest
    volumes:
      - ./results:/app/results
    command: e2e --vm-host 192.168.92.131
```

```bash
docker-compose up
```

## 🔍 调试和故障排除

### 查看容器内容

```bash
# 列出所有文件
docker run --rm meshscope:latest exec ls -la /app

# 查看 Python 路径
docker run --rm meshscope:latest exec python -c "import sys; print('\n'.join(sys.path))"

# 检查依赖
docker run --rm meshscope:latest exec pip list
```

### 执行调试

```bash
# 进入容器调试
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest shell

# 在容器内
python -c "import istio_config_parser; print('OK')"
python -c "import consistency_checker; print('OK')"
python -c "import istio_Dynamic_Test; print('OK')"
```

## 📚 更多信息

- [DOCKER_README.md](DOCKER_README.md) - 详细 Docker 文档
- [DOCKER_QUICKSTART.md](DOCKER_QUICKSTART.md) - 快速开始
- [README.md](README.md) - 项目主文档

