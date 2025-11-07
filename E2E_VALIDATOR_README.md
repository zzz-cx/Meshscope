# MeshScope 端到端验证框架使用说明

## 概述

`e2e_validator.py` 是一个完整的端到端验证框架，整合了所有模块，实现了从配置获取到一致性分析的完整流程。

## 功能特性

1. **完整的流程覆盖**：
   - 监控器获取配置（控制平面 + 数据平面）
   - 解析静态配置
   - 生成IR中间表示
   - 生成正交测试策略
   - 发送动态请求
   - 收集日志数据
   - 动态验证
   - 一致性分析和可视化

2. **详细的执行记录**：
   - 每个步骤的输入输出
   - 每个步骤的耗时
   - 错误信息和堆栈跟踪
   - 静态解析全流程总耗时
   - 动态验证全流程总耗时

3. **错误处理**：
   - 每个步骤独立处理错误
   - 即使某个步骤失败，也会继续执行后续步骤
   - 完整的错误信息记录

## 使用方法

### 基本用法

```bash
# 使用默认配置（192.168.92.131）
python e2e_validator.py --vm-host 192.168.92.131 --vm-user root --vm-password 12345678

# 指定命名空间
python e2e_validator.py --vm-host 192.168.92.131 --namespace default --vm-password 12345678

# 指定ingress URL
python e2e_validator.py --vm-host 192.168.92.131 --ingress-url http://192.168.92.131:30476/productpage --vm-password 12345678

# 指定输出目录
python e2e_validator.py --vm-host 192.168.92.131 --output-dir results/my_e2e_test --vm-password 12345678
```

### 完整参数说明

```bash
python e2e_validator.py [选项]

选项:
  --vm-host HOST        虚拟机主机IP地址 (默认: 192.168.92.131)
  --vm-user USER        SSH用户名 (默认: root)
  --vm-password PASS    SSH密码
  --namespace NS        Kubernetes命名空间 (默认: default)
  --ingress-url URL     Ingress URL (默认: http://{vm-host}:30476/productpage)
  --output-dir DIR      输出目录 (默认: results/e2e_validation)
```

## 执行流程

### 阶段1: 静态解析全流程

1. **步骤1.1: 监控器获取配置**
   - 使用 `IstioSidecarMonitor` 获取控制平面和数据平面配置
   - 保存到 `istio_config_parser/istio_monitor/istio_control_config` 和 `istio_sidecar_config`

2. **步骤1.2: 解析静态配置**
   - 调用 `parse_unified_from_dir` 解析配置
   - 生成 `SystemIR` 对象

3. **步骤1.3: 生成IR中间表示**
   - 使用 `SimpleIRConverter` 转换为简化IR格式
   - 保存到 `output_dir/simple_ir_output.json`

### 阶段2: 动态验证全流程

4. **步骤2.1: 生成正交测试策略**
   - 使用 `TestCaseGenerator` 基于IR生成测试用例
   - 保存测试矩阵到 `output_dir/output_matrix.json`

5. **步骤2.2: 发送动态请求**
   - 使用 `TrafficDriver` 执行测试用例
   - 发送HTTP请求并收集响应

6. **步骤2.3: 收集日志数据**
   - 使用 `EnvoyLogCollector` 收集Envoy访问日志
   - 保存到 `results/logs/`

7. **步骤2.4: 动态验证**
   - 使用 `run_verification` 验证测试结果
   - 生成验证报告

### 阶段3: 一致性分析和可视化

8. **步骤3.1: 一致性分析和可视化**
   - 使用 `Pipeline` 运行完整的一致性检查
   - 生成一致性报告和可视化数据

## 输出结果

### 1. 执行日志

所有执行日志保存到 `e2e_validation.log`，包括：
- 每个步骤的开始和结束时间
- 输入参数
- 输出结果
- 错误信息（如果有）

### 2. 详细结果JSON

保存到 `{output_dir}/e2e_result_{timestamp}.json`，包含：
- 总体执行时间
- 静态解析全流程耗时
- 动态验证全流程耗时
- 每个步骤的详细信息（输入、输出、耗时、错误）

### 3. 中间文件

- `simple_ir_output.json`: IR中间表示
- `output_matrix.json`: 测试矩阵
- `consistency_report_{timestamp}.json`: 一致性报告

### 4. 验证结果

- `{output_dir}/verification/`: 动态验证结果
- `{output_dir}/consistency_report_*.json`: 一致性报告

