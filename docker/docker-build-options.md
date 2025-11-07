# Docker 构建选项

## 网络问题解决方案

如果遇到网络连接问题，有以下几种解决方案：

### 方案1：配置 Docker 镜像加速器（推荐）

1. 打开 Docker Desktop
2. 进入 Settings → Docker Engine
3. 添加以下配置：

```json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ]
}
```

4. 点击 "Apply & Restart"
5. 重新构建镜像

### 方案2：使用代理

如果有代理，可以在 Docker Desktop 中配置：
- Settings → Resources → Proxies
- 配置 HTTP/HTTPS 代理

### 方案3：使用国内镜像源构建

如果无法访问 Docker Hub，可以使用国内镜像：

```powershell
# 使用阿里云镜像
docker build -t meshscope:latest -f Dockerfile.cn .

# 或者手动指定基础镜像
docker build --build-arg BASE_IMAGE=registry.cn-hangzhou.aliyuncs.com/acs/python:3.9-slim -t meshscope:latest .
```

### 方案4：离线构建

如果网络完全不可用：

1. 在有网络的机器上拉取基础镜像：
   ```powershell
   docker pull python:3.9-slim
   docker save python:3.9-slim -o python-3.9-slim.tar
   ```

2. 在目标机器上加载：
   ```powershell
   docker load -i python-3.9-slim.tar
   ```

3. 然后构建项目镜像

## 当前建议

由于检测到网络连接问题，建议：

1. **首先尝试配置镜像加速器**（方案1）
2. 如果还是不行，检查网络连接和防火墙设置
3. 或者等待网络恢复后重试

## 验证网络连接

```powershell
# 测试 Docker Hub 连接
docker pull hello-world

# 如果成功，说明网络正常
# 如果失败，需要配置镜像加速器或代理
```

