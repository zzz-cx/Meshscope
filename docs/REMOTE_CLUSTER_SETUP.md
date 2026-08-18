# 连接远程 Kubernetes 集群 (192.168.92.131)

当 Kubernetes Master 在远程节点 `192.168.92.131` 时，需要配置本地 kubectl 才能访问集群。

## 方法一：从 Master 复制 kubeconfig（推荐）

### 1. 复制 admin.conf 到本地

在**本地 Windows** 上执行（需要 OpenSSH 或类似工具）：

```powershell
# 创建 .kube 目录
mkdir -Force $env:USERPROFILE\.kube

# 从 Master 复制配置文件
scp root@192.168.92.131:/etc/kubernetes/admin.conf $env:USERPROFILE\.kube\config
```

### 2. 修改 server 地址（如需要）

如果 `admin.conf` 中的 server 是 `https://127.0.0.1:6443` 或集群内网地址，需改为外网地址：

```yaml
# 编辑 $env:USERPROFILE\.kube\config
# 将 clusters[].cluster.server 改为：
server: https://192.168.92.131:6443
```

### 3. 测试连接

```powershell
kubectl get nodes
kubectl get pods -A
```

---

## 方法二：使用项目脚本测试

```powershell
cd d:\python_code\istio_check\scripts
.\test_cluster_connection.ps1

# 或指定 kubeconfig 路径
.\test_cluster_connection.ps1 -KubeConfigPath "C:\path\to\admin.conf"
```

---

## 方法三：SSH 隧道（当 API 未直接暴露时）

如果 6443 端口未对外开放，可通过 SSH 建立隧道：

```powershell
# 建立隧道（保持终端运行）
ssh -L 6443:127.0.0.1:6443 root@192.168.92.131 -N
```

然后在另一个终端，将 kubeconfig 的 server 改为 `https://127.0.0.1:6443` 后使用 kubectl。

---

## 常见问题

| 问题 | 可能原因 | 解决 |
|------|----------|------|
| `connection refused` | 6443 端口未开放 | 检查防火墙，或使用 SSH 隧道 |
| `certificate signed by unknown authority` | 证书问题 | 在 kubeconfig 中设置 `insecure-skip-tls-verify: true`（仅测试用） |
| `current-context is not set` | 无有效 kubeconfig | 按方法一复制并配置 |
| `the server could not find the requested resource` | kubectl 与集群版本不匹配 | 升级/降级 kubectl 版本 |

---

## 项目中的集群配置

`consistency_checker/config.py` 中默认配置：

- **k8s_host**: 192.168.92.131  
- **k8s_port**: 6443  
- **ingress_port**: 30476（应用入口）

可通过项目根目录 `configpilot.json` 或 `--config` 参数覆盖这些配置。
