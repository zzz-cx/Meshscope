#!/bin/bash
# 重试验证测试脚本
# 用法: ./retry.sh <url> <count>
# 示例: ./retry.sh http://service:9080/api 10

URL=${1:-"http://service:9080/api"}
COUNT=${2:-10}
RESULT_FILE="../results/retry_$(date +%Y%m%d%H%M%S).log"

for i in $(seq 1 $COUNT); do
  curl -s -w "\n%{http_code} %{time_total}" "$URL" >> "$RESULT_FILE"
  echo "---" >> "$RESULT_FILE"
done
# 可根据日志分析重试次数和响应时间 