# 检查 Docker 服务状态

Write-Host "检查 Docker 服务状态..." -ForegroundColor Cyan

# 检查 Docker 是否安装
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[错误] Docker 未安装" -ForegroundColor Red
    Write-Host "请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Docker 已安装" -ForegroundColor Green
docker --version

# 检查 Docker 服务是否运行
$result = docker info 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Docker 服务正在运行" -ForegroundColor Green
    Write-Host ""
    Write-Host "Docker 信息:" -ForegroundColor Cyan
    docker version
    Write-Host ""
    Write-Host "可以开始构建镜像了！" -ForegroundColor Green
    Write-Host "运行: docker build -t meshscope:latest ." -ForegroundColor Yellow
} else {
    Write-Host "[错误] Docker 服务未运行" -ForegroundColor Red
    Write-Host ""
    Write-Host "请执行以下步骤:" -ForegroundColor Yellow
    Write-Host "1. 启动 Docker Desktop" -ForegroundColor White
    Write-Host "2. 等待 Docker Desktop 完全启动（系统托盘图标不再闪烁）" -ForegroundColor White
    Write-Host "3. 然后重新运行此脚本" -ForegroundColor White
    exit 1
}
