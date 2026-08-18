# Istio 配置解析与分析

parser 把控制面 YAML 和数据面 Envoy dump 映射成**同一套语义模型**，做平面对齐和跨资源冲突，并写出 `aligned_semantic.json`。动态验证和 checker 都消费这份产物，不要在那些模块里再解析 YAML。

推荐：

```bash
python -m configpilot static --namespace default --export
python -m istio_config_parser.main_parser --namespace default --export
```

默认写出 `results/consistency/aligned_semantic.json`（pairs、conflicts、expected_tuples、graph_data）。

`graph_data` 供 Web「静态分析」页使用：服务节点带命名空间、声明式资源（VS/DR/EF 等）和对应数据面规则摘要。

## 核心特性

### 统一解析架构
- **语义聚合**：VirtualService + DestinationRule 等到同一功能
- **双平面统一**：`FunctionModel` + 语义元组 `⟨predicate, action, scope, constraint⟩`
- **对齐与冲突**：平面差异 + 缺 subset / 路由优先级 / Gateway 选择器
- **并行处理**：多线程解析

### 功能解析支持
- 路由、熔断、限流、流量迁移、重试、超时等


## 📁 项目结构

### 核心模块

#### `main_parser.py` - 主解析器

```bash
python -m istio_config_parser.main_parser
python -m istio_config_parser.main_parser --export
python -m istio_config_parser.main_parser --namespace online-boutique --max-workers 4 --details
```

**主要参数**：
- `--mode {legacy,unified}`：解析模式（默认unified）
- `--export`：导出独立的模型文件
- `--output-dir`：模型文件输出目录（默认models_output）
- `--no-parallel`：禁用并行处理
- `--max-workers`：最大工作线程数
- `--namespace`：命名空间过滤
- `--details`：显示详细信息和问题列表

#### `models/` - 数据模型层
统一的数据模型定义，支持控制平面和数据平面的统一表示：

- **`function_models.py`**：功能模型（Routing、CircuitBreaker、RateLimit、TrafficShifting 等）
- **`semantic_tuple.py`**：语义元组
- **`alignment_models.py`**：平面对齐
- **`ir_models.py`**：IR
- **`data_structures.py`**：向后兼容结构

#### `parsers/` - 解析器层
模块化的解析器实现，支持并行处理：

- **`unified_parser.py`**：统一解析器，支持并行处理和语义聚合
- **`base_parser.py`**：解析器基类和注册机制
- **`routing_parser.py`**：路由配置解析器
- **`circuit_breaker_parser.py`**：熔断配置解析器
- **`ratelimit_parser.py`**：限流配置解析器
- **`traffic_shifting_parser.py`**：流量迁移配置解析器
- **`model_exporter.py`**：模型导出器，生成标准化的模型文件

#### `utils/` - 工具模块
通用工具和性能测试功能：

- **`file_utils.py`**：文件读写和配置加载工具
- **`performance_tester.py`**：性能测试工具，支持CPU、内存、时延监控

### 配置与监控

#### `istio_monitor/` - 配置监控
- **`istio_control_config/`**：控制平面配置目录
  - 按资源类型和命名空间组织的YAML配置
  - 支持services、virtualservices、destinationrules、envoyfilters等
- **`istio_sidecar_config/`**：数据平面配置目录
  - routes.json、clusters.json、listeners.json等Envoy配置
- **`export_data_plane_config.py`**：数据平面配置导出（routes/clusters/listeners，支持 istioctl / kubectl-exec / from-yaml）
- **`export_control_plane_config.py`**：控制平面配置导出（VirtualService、DestinationRule、Service 等，支持 kubeconfig / 远程集群）
- **`istio_sidecar_monitor.py`**：配置监控器（编排上述两个模块，支持定期拉取与变更回调）
- **`istio_api.py`**：Istio API接口
- **`istio_config_parser.py`**：配置解析器

#### `models_output/` - 模型输出
解析器生成的标准化模型文件：
- **`control_plane_models.json`**：控制平面功能模型
- **`data_plane_models.json`**：数据平面功能模型
- **`model_comparison.json`**：控制平面与数据平面对比分析
- **`visualization_data.json`**：可视化数据
- **`graph_visualization_data.json`**：图形可视化数据

### 向后兼容

#### `traffic_management/` - 传统解析器
保留的传统解析器（已废弃，用于向后兼容）：
- **`canary_parser.py`**：金丝雀发布解析
- **`circuit_breaker_parser.py`**：熔断解析
- **`ratelimit_parser.py`**：限流解析
- **`route_parser.py`**：路由解析
- **`service_parser.py`**：服务解析

## 使用方法

```bash
python -m istio_config_parser.main_parser
python -m istio_config_parser.main_parser --export
python -m istio_config_parser.main_parser --namespace online-boutique --max-workers 4 --export --details
```

对齐产物默认在 `results/consistency/aligned_semantic.json`。`--export` 仍可额外写出 `models_output/` 下的平面模型文件。

### 数据平面 / 控制面导出

一致性检验需要 `routes.json`、`clusters.json`、`listeners.json`：

```bash
python -m istio_config_parser.istio_monitor.export_data_plane_config --method istioctl
python -m istio_config_parser.istio_monitor.export_data_plane_config --pod <pod-name> -n default --method kubectl-exec
python -m istio_config_parser.istio_monitor.export_control_plane_config
python -m istio_config_parser.istio_monitor.istio_sidecar_monitor --update-now
```

### 性能优化

1. **并行处理**（默认启用）：
   ```bash
   # 自动计算线程数
   python -m istio_config_parser.main_parser --export
   python -m istio_config_parser.main_parser --export --max-workers 8
   python -m istio_config_parser.main_parser --no-parallel
   ```

2. **性能测试**：
   ```bash
   # 使用性能测试工具
   python utils/performance_tester.py --help
   ```

### 输出说明

主产物是 `results/consistency/aligned_semantic.json`（对齐 pairs、冲突、期望元组、静态 `graph_data`）。`--export` 时 `models_output/` 另有平面模型与对比文件。

## 📊 输出示例

### 系统摘要
```
总服务数:       37
一致的服务:     1 (2.7%)
不一致的服务:   0 (0.0%)
一致性比例:     2.70%
总问题数:       59
  - 错误:       3
  - 警告:       56
```

### 并行处理日志
```
[并行] 开始并行解析控制平面配置...
[并行] 控制平面-routing: 解析到 6 个配置
[并行] 控制平面-circuit_breaker: 解析到 5 个配置
[并行] 控制平面-traffic_shifting: 解析到 3 个配置
[并行] 控制平面解析完成，共 3 个解析结果
```

## 🔧 开发说明

### 扩展解析器
1. 继承 `BaseParser` 类
2. 实现 `parse_control_plane` 和 `parse_data_plane` 方法
3. 在 `UnifiedParser` 中注册新的解析器

### 添加功能模型
1. 在 `models/function_models.py` 中定义新的 `FunctionModel` 子类
2. 对应更新解析器实现
3. 更新对齐和IR构建逻辑

## 📈 性能特性

- **并行处理**：支持多线程并行解析，显著提升处理速度
- **内存优化**：统一数据模型减少内存占用
- **错误处理**：完善的异常处理和日志记录
- **可扩展性**：模块化设计，易于扩展新功能

## 🎯 应用场景

1. **Istio配置分析**：分析服务网格的配置一致性
2. **性能优化**：识别配置问题和性能瓶颈
3. **可视化展示**：生成配置的可视化图表
4. **CI/CD集成**：自动化配置验证和分析
5. **故障排查**：快速定位配置不一致问题

