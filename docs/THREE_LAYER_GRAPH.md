# 三层空间配置依赖图

基于三层空间模型构建的 Istio 服务依赖图，用于可视化控制面、数据面配置及其一致性关系。

## 模型结构

### 第一层：数据面/控制面全局

- **节点**：Control Plane（控制面）、Data Plane（数据面）、Consistency Checker（一致性检查器）
- **边**：控制面/数据面 → 一致性检查器，表示配置与运行时状态的**一致/不一致匹配**内容
- **用途**：展示配置验证流程，虚线表示配置信息传递与校验

### 第二层：服务关系层

- **节点**：
  - 控制面：服务（SVC-A, SVC-B）、子集（SVC-A V1, SVC-A V2）
  - 数据面：Envoy 代理（envoy-svcA）、Pod（pod svcA/v1）、全局限速器（rls-server）
- **边**：服务间**功能关系**
  - `Route`：路由依赖
  - `RateLimit`：限流关系
  - `TrafficSplit`：流量分配（70%/30%）
  - `Gateway`：网关入口

### 第三层：配置关系层

- **节点**：Istio 配置资源
  - `DR`：DestinationRule
  - `VS`：VirtualService
  - `EF`：EnvoyFilter
  - `RLS`：RateLimitService
  - `SE`：ServiceEntry
- **边**：配置资源**依赖关系**（服务内）
  - DR → VS（Subnet 引用）
  - EF → RLS → DR → SE（限流链）

### 跨层边：第三层 → 第二层

- **服务间依赖**：VS 指向目标服务（Route）、EF/RLS 指向受影响服务（RateLimit）
- **服务内依赖**：VS 指向子集（流量分配）

## 使用方式

### 1. 通过流水线自动生成

运行完整一致性验证流水线时，会自动生成三层图：

```bash
python -m consistency_checker.main run
```

输出文件：`{report_id}_three_layer_graph.json`

### 2. 从静态分析结果生成

```python
from consistency_checker.visualizer import ThreeLayerGraphGenerator

# 假设已有 static_result（来自 StaticAnalyzer.analyze()）
generator = ThreeLayerGraphGenerator.from_static_result(
    static_result=static_result,
    consistency_result=consistency_result,  # 可选
    namespace="default",
)
generator.generate()
generator.save_to_file("three_layer_graph.json")

# 或获取 D3 兼容的字典
d3_data = generator.to_d3_json()
```

### 3. 直接传入控制面/数据面数据

```python
generator = ThreeLayerGraphGenerator(
    control_plane_data=control_plane_result,
    data_plane_data=data_plane_result,
    config_edges=config_edges,
    consistency_result=consistency_result,
)
generator.generate()
```

## 输出格式（D3.js 兼容）

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
    {"source": "cp_reviews_VS", "target": "cp_svc_ratings", "layer": "cross_layer", "relation_type": "route"}
  ],
  "layers": [
    {"id": "layer1", "name": "数据面/控制面全局"},
    {"id": "layer2", "name": "服务关系层"},
    {"id": "layer3", "name": "配置关系层"}
  ],
  "metadata": { ... }
}
```

## Web 前端展示

生成的 JSON 可直接用于 Web 前端绘制。支持两种方式：

### 方式一：本地文件加载

1. 生成三层图 JSON：`python -m consistency_checker.main run` 或手动调用 `ThreeLayerGraphGenerator`
2. 打开 `consistency_checker/web/static/three_layer_graph_viewer.html`（用浏览器直接打开，或通过 Web 服务）
3. 点击「选择文件」加载 `*_three_layer_graph.json`

### 方式二：通过 Web 服务

1. 启动 Web 服务：`python -m consistency_checker.web.server`（默认端口 8080）
2. 访问：`http://localhost:8080/three_layer_graph`
3. 或带 report_id 加载：`http://localhost:8080/three_layer_graph?report_id=report_20260312_120000`

查看器基于 Cytoscape.js，支持：
- 按层级过滤（第一层/第二层/第三层/跨层）
- 按平面类型过滤（控制面/数据面）
- 节点点击查看详情
- 导出 PNG

### 前端集成

若需在自有前端集成，JSON 格式为：

```javascript
// 标准图结构，可直接用于 D3.js / Cytoscape / ECharts
fetch('/api/three_layer_graph/report_xxx').then(r => r.json()).then(data => {
  // data.nodes: [{id, label, layer, plane_type, node_type, resource_type}]
  // data.edges: [{source, target, layer, relation_type, label, weight}]
});
```

## 与参考图的对应关系

| 参考图元素 | 本实现 |
|-----------|--------|
| Control Plane 矩形 | `layer1` 节点 `control_plane` |
| Data Plane 矩形 | `layer1` 节点 `data_plane` |
| Consistency Checker | `layer1` 节点 `consistency_checker` |
| SVC-A, SVC-B | `layer2` 节点 `cp_svc_*` |
| SVC-A V1, V2 | `layer2` 节点 `cp_svc_*_v1` 等 |
| envoy-svcA | `layer2` 节点 `dp_envoy_*` |
| pod svcA/v1 | `layer2` 节点 `dp_pod_*` |
| DR, VS, EF, RLS, SE | `layer3` 节点 |
| Route / RateLimit 边 | `layer2` 或 `cross_layer` 边 |
