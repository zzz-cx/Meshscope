#!/bin/bash
# MeshScope 统一入口脚本

set -e

# 显示帮助信息
show_help() {
    cat << EOF
ConfigPilot - Istio 配置一致性检验

用法: docker run [OPTIONS] configpilot:latest <command> [ARGS...]

可用命令（与 python -m configpilot 相同）:
  run | e2e          完整流水线
  collect            采集集群配置
  static             静态分析
  dynamic            动态验证
  check              一致性判定
  web                启动 Web 界面
  shell              进入交互式 shell
  help               显示帮助

示例:
  # 端到端验证
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest e2e --vm-host 192.0.2.10

  # 静态分析
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest static --namespace default

  # 一致性检查
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest check --namespace default

  # Web 服务
  docker run -it --rm -p 8080:8080 -v \$(pwd)/results:/app/results meshscope:latest web --port 8080

  # 进入 shell
  docker run -it --rm -v \$(pwd)/results:/app/results meshscope:latest shell
EOF
}

# 根据命令执行相应操作
case "${1:-help}" in
    run|e2e|collect|static|dynamic|check|web)
        exec python -m configpilot "$@"
        ;;
    parser)
        shift
        exec python -m configpilot static "$@"
        ;;
    consistency)
        shift
        exec python -m configpilot check "$@"
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

