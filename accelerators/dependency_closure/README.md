# 可选 Go 依赖闭包内核

该程序只计算已经解析的关系图上的定向闭包。输入输出带参照模型身份；它不决定策略正确性、探针合并、并发许可或配置变更。

使用 Go 1.23+，不依赖第三方 Go 模块。Linux：

```bash
cd accelerators/dependency_closure
go build -o /tmp/configpilot-closure .
cd ../..
python -m configpilot plan --aligned aligned_semantic.json \
  --compute-backend go --compute-workers 2 \
  --go-binary /tmp/configpilot-closure --output-dir results/relational/go-plan
```

Windows PowerShell：

```powershell
go -C accelerators/dependency_closure build -o "$env:TEMP/configpilot-closure.exe" .
python -m configpilot plan --aligned aligned_semantic.json --compute-backend go --compute-workers 2 --go-binary "$env:TEMP/configpilot-closure.exe" --output-dir results/relational/go-plan
```

独立 worker 计算各来源的闭包，输入关系只读。并行执行线程按 worker 和可见 CPU 数取较小值；容器配额和其他负载仍需调用者考虑，不是自动容量发现。

新 Python 默认使用索引化闭包；Go 当前保持固定点扫描实现。历史实验中两者尚未使用这一相同的新索引策略，不能将旧实验比值作为当前 Go 后端的性能承诺。短任务可能更适合 Python 串行索引。

```powershell
$env:CONFIGPILOT_TEST_GO_BINARY = "$env:TEMP/configpilot-closure.exe"
python -m unittest istio_Dynamic_Test.tests.test_new_architecture.GoEngineTests -v
```

编译产物不要提交到源代码目录。模型不匹配、返回缺项或二进制不可用时明确报错，不静默跳过义务。
