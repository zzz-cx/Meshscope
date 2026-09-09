# 配置变更响应性评估

本目录包含用于评估系统在运行时环境中频繁修改配置时的响应性的脚本。

## 功能说明

评估脚本 `config_change_responsiveness.py` 实现了以下功能：

1. **配置变更监听**：使用 Kubernetes/Istio watchers 监听配置变更
2. **配置更新模拟**：模拟管理员更新配置（支持 3、5、10 个配置项）
3. **时延记录**：记录以下阶段的时延：
   - **配置变更应用时延**：从开始应用配置到 `kubectl apply` 完成的时间
   - **配置变更检测时延**：从配置应用完成到检测到变更的时间
   - **增量配置解析时延**：解析变更后的配置并构建系统IR的时间
   - **依赖图更新时延**：更新服务依赖关系图的时间
   - **动态验证时延**：对受影响的策略进行动态验证的时间
   - **可视化刷新时延**：刷新配置图并标记策略状态的时间
   - **总时延**：从配置变更应用到所有处理完成的总时间

4. **多应用支持**：支持 Bookinfo、Online Boutique 和 Sock Shop 应用

## 使用方法

### 基本用法

```bash
# 使用 Bookinfo 应用（默认）
python evaluation/performance/config_change_responsiveness.py \
    --vm-host 192.168.92.131 \
    --vm-user root \
    --vm-password 12345678 \
    --namespace default

# 指定应用类型
python evaluation/performance/config_change_responsiveness.py \
    --app-name online-boutique \
    --vm-host 192.168.92.131 \
    --vm-user root \
    --vm-password 12345678

# 指定评估范围和迭代次数
python evaluation/performance/config_change_responsiveness.py \
    --scopes 3 5 10 \
    --iterations 10 \
    --vm-host 192.168.92.131 \
    --vm-user root \
    --vm-password 12345678
```

### 参数说明

- `--vm-host`: 虚拟机主机IP地址（必填）
- `--vm-user`: SSH用户名（默认：root）
- `--vm-password`: SSH密码
- `--namespace`: Kubernetes命名空间（默认：default）
- `--app-name`: 应用名称，可选值：bookinfo、online-boutique、sock-shop（默认：bookinfo）
- `--k8s-host`: Kubernetes API服务器地址（可选）
- `--k8s-token`: Kubernetes API认证token（可选）
- `--scopes`: 配置变更范围（配置项数量），可指定多个，如 `--scopes 3 5 10`（默认：[3, 5, 10]）
- `--iterations`: 每个范围的迭代次数（默认：5）
- `--output-dir`: 输出目录（默认：results/performance/config_change_responsiveness）

## 评估流程

1. **启动监控器**：启动 Istio 配置监控器，监听 Kubernetes 资源变更
2. **生成配置变更**：根据指定的范围（3、5、10个配置项）生成配置变更
3. **应用配置变更**：使用 `kubectl apply` 应用配置变更
4. **检测配置变更**：监控器检测到配置变更，记录检测时延
5. **解析配置**：增量解析配置并更新依赖图
6. **动态验证**：对受影响的策略进行动态验证
7. **可视化刷新**：刷新配置图，标记策略状态（static-inconsistent、dynamic-inconsistent、fully-consistent）
8. **记录时延**：记录各阶段的时延数据

## 技术实现细节

### 如何知道配置应用完成？

配置应用完成的判断基于 `kubectl apply` 命令的返回状态：

1. **执行 `kubectl apply`**：
   - **优先使用本地 kubectl**：如果本地有 kubectl 且可以连接到集群，则使用本地命令
   - **否则使用 SSH**：如果本地不可用，则通过 SSH 在虚拟机上执行 `kubectl apply -f -` 命令
   - 将配置 YAML 内容通过标准输入传递给 kubectl
   - 脚本启动时会自动检测本地 kubectl 是否可用（通过 `kubectl version --client` 和 `kubectl get nodes`）

2. **判断应用成功**：
   - 如果 `kubectl apply` 命令返回成功（exit code 0），则认为配置已成功应用到 Kubernetes
   - 记录此时的时间戳作为 `配置应用完成时间`
   - 如果命令失败，记录错误信息并标记为失败

3. **时间记录**：
   - `apply_start_time`：开始执行 `kubectl apply` 的时间
   - `change_time`：`kubectl apply` 成功返回的时间（配置应用完成时间）
   - `apply_time`：应用时延 = `change_time` - `apply_start_time`

**注意**：`kubectl apply` 成功返回只是表示配置已提交到 Kubernetes API Server，但配置可能还在传播到各个组件（如 Istio Control Plane、Sidecar 等）。实际生效可能需要额外时间。

### 如何检测到配置变更？

配置变更检测采用**主动验证**的方式，而不是被动等待 Kubernetes Watch 事件：

1. **等待 API 更新**：
   - 配置应用完成后，等待 0.3 秒让 Kubernetes API Server 更新
   - 这是从 `kubectl apply` 完成到配置在 API 中可查询的最小延迟

