
---

### 根目录（/Meshscope）
本项目为 Istio 配置与流量管理的可视化与分析工具，包含主程序、配置解析、动态测试、前端资源等。

---

### istio_config_parser
#### 静态检测部分
该模块为项目的静态检查部分，用于解析和管理 Istio 控制面与数据面的各类配置，支持多种配置类型的读取与处理，将数据平面和控制平面的数据以拓扑图的形式展现在前端，同时进行一致性比较。

- **istio_control_config/**：存放各类 Istio 控制面资源的配置文件（如 Service、VirtualService、Gateway 等），按资源类型和命名空间分类。
- **models/**：定义数据结构和 schema，用于描述和校验控制面与数据面的数据。
- **static/**：前端静态资源，包括 HTML、CSS、JS 及其组件。
- **traffic_management/**：Istio 流量管理相关的解析器（如金丝雀发布、熔断、限流等）。
- **utils/**：工具函数，如文件操作等。
- **main_parser.py**：主解析入口，负责调度各类配置解析。
- **service.py**：服务相关的处理逻辑。
- **online-boutique-service.yaml / online-boutique.yaml**：示例微服务配置文件。

---

### istio_Dynamic_Test
#### 动态检测部分
该模块为项目的动态检测部分，用于对 Istio 配置进行动态测试和验证，包含测试用例生成、结果收集、脚本工具等，按需进行动态验证，利用测试用例模拟用户操作，比较系统行为和预期行为是否一致。

- **checker/**：测试结果校验相关脚本和数据。
- **generator/**：测试用例生成器及相关配置。
- **results/**：存放测试结果数据。
- **scripts/**：各类测试相关 shell 脚本。
- **utils/**：辅助工具函数，如 SSH 工具等。
- **README.md**：动态测试模块说明文档。
- **__init__.py**：模块初始化文件。

---

### src
#### 监控模块
主程序源码目录，包含 Istio 监控、配置解析等核心功能，监控模块，定时和按需实现配置文件的获取，辅助静态检查和动态检测的实现。

- **istio_monitor/**：Istio 运行时监控与配置解析相关代码。
  - **istio_api.py**：与 Istio API 交互的实现。
  - **istio_config_parser.py**：配置解析主逻辑。
  - **istio_sidecar_monitor.py**：Sidecar 监控脚本。
  - **istio_sidecar_config/**、**istio_control_config/**：与主目录下同名文件夹类似，存放监控和配置相关的子资源。
  - **README.md**：监控模块说明文档。

---