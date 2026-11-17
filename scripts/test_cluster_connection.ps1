# Remote Kubernetes Cluster Connection Test
# Cluster Master: 192.0.2.10:6443

param(
    [string]$KubeConfigPath = "",
    [string]$ClusterHost = $env:K8S_HOST,
    [int]$ClusterPort = 6443
)

$ErrorActionPreference = "Continue"

Write-Host "`n=== Kubernetes Remote Cluster Connection Test ===" -ForegroundColor Cyan
Write-Host "Target: $ClusterHost`:$ClusterPort`n" -ForegroundColor Gray

# 1. Check kubectl
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] kubectl not found. Please install Kubernetes client tools." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] kubectl installed" -ForegroundColor Green

# 2. Check kubeconfig
$defaultKubeConfig = Join-Path $env:USERPROFILE ".kube\config"
$projectKubeConfig = Join-Path $PSScriptRoot "..\kubeconfig-remote"

if ($KubeConfigPath -and (Test-Path $KubeConfigPath)) {
    $env:KUBECONFIG = $KubeConfigPath
    Write-Host "[OK] Using config: $KubeConfigPath" -ForegroundColor Green
} elseif (Test-Path $defaultKubeConfig) {
    $env:KUBECONFIG = $defaultKubeConfig
    Write-Host "[OK] Using default: $defaultKubeConfig" -ForegroundColor Green
} elseif (Test-Path $projectKubeConfig) {
    $env:KUBECONFIG = (Resolve-Path $projectKubeConfig).Path
    Write-Host "[OK] Using project: $projectKubeConfig" -ForegroundColor Green
} else {
    Write-Host "`n[TIP] No kubeconfig found. Copy from Master node:" -ForegroundColor Yellow
    Write-Host "  scp root@${ClusterHost}:/etc/kubernetes/admin.conf `$env:USERPROFILE\.kube\config" -ForegroundColor White
    Write-Host "`nOr set KUBECONFIG env before running this script.`n" -ForegroundColor Yellow
    exit 1
}

# 3. Test connection
Write-Host "`n--- Cluster Connection ---" -ForegroundColor Cyan
$result = kubectl cluster-info 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host $result -ForegroundColor Green
    Write-Host "`n[SUCCESS] Cluster connected!" -ForegroundColor Green
} else {
    Write-Host $result -ForegroundColor Red
    Write-Host "`n[FAILED] Cannot connect to cluster" -ForegroundColor Red
}

# 4. Get nodes
Write-Host "`n--- Nodes ---" -ForegroundColor Cyan
kubectl get nodes 2>&1

# 5. Network reachability
Write-Host "`n--- Network ($ClusterHost`:$ClusterPort) ---" -ForegroundColor Cyan
$tcpTest = Test-NetConnection -ComputerName $ClusterHost -Port $ClusterPort -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
if ($tcpTest.TcpTestSucceeded) {
    Write-Host "[OK] Port $ClusterPort reachable" -ForegroundColor Green
} else {
    Write-Host "[WARN] Port $ClusterPort may be unreachable (firewall/network)" -ForegroundColor Yellow
}

Write-Host ""
