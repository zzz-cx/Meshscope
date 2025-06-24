#!/bin/bash
# 路由匹配测试脚本
# 用法: ./route_match.sh <path> <header_key> <header_value>
# 示例: ./route_match.sh /v1 "x-user" "admin"

PATH_TO_TEST=${1:-/v1}
HEADER_KEY=${2:-"x-user"}
HEADER_VALUE=${3:-"admin"}
RESULT_FILE="../results/route_match_$(date +%Y%m%d%H%M%S).log"

curl -s -H "$HEADER_KEY: $HEADER_VALUE" "http://productpage:9080$PATH_TO_TEST" | tee "$RESULT_FILE" 