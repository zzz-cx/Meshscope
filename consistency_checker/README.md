# 一致性验证与可视化

checker 只消费 parser 的 `aligned_semantic.json` 和动态验证结果，生成报告、三层图和 Web UI。不在本模块解析 YAML。

推荐入口：

```bash
python -m configpilot web --port 8080
python -m configpilot run --namespace default
python -m configpilot check --namespace default
```

本模块仍可单独调用：`python -m consistency_checker.main --mode full|static|consistency|web`。

## 职责

- 读对齐产物：策略、服务图、跨资源冲突
- 读动态结果：期望 vs 观测
- 一致性判定与报告
- 三层配置依赖图（控制面 / 数据面 / 配置资源）
- Web：总览、静态资源图、动态、一致性、三层图

## 目录

```text
consistency_checker/
├── config.py                 # 读 configpilot.json
├── main.py
├── models/
├── core/
│   ├── static_analyzer.py    # 只读 aligned_semantic.json
│   ├── dynamic_analyzer.py
│   ├── consistency_checker.py
│   └── orchestrator.py
├── visualizer/
│   ├── graph_generator.py
│   ├── three_layer_graph_generator.py
│   └── report_generator.py
└── web/
    ├── server.py
    ├── templates/index.html
    └── static/
        ├── css/app.css
        ├── js/app.js
        └── three_layer_graph_viewer.html
```

## 运行

依赖：`pip install -r requirements.txt`。集群地址、快照目录、Web 端口在根目录 `configpilot.json`；总览页改探测地址会写回该文件。

```bash
python -m consistency_checker.main --mode full --namespace online-boutique
python -m consistency_checker.main --mode web --port 8080
```

访问 `http://localhost:8080`。

### 结果位置

- JSON 报告：`results/consistency/report_*.json`
- HTML：`results/visualization/report_*_report.html`
- 三层图：`results/visualization/*_three_layer_graph.json`
- 对齐模型（由 parser 写出）：`results/consistency/aligned_semantic.json`

## 数据流

```text
parser → aligned_semantic.json
动态验证 → 矩阵 / 观测 / 校验报告
                │
                ▼
         Pipeline / Web API
                │
                ├─ 静态分析页：graph_data（命名空间、声明式配置、数据面规则）
                └─ 三层图页：ThreeLayerGraphGenerator（不一致、Exp/Obs 权重）
```

## 命令行

```text
python -m consistency_checker.main
  --mode {full,static,consistency,web}
  --namespace NAMESPACE
  --config CONFIG
  --port PORT
```

更完整的流水线请用 `python -m configpilot run`。

## Web

样式为 PatternFly 深色控制台。静态分析页按命名空间展示服务和 VS/DR/EF/Gateway；点击节点查看声明式 YAML 与对应 Envoy 规则。三层图支持搜索、邻域、路径、仅看不一致边，见 [docs/THREE_LAYER_GRAPH.md](../docs/THREE_LAYER_GRAPH.md)。

## 编程调用

```python
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.orchestrator import Pipeline

# StaticAnalyzer 读的是 parser 产物，config_dir 仅作兼容参数
analyzer = StaticAnalyzer(namespace="online-boutique")
result = analyzer.analyze()

pipeline = Pipeline(namespace="online-boutique")
report = pipeline.run_full_pipeline()
```

动态分析器读测试矩阵与验证目录，期望同样来自对齐模型，而不是 YAML。

## 依赖

Python 3.8+、Flask、PyYAML，以及同仓库的 `istio_config_parser`、`istio_Dynamic_Test`。
