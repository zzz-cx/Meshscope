#!/bin/bash
# 故障注入测试脚本
# 用法: ./fault_injection.sh <url> <count>
# 示例: ./fault_injection.sh http://reviews:9080/ 10

URL=${1:-"http://reviews:9080/"}
COUNT=${2:-10}
RESULT_FILE="../results/fault_injection_$(date +%Y%m%d%H%M%S).log"

for i in $(seq 1 $COUNT); do
  curl -s -w "\n%{http_code} %{time_total}" "$URL" >> "$RESULT_FILE"
  echo "---" >> "$RESULT_FILE"
done
# 可分析响应码和延迟，判断故障注入效果 