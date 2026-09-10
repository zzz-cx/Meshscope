# Docker 部署文件

本目录包含所有 Docker 相关的部署文件。

## 📁 文件说明

### 核心文件

- **`Dockerfile`** - Docker 镜像构建文件
- **`docker-compose.yml`** - Docker Compose 配置文件
- **`entrypoint.sh`** - 容器入口脚本

### 执行脚本

- **`docker-run.sh`** / **`docker-run.ps1`** - 快速启动脚本
- **`docker-exec.sh`** / **`docker-exec.ps1`** - 统一执行脚本

### 文档

- **`DOCKER_README.md`** - Docker 部署详细文档
- **`DOCKER_QUICKSTART.md`** - 快速开始指南
- **`DOCKER_USAGE.md`** - 使用说明
- **`DOCKER_COMPLETE_GUIDE.md`** - 完整功能指南
- **`docker-build-options.md`** - 构建选项和故障排除

## 🚀 快速开始

### 构建镜像

```bash
# 从项目根目录构建
cd ..
docker build -t meshscope:latest -f docker/Dockerfile .

# 或使用 docker-compose
cd docker
docker-compose build
```

### 运行容器

```bash
# 从 docker 目录运行
cd docker
docker-compose up

# 或从项目根目录运行
docker-compose -f docker/docker-compose.yml up
```

### 使用脚本

```bash
# Linux/Mac
cd docker
./docker-run.sh --build
./docker-run.sh --run

# Windows PowerShell
cd docker
.\docker-run.ps1 -Build
.\docker-run.ps1 -Run
```

## 📚 更多信息

详细使用说明请参考各个文档文件。

