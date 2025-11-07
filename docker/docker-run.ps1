# MeshScope Docker 快速启动脚本 (PowerShell)

param(
    [switch]$Build,
    [switch]$Run,
    [switch]$Web,
    [switch]$Clean,
    [switch]$Help,
    [string]$VmHost = $env:VM_HOST ?? "192.168.92.131",
    [string]$VmUser = $env:VM_USER ?? "root",
    [string]$VmPassword = $env:VM_PASSWORD ?? "",
    [string]$Namespace = $env:NAMESPACE ?? "default",
    [string]$IngressUrl = $env:INGRESS_URL ?? "",
    [string]$OutputDir = $env:OUTPUT_DIR ?? "results/e2e_validation"
)

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "Docker 未安装，请先安装 Docker"
    }
    $version = docker --version
    Write-Info "Docker 已安装: $version"
}

function Build-Image {
    Write-Info "开始构建 Docker 镜像..."
    docker build -t meshscope:latest .
    if ($LASTEXITCODE -ne 0) {
        Write-Error "镜像构建失败"
    }
    Write-Info "镜像构建完成"
}

function Start-Container {
    Write-Info "启动 MeshScope 容器..."
    
    # 创建结果目录
    if (-not (Test-Path "results")) {
        New-Item -ItemType Directory -Path "results" | Out-Null
    }
    
    # 构建命令
    $volumes = @(
        "-v", "$(Get-Location)/results:/app/results",
        "-v", "$(Get-Location)/istio_config_parser/istio_monitor/istio_control_config:/app/istio_config_parser/istio_monitor/istio_control_config:ro",
        "-v", "$(Get-Location)/istio_config_parser/istio_monitor/istio_sidecar_config:/app/istio_config_parser/istio_monitor/istio_sidecar_config:ro"
    )
    
    # 挂载 kubeconfig（如果存在）
    $kubeConfig = "$env:USERPROFILE\.kube\config"
    if (Test-Path $kubeConfig) {
        $volumes += "-v", "$kubeConfig:/root/.kube/config:ro"
        Write-Info "已挂载 Kubernetes 配置"
    }
    
    # 构建参数
    $args = @(
        "run", "-it", "--rm"
    ) + $volumes + @(
        "meshscope:latest",
        "python", "e2e_validator.py",
        "--vm-host", $VmHost,
        "--vm-user", $VmUser,
        "--namespace", $Namespace,
        "--output-dir", $OutputDir
    )
    
    if ($VmPassword) {
        $args += "--vm-password", $VmPassword
    }
    
    if ($IngressUrl) {
        $args += "--ingress-url", $IngressUrl
    }
    
    # 执行
    docker $args
}

function Start-Web {
    Write-Info "启动 Web 服务..."
    docker run -it --rm `
        -p 8080:8080 `
        -v "$(Get-Location)/results:/app/results" `
        meshscope:latest `
        python -m consistency_checker.main --mode web --port 8080
}

function Clear-Docker {
    Write-Info "清理 Docker 资源..."
    docker system prune -f
    Write-Info "清理完成"
}

function Show-Help {
    Write-Host @"
MeshScope Docker 快速启动脚本 (PowerShell)

用法:
    .\docker-run.ps1 [选项]

选项:
    -Build              构建 Docker 镜像
    -Run                运行容器
    -Web                启动 Web 服务
    -Clean              清理 Docker 资源
    -Help               显示帮助信息

参数:
    -VmHost             虚拟机主机地址 (默认: 192.168.92.131)
    -VmUser             SSH 用户名 (默认: root)
    -VmPassword         SSH 密码
    -Namespace          Kubernetes 命名空间 (默认: default)
    -IngressUrl         Ingress URL
    -OutputDir          输出目录 (默认: results/e2e_validation)

环境变量:
    也可以通过环境变量设置:
    `$env:VM_HOST = "192.168.92.131"
    `$env:VM_PASSWORD = "12345678"
    `$env:NAMESPACE = "default"

示例:
    # 构建镜像
    .\docker-run.ps1 -Build

    # 运行端到端验证
    .\docker-run.ps1 -Run -VmHost "192.168.92.131" -VmPassword "12345678"

    # 启动 Web 服务
    .\docker-run.ps1 -Web

    # 使用环境变量
    `$env:VM_HOST = "192.168.92.131"
    `$env:VM_PASSWORD = "12345678"
    .\docker-run.ps1 -Run
"@
}

# 主逻辑
if ($Help) {
    Show-Help
    exit 0
}

if ($Build) {
    Test-Docker
    Build-Image
}
elseif ($Run) {
    Test-Docker
    Start-Container
}
elseif ($Web) {
    Test-Docker
    Start-Web
}
elseif ($Clean) {
    Test-Docker
    Clear-Docker
}
else {
    Show-Help
}

