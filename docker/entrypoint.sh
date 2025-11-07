#!/bin/bash
# MeshScope 统一入口脚本

set -e

# 显示帮助信息
show_help() {
    cat << EOF
MeshScope - Istio 配置验证系统

用法: docker run [OPTIONS] meshscope:latest <command> [ARGS...]

可用命令:
  e2e                运行端到端验证
  static             运行静态配置分析
  consistency        运行一致性检查
  dynamic            运行动态测试
  web                启动 Web 服务
  parser             运行配置解析器
  shell              进入交互式 shell
  help               显示此帮助信息

示例:
  # 端到端验证
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest e2e --vm-host 192.168.92.131

  # 静态分析
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest static --namespace default

  # 一致性检查
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest consistency --mode full --namespace default

  # Web 服务
  docker run -it --rm -p 8080:8080 -v \$(pwd)/results:/app/results meshscope:latest web --port 8080

  # 进入 shell
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest shell
EOF
}

# 根据命令执行相应操作
case "${1:-help}" in
    e2e)
        shift
        exec python e2e_validator.py "$@"
        ;;
    static|parser)
        shift
        exec python -m istio_config_parser.main_parser "$@"
        ;;
    consistency)
        shift
        exec python -m consistency_checker.main "$@"
        ;;
    dynamic)
        shift
        exec python -m istio_Dynamic_Test.checker.traffic_driver "$@"
        ;;
    web)
        shift
        exec python -m consistency_checker.main --mode web "$@"
        ;;
    shell)
        exec /bin/bash
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        # 如果没有匹配的命令，尝试直接执行 Python 脚本
        if [ -f "$1" ] && [[ "$1" == *.py ]]; then
            exec python "$@"
        elif [ -f "/app/$1" ] && [[ "$1" == *.py ]]; then
            exec python "/app/$1" "${@:2}"
        else
            echo "未知命令: $1"
            echo "使用 'help' 查看可用命令"
            echo ""
            echo "或者直接执行 Python 脚本:"
            echo "  docker run -it --rm meshscope:latest exec python <script.py> [args...]"
            exit 1
        fi
        ;;
esac

