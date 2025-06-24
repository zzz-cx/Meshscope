#!/bin/bash
# 权重分流验证脚本
# 用法: ./weight_split.sh <service_url> <grep_pattern> <weights逗号分隔> <namespace> <pod_name> [Z] [E]
# 示例: ./weight_split.sh http://productpage:9080/productpage 'reviews-v[0-9]' 80,20 default productpage-v1-xxxx 1.96 0.05

SERVICE_URL=${1:-"http://productpage:9080/productpage"}
GREP_PATTERN=${2:-'reviews-v[0-9]'}
WEIGHTS_CSV=${3:-"80,20"}
NAMESPACE=${4:-default}
POD_NAME=${5:-productpage-v1-xxxx}
Z=${6:-1.96}   # 置信度（默认95%）
E=${7:-0.05}   # 误差（默认5%）
RESULT_FILE="../results/weight_split_$(date +%Y%m%d%H%M%S).log"

IFS=',' read -ra WEIGHTS <<< "$WEIGHTS_CSV"
TOTAL=0
for w in "${WEIGHTS[@]}"; do
  TOTAL=$((TOTAL + w))
done

if [ "$TOTAL" -eq 0 ]; then
  echo "❌ 总权重不能为0"
  exit 1
fi

echo "📦 总权重为 $TOTAL" | tee -a "$RESULT_FILE"

# ---- 计算最大方差 ----
MAX_VAR=0
for w in "${WEIGHTS[@]}"; do
  p=$(echo "scale=6; $w / $TOTAL" | bc)
  q=$(echo "scale=6; 1 - $p" | bc)
  var=$(echo "scale=6; $p * $q" | bc)
  MAX_VAR=$(awk -v a="$MAX_VAR" -v b="$var" 'BEGIN { print (a > b ? a : b) }')
done

# ---- 估算最小请求数 ----
NUM=$(echo "scale=6; ($Z * $Z * $MAX_VAR) / ($E * $E)" | bc)
NUM_REQUESTS=$(echo "$NUM + 0.999" | bc | awk '{print int($1)}')

echo "▶ 推荐发送请求数为：$NUM_REQUESTS（置信度 ≈ $Z，误差 ±$E）" | tee -a "$RESULT_FILE"
echo "▶ 正在发送请求并统计版本..."

# ---- 发起请求并提取版本（每次只取1个版本） ----
RAW_OUTPUT=$(kubectl exec -i "$POD_NAME" -n "$NAMESPACE" -- \
  sh -c "for i in \$(seq 1 $NUM_REQUESTS); do curl -s $SERVICE_URL | grep -o '$GREP_PATTERN'  | head -n1; done")

echo "$RAW_OUTPUT" >> "$RESULT_FILE"

if [[ -z "$RAW_OUTPUT" ]]; then
  echo "❌ 页面中未检测到版本信息，请确认 GREP_PATTERN 设置正确。"
  exit 1
fi

# ---- 统计版本分布 ----
declare -A VERSION_COUNTS
while read -r version; do
  [[ -z "$version" ]] && continue
  VERSION_COUNTS["$version"]=$((VERSION_COUNTS["$version"] + 1))
done <<< "$RAW_OUTPUT"

for version in "${!VERSION_COUNTS[@]}"; do
  count=${VERSION_COUNTS["$version"]}
  percent=$(echo "scale=2; 100 * $count / $NUM_REQUESTS" | bc)
  printf "  - %-10s %4d 次（%6.2f%%）\n" "$version" "$count" "$percent"
done

echo "✅ 验证完成。"