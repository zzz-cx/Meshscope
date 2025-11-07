#!/bin/bash
# MeshScope Docker 执行脚本 - 统一入口

set -e

IMAGE_NAME="${IMAGE_NAME:-meshscope:latest}"
VOLUME_MOUNTS="-v $(pwd)/results:/app/results"

# 显示帮助
show_help() {
    cat << EOF
MeshScope Docker 执行脚本

用法: $0 <command> [args...]

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
  $0 e2e --vm-host 192.168.92.131 --vm-user root --vm-password 12345678

  # 静态分析
  $0 static --namespace default

  # 一致性检查
  $0 consistency --mode full --namespace default

  # Web 服务
  $0 web --port 8080

  # 进入容器
  $0 shell

  # 执行任意 Python 脚本
  $0 exec python e2e_validator.py --help
EOF
}

# 检查镜像是否存在
check_image() {
    if ! docker images | grep -q "^${IMAGE_NAME%:*}"; then
        echo "错误: 镜像 $IMAGE_NAME 不存在"
        echo "请先构建镜像: docker build -t $IMAGE_NAME ."
        exit 1
    fi
}

# 主逻辑
case "${1:-help}" in
    e2e|static|consistency|dynamic|web|parser)
        check_image
        shift
        docker run -it --rm $VOLUME_MOUNTS $IMAGE_NAME "$@"
        ;;
    shell)
        check_image
        docker run -it --rm $VOLUME_MOUNTS $IMAGE_NAME /bin/bash
        ;;
    exec)
        check_image
        shift
        docker run -it --rm $VOLUME_MOUNTS $IMAGE_NAME "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "未知命令: $1"
        echo "使用 'help' 查看可用命令"
        exit 1
        ;;
esac