2. **验证配置存在**：
   - **优先使用本地 kubectl**：如果本地有 kubectl 且可以连接到集群，则使用本地命令
   - **否则使用 SSH**：如果本地不可用，则通过 SSH 在虚拟机上执行 `kubectl get virtualservice <name> -n <namespace> -o name`
   - 检查每个变更的 VirtualService 是否已存在于 Kubernetes 中
   - 如果所有配置都已存在，则认为配置变更已被"检测到"

3. **记录检测时间**：
   - `detection_time`：验证完成的时间（所有配置都已确认存在）
   - `change_detection_time`：检测时延 = `detection_time` - `change_time`

**执行方式选择逻辑**：

脚本启动时会自动检测：
1. 检查本地是否有 `kubectl` 命令
2. 检查本地 `kubectl` 是否可以连接到集群（执行 `kubectl get nodes`）
3. 如果本地可用，则使用本地 kubectl（更快速，无需SSH连接）
4. 如果本地不可用，则使用 SSH 在虚拟机上执行（需要配置 `--vm-host`、`--vm-user`、`--vm-password`）

**为什么使用主动验证而不是 Watch？**

- Kubernetes Watch 机制需要在本地配置 kubeconfig，但评估脚本在本地可能没有配置
- 通过统一的执行接口（本地或SSH），可以灵活选择执行方式
- 主动验证更加可靠，不依赖于 Watch 连接状态
- 检测时延更准确，避免了 Watch 延迟和网络问题的影响

**备选方案**：

如果 Kubernetes Watch 可用（本地有正确的 kubeconfig），监控器也会尝试通过 Watch 监听资源变更。但在当前实现中，主要依赖主动验证的方式。

## 输出结果

评估结果保存在 `results/performance/config_change_responsiveness/` 目录下，包含：

- `responsiveness_results_YYYYMMDD_HHMMSS.json`: 详细的评估结果，包括：
  - 每个变更事件的时延数据
  - 各阶段的时延统计
  - 策略状态信息
  - 错误信息（如果有）

- `config_change_responsiveness.log`: 评估过程的日志文件

## 结果分析

评估结果包含以下指标：

- **应用时延**：从开始应用配置变更到 `kubectl apply` 完成的时间
  - 包括：生成配置YAML、执行 `kubectl apply`、等待应用完成
- **检测时延**：从配置应用完成到检测到变更的时间
  - 包括：等待 Kubernetes API 更新、验证配置存在
- **解析时延**：增量配置解析的时间
  - 包括：读取配置文件、解析YAML/JSON、构建中间表示
- **依赖更新时延**：依赖图更新的时间
  - 包括：分析配置变更影响、更新依赖关系、标记受影响的服务
- **验证时延**：动态验证的时间
  - 包括：识别受影响策略、运行一致性检查、生成验证报告
- **可视化时延**：可视化刷新的时间
  - 包括：更新图数据、标记策略状态、生成可视化
- **总时延**：从配置变更应用到所有处理完成的总时间

结果按配置变更范围（3、5、10个配置项）分组统计，包括平均值、最小值、最大值。

## 注意事项

1. 确保已安装并配置好 Kubernetes 和 Istio
2. 确保目标应用（Bookinfo、Online Boutique 或 Sock Shop）已部署
3. 确保可以通过 SSH 连接到虚拟机（如果需要）
4. 确保有足够的权限执行 `kubectl apply` 操作
5. 评估过程中会修改应用的配置，评估完成后可能需要恢复原始配置

## 示例输出

```
================================================================================
开始配置变更响应性评估
================================================================================
启动配置监控器...
配置监控器已启动

================================================================================
评估范围: 3 个配置项
================================================================================

--- 迭代 1/5 ---
[事件 abc123] 开始应用 3 个配置变更
  应用配置变更 1/3: productpage
  应用配置变更 2/3: reviews
  应用配置变更 3/3: ratings
[事件 abc123] 配置变更应用完成
检测到配置变更: ['control_plane_virtualservices'] (时间: 1234567890.123)
关联变更事件 abc123 检测时延: 1.234秒
[事件 abc123] 配置变更检测时延: 1.234秒
[事件 abc123] 配置解析时延: 0.567秒
[事件 abc123] 动态验证时延: 2.345秒
  总时延: 4.146秒
    - 应用时延: 0.800秒 (配置变更应用到Kubernetes的时间)
    - 检测时延: 0.500秒 (配置变更应用到检测到的时间)
    - 解析时延: 0.567秒 (增量配置解析时间)
    - 依赖更新时延: 0.001秒 (依赖图更新时间)
    - 验证时延: 2.345秒 (动态验证时间)
    - 可视化时延: 0.010秒 (可视化刷新时间)

...

================================================================================
评估摘要
================================================================================

范围 3 个配置项:
  总时延: 平均=4.123秒, 最小=3.890秒, 最大=4.567秒
  应用时延: 平均=0.800秒
  检测时延: 平均=0.500秒
  解析时延: 平均=0.567秒
  验证时延: 平均=2.345秒

结果已保存到: results/performance/config_change_responsiveness/responsiveness_results_20250107_120000.json
```
