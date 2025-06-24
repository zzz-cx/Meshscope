#!/bin/bash
# 熔断模拟测试脚本
# 用法: ./circuit_breaker.sh <url> <total_requests> <concurrency>
# 示例: ./circuit_breaker.sh http://reviews:9080/ 200 50

URL=${1:-"http://reviews:9080/"}
TOTAL=${2:-200}
CONCURRENCY=${3:-50}
RESULT_FILE="../results/circuit_breaker_$(date +%Y%m%d%H%M%S).log"

ab -n $TOTAL -c $CONCURRENCY "$URL" > "$RESULT_FILE"
echo "响应码统计："
grep 'Failed requests' "$RESULT_FILE"
grep 'Non-2xx responses' "$RESULT_FILE" 