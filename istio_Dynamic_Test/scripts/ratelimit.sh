#!/bin/bash
# 限流测试脚本
# 用法: ./ratelimit.sh <url> <total_requests> <concurrency>
# 示例: ./ratelimit.sh http://service:9080/api 100 20

URL=${1:-"http://service:9080/api"}
TOTAL=${2:-100}
CONCURRENCY=${3:-20}
RESULT_FILE="../results/ratelimit_$(date +%Y%m%d%H%M%S).log"

ab -n $TOTAL -c $CONCURRENCY "$URL" > "$RESULT_FILE"
echo "被限流的响应统计："
grep -E 'Non-2xx responses|Failed requests' "$RESULT_FILE" 