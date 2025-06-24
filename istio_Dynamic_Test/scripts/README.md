# scripts 目录说明

本目录用于存放针对 Istio 配置的各类动态测试脚本。

## 建议脚本命名
- route_match.sh / route_match.py：路由匹配测试
- weight_split.sh / weight_split.py：权重分流测试
- circuit_breaker.sh / circuit_breaker.py：熔断模拟
- timeout.sh / timeout.py：超时模拟
- retry.sh / retry.py：重试验证
- ratelimit.sh / ratelimit.py：限流测试
- fault_injection.sh / fault_injection.py：故障注入

## 说明
- 每个脚本请注明用途、参数说明和预期输出
- 可根据实际需求扩展更多测试类型 

## 针对各个配置细节的自动化 Bash 测试脚本，包括：

1. **route_match.sh**：路由匹配测试，支持自定义路径和 header，输出响应内容到 results 目录。
2. **weight_split.sh**：权重分流测试，批量请求并统计不同版本响应次数。
3. **circuit_breaker.sh**：熔断模拟测试，高并发请求，统计失败和非 2xx 响应。
4. **timeout.sh**：超时模拟测试，支持自定义超时时间，记录实际耗时。
5. **retry.sh**：重试验证测试，模拟错误响应并检测重试行为。
6. **ratelimit.sh**：限流测试，高并发突发请求，统计被限流的响应数量。
7. **fault_injection.sh**：故障注入测试，检测错误码或延迟。