## 结果示例

### 控制台输出

```
================================================================================
开始端到端验证流程
================================================================================

================================================================================
阶段1: 静态解析全流程
================================================================================
[step_01] 开始执行: 1.1 监控器获取配置
  输入参数: {}
[step_01] 执行成功: 1.1 监控器获取配置 (耗时: 5.234秒)

[step_02] 开始执行: 1.2 解析静态配置
  输入参数: {...}
[step_02] 执行成功: 1.2 解析静态配置 (耗时: 0.023秒)

[step_03] 开始执行: 1.3 生成IR中间表示
  输入参数: {...}
[step_03] 执行成功: 1.3 生成IR中间表示 (耗时: 0.012秒)

静态解析全流程耗时: 5.269秒

================================================================================
阶段2: 动态验证全流程
================================================================================
[step_04] 开始执行: 2.1 生成正交测试策略
...
动态验证全流程耗时: 58.123秒

================================================================================
端到端验证摘要
================================================================================

总执行时间: 63.392秒
执行状态: 成功

静态解析全流程: 5.269秒
动态验证全流程: 58.123秒

各步骤耗时:
--------------------------------------------------------------------------------
✓ [step_01] 1.1 监控器获取配置: 5.234秒
✓ [step_02] 1.2 解析静态配置: 0.023秒
✓ [step_03] 1.3 生成IR中间表示: 0.012秒
✓ [step_04] 2.1 生成正交测试策略: 0.145秒
✓ [step_05] 2.2 发送动态请求: 52.456秒
✓ [step_06] 2.3 收集日志数据: 3.123秒
✓ [step_07] 2.4 动态验证: 2.399秒
✓ [step_08] 3.1 一致性分析和可视化: 0.345秒
================================================================================
```

### JSON结果格式

```json
{
  "timestamp": "2025-01-15T10:30:00",
  "total_duration": 63.392,
  "success": true,
  "static_pipeline_duration": 5.269,
  "dynamic_pipeline_duration": 58.123,
  "steps": [
    {
      "step_name": "1.1 监控器获取配置",
      "step_id": "step_01",
      "success": true,
      "duration": 5.234,
      "inputs": {...},
      "outputs": {...},
      "error": null,
      "error_traceback": null
    },
    ...
  ]
}
```

## 故障排查

### 常见问题

1. **SSH连接失败**
   - 检查 `--vm-host`、`--vm-user`、`--vm-password` 是否正确
   - 检查网络连通性

2. **配置获取失败**
   - 检查Kubernetes集群是否可访问
   - 检查命名空间是否正确

3. **测试用例生成失败**
   - 检查 `istio_config.json` 是否存在
   - 检查配置文件格式是否正确

4. **动态请求失败**
   - 检查ingress URL是否正确
   - 检查服务是否正在运行

5. **日志收集失败**
   - 检查Envoy access log是否启用
   - 检查日志目录权限

### 调试模式

查看详细日志：
```bash
# 查看日志文件
tail -f e2e_validation.log

# 查看特定步骤的详细信息
grep "step_02" e2e_validation.log
```

## 注意事项

1. **权限要求**：
   - 需要对Kubernetes集群有读取权限
   - 需要SSH访问权限到集群节点

2. **依赖要求**：
   - 确保所有依赖模块已正确安装
   - 确保配置文件路径正确

3. **性能考虑**：
   - 动态验证阶段可能需要较长时间（50-90秒）
   - 建议在测试环境中运行

4. **结果保存**：
   - 所有结果保存在 `{output_dir}` 目录
   - 建议定期清理旧的结果文件

## 扩展使用

### 在代码中使用

```python
from e2e_validator import E2EValidator

config = {
    'vm_host': '192.168.92.131',
    'vm_user': 'root',
    'vm_password': '12345678',
    'namespace': 'default',
    'ingress_url': 'http://192.168.92.131:30476/productpage',
    'output_dir': 'results/my_test'
}

validator = E2EValidator(config)
results = validator.run_full_pipeline()

print(f"总耗时: {results.total_duration:.3f}秒")
print(f"静态解析: {results.static_pipeline_duration:.3f}秒")
print(f"动态验证: {results.dynamic_pipeline_duration:.3f}秒")
```

## 相关文档

- `istio_config_parser/README.md`: 配置解析模块文档
- `istio_Dynamic_Test/README.md`: 动态测试模块文档
- `consistency_checker/README.md`: 一致性检查模块文档

