# Docker 构建说明

## 📍 构建位置

由于 Dockerfile 位于 `docker/` 目录，构建时需要指定正确的上下文和 Dockerfile 路径。

## 🔨 构建方式

### 方式1：从项目根目录构建（推荐）

```bash
# 在项目根目录执行
docker build -t meshscope:latest -f docker/Dockerfile .
```

### 方式2：使用 Docker Compose

```bash
# 在 docker 目录执行
cd docker
docker-compose build

# 或从项目根目录执行
docker-compose -f docker/docker-compose.yml build
```

### 方式3：使用脚本

```bash
# Linux/Mac
cd docker
./docker-run.sh --build

# Windows PowerShell
cd docker
.\docker-run.ps1 -Build
```

## ⚠️ 注意事项

1. **构建上下文**: Dockerfile 中的 `COPY` 命令是相对于构建上下文的
   - 使用 `-f docker/Dockerfile .` 时，上下文是项目根目录（`.`）
   - 因此 Dockerfile 中使用 `COPY requirements.txt` 即可

2. **文件路径**: 
   - `entrypoint.sh` 位于 `docker/` 目录，所以使用 `COPY docker/entrypoint.sh`
   - 其他项目文件从根目录复制

3. **docker-compose.yml**:
   - `context: ..` 表示构建上下文是项目根目录
   - `dockerfile: docker/Dockerfile` 指定 Dockerfile 路径
   - 卷挂载路径相对于 docker-compose.yml 所在目录

## 🐛 常见问题

### 问题：找不到 requirements.txt

**原因**: 构建上下文不正确

**解决**: 确保从项目根目录构建，或使用正确的上下文路径

```bash
# 正确
docker build -t meshscope:latest -f docker/Dockerfile .

# 错误（在 docker 目录执行）
cd docker
docker build -t meshscope:latest -f Dockerfile .
```

### 问题：找不到 entrypoint.sh

**原因**: COPY 路径不正确

**解决**: 确保使用 `COPY docker/entrypoint.sh`（相对于构建上下文）

