#!/bin/bash
# MeshScope Docker 快速启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认配置
VM_HOST="${VM_HOST:-192.168.92.131}"
VM_USER="${VM_USER:-root}"
VM_PASSWORD="${VM_PASSWORD:-}"
NAMESPACE="${NAMESPACE:-default}"
INGRESS_URL="${INGRESS_URL:-}"
OUTPUT_DIR="${OUTPUT_DIR:-results/e2e_validation}"

# 函数：打印信息
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# 函数：检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker 未安装，请先安装 Docker"
    fi
    info "Docker 已安装: $(docker --version)"
}

# 函数：构建镜像
build_image() {
    info "开始构建 Docker 镜像..."
    docker build -t meshscope:latest .
    info "镜像构建完成"
}

# 函数：运行容器
run_container() {
    info "启动 MeshScope 容器..."
    
    # 创建结果目录
    mkdir -p results
    
    # 构建命令
    CMD="docker run -it --rm"
    
    # 挂载卷
    CMD="$CMD -v $(pwd)/results:/app/results"
    CMD="$CMD -v $(pwd)/istio_config_parser/istio_monitor/istio_control_config:/app/istio_config_parser/istio_monitor/istio_control_config:ro"
    CMD="$CMD -v $(pwd)/istio_config_parser/istio_monitor/istio_sidecar_config:/app/istio_config_parser/istio_monitor/istio_sidecar_config:ro"
    
    # 挂载 kubeconfig（如果存在）
    if [ -f ~/.kube/config ]; then
        CMD="$CMD -v ~/.kube/config:/root/.kube/config:ro"
        info "已挂载 Kubernetes 配置"
    fi
    
    # 镜像名称
    CMD="$CMD meshscope:latest"
    
    # 执行命令
    CMD="$CMD python e2e_validator.py"
    CMD="$CMD --vm-host $VM_HOST"
    CMD="$CMD --vm-user $VM_USER"
    
    if [ -n "$VM_PASSWORD" ]; then
        CMD="$CMD --vm-password $VM_PASSWORD"
    fi
    
    CMD="$CMD --namespace $NAMESPACE"
    
    if [ -n "$INGRESS_URL" ]; then
        CMD="$CMD --ingress-url $INGRESS_URL"
    fi
    
    CMD="$CMD --output-dir $OUTPUT_DIR"
    
    # 执行
    eval $CMD
}

# 函数：显示帮助信息
show_help() {
    cat << EOF
MeshScope Docker 快速启动脚本

用法:
    $0 [选项]

选项:
    -h, --help              显示帮助信息
    -b, --build             构建 Docker 镜像
    -r, --run               运行容器
    -w, --web               启动 Web 服务
    -c, --clean             清理 Docker 资源

环境变量:
    VM_HOST                 虚拟机主机地址 (默认: 192.168.92.131)
    VM_USER                 SSH 用户名 (默认: root)
    VM_PASSWORD             SSH 密码
    NAMESPACE               Kubernetes 命名空间 (默认: default)
    INGRESS_URL             Ingress URL
    OUTPUT_DIR              输出目录 (默认: results/e2e_validation)

示例:
    # 构建镜像
    $0 --build

    # 运行端到端验证
    VM_HOST=192.168.92.131 VM_PASSWORD=12345678 $0 --run

    # 启动 Web 服务
    $0 --web

    # 使用自定义配置
    VM_HOST=10.0.0.1 NAMESPACE=production $0 --run
EOF
}

# 函数：启动 Web 服务
run_web() {
    info "启动 Web 服务..."
    docker run -it --rm \
        -p 8080:8080 \
        -v $(pwd)/results:/app/results \
        meshscope:latest \
        python -m consistency_checker.main --mode web --port 8080
}

# 函数：清理 Docker 资源
clean_docker() {
    info "清理 Docker 资源..."
    docker system prune -f
    info "清理完成"
}

# 主函数
main() {
    case "${1:-}" in
        -h|--help)
            show_help
            ;;
        -b|--build)
            check_docker
            build_image
            ;;
        -r|--run)
            check_docker
            run_container
            ;;
        -w|--web)
            check_docker
            run_web
            ;;
        -c|--clean)
            check_docker
            clean_docker
            ;;
        *)
            show_help
            ;;
    esac
}

# 执行主函数
main "$@"

