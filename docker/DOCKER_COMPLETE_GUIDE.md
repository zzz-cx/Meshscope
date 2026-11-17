# Docker 完整部署指南

## ✅ 功能支持

本 Docker 镜像**完全支持**执行 `istio_check` 项目中的所有可执行文件！

## 🎯 核心特性

1. ✅ **完整项目打包** - 所有代码文件都包含在镜像中
2. ✅ **统一入口** - 通过 `entrypoint.sh` 提供统一的命令接口
3. ✅ **灵活执行** - 可以执行任何 Python 脚本或命令
4. ✅ **环境隔离** - 所有依赖都已安装，无需本地环境
5. ✅ **数据持久化** - 通过卷挂载保存结果

## 📦 构建镜像

```bash
docker build -t meshscope:latest .
```

## 🚀 使用方式

### 方式1：使用统一命令（推荐）

```bash
# 端到端验证
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.0.2.10 \
  --vm-user root \
  --vm-password <SSH_PASSWORD>

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

### 方式2：使用便捷脚本

#### Linux/Mac

```bash
chmod +x docker-exec.sh
./docker-exec.sh e2e --vm-host 192.0.2.10
```

#### Windows PowerShell

```powershell
.\docker-exec.ps1 e2e -VmHost "192.0.2.10" -VmPassword "<SSH_PASSWORD>"
```

### 方式3：直接执行任意脚本

```bash
# 执行任何 Python 脚本
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python e2e_validator.py --help

docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python -m istio_config_parser.main_parser --help

docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python -m consistency_checker.main --help
```

### 方式4：进入容器交互式执行

```bash
# 进入容器
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest shell

# 在容器内可以执行任何命令
python e2e_validator.py --help
python -m istio_config_parser.main_parser --help
python -m consistency_checker.main --help
kubectl version
ssh -V
```

## 📋 支持的所有可执行文件

### 主要入口点

| 文件 | 命令 | 说明 |
|------|------|------|
| `e2e_validator.py` | `e2e` | 端到端验证 |
| `istio_config_parser/main_parser.py` | `static` 或 `parser` | 静态配置分析 |
| `consistency_checker/main.py` | `consistency` | 一致性检查 |
| `consistency_checker/main.py` | `web` | Web 服务 |

### 动态测试模块

| 文件 | 执行方式 |
|------|----------|
| `istio_Dynamic_Test/internal/testcase/generators/test_case_generator.py` | 直接运行或经 experiment4 调用 |
| `istio_Dynamic_Test/cmd` | `dynamic` 或 `python -m istio_Dynamic_Test.cmd` |
| `istio_Dynamic_Test/internal/validation/offline.py` | 离线验证（由 Pipeline / API 调用） |

### 评估模块

| 文件 | 执行方式 |
|------|----------|
| `evaluation/performance/config_change_responsiveness.py` | `python -m evaluation.performance.config_change_responsiveness` |
| `evaluation/scalability/scalability_evaluator.py` | `python -m evaluation.scalability.scalability_evaluator` |
| `evaluation/accuracy/scripts/accuracy_evaluator.py` | `python -m evaluation.accuracy.scripts.accuracy_evaluator` |

### 监控模块

| 文件 | 执行方式 |
|------|----------|
| `istio_config_parser/istio_monitor/istio_sidecar_monitor.py` | `python -m istio_config_parser.istio_monitor.istio_sidecar_monitor` |
| `istio_config_parser/istio_monitor/istio_api.py` | 作为模块导入使用 |

## 🎯 完整示例

### 示例1：端到端验证流程

```bash
# 使用统一命令
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest e2e \
  --vm-host 192.0.2.10 \
  --vm-user root \
  --vm-password <SSH_PASSWORD> \
  --namespace default \
  --ingress-url http://192.0.2.10:30476/productpage
```

### 示例2：分步执行

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
  --ssh-host 192.0.2.10

# 4. 一致性检查
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest consistency \
  --mode full \
  --namespace default
```

### 示例3：评估模块

```bash
# 性能评估
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python -m evaluation.performance.config_change_responsiveness \
  --namespace default

# 可扩展性评估
docker run -it --rm \
  -v $(pwd)/results:/app/results \
  meshscope:latest exec \
  python -m evaluation.scalability.scalability_evaluator \
  --namespace default
```

## 🔧 高级配置

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
  -e VM_HOST=192.0.2.10 \
  -e VM_USER=root \
  -e VM_PASSWORD=<SSH_PASSWORD> \
  -e NAMESPACE=default \
  meshscope:latest e2e
```

### 后台运行服务

```bash
# 启动 Web 服务
docker run -d \
  --name meshscope-web \
  -p 8080:8080 \
  -v $(pwd)/results:/app/results \
  meshscope:latest web \
  --port 8080

# 查看日志
docker logs -f meshscope-web

# 停止服务
docker stop meshscope-web && docker rm meshscope-web
```

## ✅ 验证功能

### 检查镜像内容

```bash
# 列出所有文件
docker run --rm meshscope:latest exec ls -la /app

# 检查 Python 模块
docker run --rm meshscope:latest exec python -c "import istio_config_parser; print('OK')"
docker run --rm meshscope:latest exec python -c "import consistency_checker; print('OK')"
docker run --rm meshscope:latest exec python -c "import istio_Dynamic_Test; print('OK')"

# 检查工具
docker run --rm meshscope:latest exec kubectl version --client
docker run --rm meshscope:latest exec ssh -V
```

## 📚 相关文档

- [DOCKER_USAGE.md](DOCKER_USAGE.md) - 详细使用说明
- [DOCKER_README.md](DOCKER_README.md) - Docker 部署文档
- [DOCKER_QUICKSTART.md](DOCKER_QUICKSTART.md) - 快速开始

## 🎉 总结

**是的，完全可以实现！** 

Docker 镜像包含了整个 `istio_check` 项目的所有代码和依赖，可以：

1. ✅ 执行所有 Python 脚本
2. ✅ 运行所有模块功能
3. ✅ 使用统一的命令接口
4. ✅ 进入容器执行任意命令
5. ✅ 挂载数据目录持久化结果

只需要构建一次镜像，就可以在任何支持 Docker 的环境中运行所有功能！

