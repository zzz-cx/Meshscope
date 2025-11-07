# MeshScope Docker 执行脚本 - 统一入口 (PowerShell)

param(
    [Parameter(Position=0)]
    [string]$Command = "help",
    
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ImageName = $env:IMAGE_NAME
if (-not $ImageName) {
    $ImageName = "meshscope:latest"
}

$VolumeMounts = @(
    "-v", "$(Get-Location)/results:/app/results"
)

function Show-Help {
    Write-Host @"
MeshScope Docker 执行脚本

用法: .\docker-exec.ps1 <command> [args...]

可用命令:
  e2e                运行端到端验证
  static             运行静态配置分析
  consistency        运行一致性检查
  dynamic            运行动态测试
  web                启动 Web 服务
  parser             运行配置解析器
  shell              进入容器交互式 shell
  exec <cmd>         执行任意命令
  help               显示此帮助信息

示例:
  # 端到端验证
  .\docker-exec.ps1 e2e --vm-host 192.168.92.131 --vm-user root --vm-password 12345678

  # 静态分析
  .\docker-exec.ps1 static --namespace default

  # 一致性检查
  .\docker-exec.ps1 consistency --mode full --namespace default

  # Web 服务
  .\docker-exec.ps1 web --port 8080

  # 进入容器
  .\docker-exec.ps1 shell

  # 执行任意 Python 脚本
  .\docker-exec.ps1 exec python e2e_validator.py --help
"@
}

function Test-Image {
    $images = docker images --format "{{.Repository}}:{{.Tag}}" | Select-String "^$($ImageName.Split(':')[0])"
    if (-not $images) {
        Write-Host "错误: 镜像 $ImageName 不存在" -ForegroundColor Red
        Write-Host "请先构建镜像: docker build -t $ImageName ." -ForegroundColor Yellow
        exit 1
    }
}

# 主逻辑
switch ($Command.ToLower()) {
    { $_ -in @("e2e", "static", "consistency", "dynamic", "web", "parser") } {
        Test-Image
        $dockerArgs = @("run", "-it", "--rm") + $VolumeMounts + @($ImageName, $Command) + $Args
        docker $dockerArgs
    }
    "shell" {
        Test-Image
        docker run -it --rm $VolumeMounts $ImageName /bin/bash
    }
    "exec" {
        Test-Image
        $dockerArgs = @("run", "-it", "--rm") + $VolumeMounts + @($ImageName) + $Args
        docker $dockerArgs
    }
    { $_ -in @("help", "--help", "-h") } {
        Show-Help
    }
    default {
        Write-Host "未知命令: $Command" -ForegroundColor Red
        Write-Host "使用 'help' 查看可用命令" -ForegroundColor Yellow
        exit 1
    }
}

