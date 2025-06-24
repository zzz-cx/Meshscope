# Istio 配置动态测试

本目录用于实现和管理针对 Istio 配置的动态测试脚本。通过自动化发送特定数据报文，检测服务网格中各类流量管理和故障注入等配置是否生效，辅助验证微服务治理策略的正确性。

## 主要测试类型与方法

| 测试类型   | 请求方式（示例） | 验证手段 |
|------------|------------------|----------|
| 路由匹配   | `curl -s -H "source: jason" http://productpage:9080/productpage` | 响应内容是否命中 v3（如 `grep review`） |
| 权重分流   | `for i in {1..100}; do curl http://productpage:9080/productpage; done` | 统计响应内容分布，`grep review` |
| 熔断模拟   | `ab -n 200 -c 50 http://reviews:9080/` 或自写循环压力脚本 | 观察是否出现断流或拒绝响应 |
| 超时模拟   | 配置调用超时时间 < 故意 delay 的服务响应（如 EnvoyFilter 模拟延迟）或请求头 `x-envoy-upstream-rq-timeout-ms` | 观察是否按时失败 |
| 重试验证   | 配置错误响应 + 重试策略，观察访问是否尝试重试（可用日志辅助确认） | 查看访问时间或日志请求次数 |
| 限流测试   | 使用压力脚本生成突发请求 | 响应中部分请求被拒绝 |
| 故障注入   | `curl http://reviews:9080/`（无需特殊 header） | 响应应含错误码（如 HTTP 500）或延迟显著 |

## 目录结构建议

- `scripts/`：存放各类 shell/python 测试脚本
- `cases/`：存放具体的测试用例描述（如 YAML/JSON/Markdown）
- `results/`：存放测试结果及日志
- `README.md`：本说明文档

## 实现建议

- 推荐使用 Python（如 requests、concurrent.futures）或 Bash 脚本实现自动化测试
- 可集成 pytest、unittest 等测试框架，便于批量执行和结果统计
- 支持参数化配置（如目标服务地址、请求头、并发数等）
- 可扩展支持自定义验证逻辑（如正则匹配、响应码统计等）

## 示例：简单路由匹配测试脚本

```bash
#!/bin/bash
curl -s -H "source: jason" http://192.168.92.131/productpage | grep review
```

## 贡献指南

1. 新增测试类型请补充本 README
2. 所有脚本需注明用途、参数说明和预期输出
3. 测试结果建议统一输出到 `results/` 目录 