# 三层空间配置依赖图

用于定位「哪条配置、作用在哪个服务、控制面期望与数据面实测是否一致」。checker 消费 parser / 动态产物生成 JSON，Web 用 Cytoscape 展示。

## 模型结构

### 第一层：控制面 / 数据面全局

- 节点：Control Plane、Data Plane、Consistency Checker
- 边：配置与运行时状态的一致 / 不一致匹配

### 第二层：服务关系

- 控制面：服务、subset
- 数据面：Envoy、Pod
- 边：Route、TrafficSplit、RateLimit、Gateway 等

流量分割不一致时，数据面可同时画出两条边：

- **Exp**：灰色虚线，控制面期望权重（如 20% / 80%）
- **Obs**：红色实线，Envoy 实测权重（如 50% / 50%）

### 第三层：配置资源

- VS、DR、EF、SE、RLS 等
- 边：资源之间的引用（如 DR subset ← VS）

### 跨层边

第三层资源指向第二层服务 / subset。

## 生成

完整流水线会自动写出 `{report_id}_three_layer_graph.json`：

```bash
python -m configpilot run --namespace default
# 或
python -m consistency_checker.main --mode full --namespace default
```

编程（从已有对齐 / 一致性结果）：

```python
from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator

generator = ThreeLayerGraphGenerator.from_static_result(
    static_result=static_result,
    consistency_result=consistency_result,
    namespace="default",
)
generator.generate()
generator.save_to_file("three_layer_graph.json")
```

## JSON 形状

```json
{
  "nodes": [
    {"id": "control_plane", "label": "Control Plane", "layer": "layer1", "plane_type": "control_plane"},
    {"id": "cp_svc_reviews", "label": "reviews", "layer": "layer2", "node_type": "service"},
    {"id": "cp_reviews_VS", "label": "VS", "layer": "layer3", "resource_type": "VS"}
  ],
  "edges": [
    {"source": "control_plane", "target": "consistency_checker", "layer": "layer1", "match_type": "consistent"},
    {"source": "cp_svc_productpage", "target": "cp_svc_reviews", "layer": "layer2", "relation_type": "route"},
    {"source": "envoy-reviews", "target": "pod-v1", "layer": "layer2", "role": "expected", "label": "Exp 20%"},
    {"source": "envoy-reviews", "target": "pod-v1", "layer": "layer2", "role": "observed", "label": "Obs 50%"}
  ],
  "layers": [
    {"id": "layer1", "name": "数据面/控制面全局"},
    {"id": "layer2", "name": "服务关系层"},
    {"id": "layer3", "name": "配置关系层"}
  ]
}
```

`edge.role`：`expected` | `observed`（仅流量分割双轨边需要）。

## Web 查看器

```bash
python -m configpilot web --port 8080
```

- 主界面「三层依赖图」页（iframe）
- 或直接打开 `http://localhost:8080/three_layer_graph`
- 指定报告：`/three_layer_graph?report_id=report_xxx`
- 也可在查看器里加载本地 JSON

交互：

- 搜索节点（`/` 或 Ctrl+K）、邻域高亮、双击聚焦
- 路径查找（`P`，再点两个节点）
- 层级 / 平面过滤；「只显示有配置资源的节点」；「仅看不一致边」
- 左侧不一致卡片、画布钉、右侧检查器
- 快捷键 `F` 适应视图，`Esc` 清除，`?` 帮助
- 导出 PNG

视觉与主应用一致：PatternFly 深色、无金色光晕。选中为蓝色描边。

API：

```text
GET /api/three_layer_graph/latest
GET /api/three_layer_graph/<report_id>
```

## 和静态分析图的区别

| | 静态分析页 | 三层依赖图 |
|--|------------|------------|
| 来源 | parser 的 `graph_data` | checker 的三层生成器 |
| 重点 | 每个服务在哪个命名空间、声明式 YAML、对应 Envoy 规则 | 控制面 / 数据面结构与不一致定位 |
| 时机 | 跑完静态即可 | 建议静态 + 动态后再看完整不一致 |

## 元素对应

| 元素 | 实现 |
|------|------|
| Control / Data Plane 框 | `layer1` 的 `control_plane` / `data_plane` |
| 服务 / subset | `layer2` |
| Envoy / Pod | `layer2` 数据面节点 |
| VS / DR / EF | `layer3` |
| Exp / Obs 权重 | `edge.role` |
