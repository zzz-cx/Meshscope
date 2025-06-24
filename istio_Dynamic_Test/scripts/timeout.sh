#!/bin/bash
# 超时模拟测试脚本
# 用法: ./timeout.sh <url> <timeout_ms>
# 示例: ./timeout.sh http://service:9080/api 1000

URL=${1:-"http://service:9080/api"}
TIMEOUT_MS=${2:-1000}
RESULT_FILE="../results/timeout_$(date +%Y%m%d%H%M%S).log"

START=$(date +%s%3N)
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" -H "x-envoy-upstream-rq-timeout-ms: $TIMEOUT_MS" "$URL" >> "$RESULT_FILE"
END=$(date +%s%3N)
ELAPSED=$((END-START))
echo "实际耗时: ${ELAPSED}ms" | tee -a "$RESULT_FILE" 