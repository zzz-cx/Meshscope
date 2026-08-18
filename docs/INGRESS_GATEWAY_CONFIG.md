# Ingress Gateway 配置采集指南

用于对 **frontend-ingress**、**bookinfo** 等 Gateway 绑定项做一致性校验，需先采集 istio-ingressgateway 的 config_dump。

## 方式一：kubectl-exec（推荐）

**前提**：已安装 kubectl 且能访问 Kubernetes 集群。

```bash
# 从项目根目录执行
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method kubectl-exec
```

或直接运行脚本：

```bash
python istio_config_parser/istio_monitor/export_ingress_gateway_config.py --method kubectl-exec
```

输出目录默认：`istio_config_parser/istio_monitor/istio_ingress_config/`（routes.json、clusters.json、listeners.json）

## 方式二：istioctl

**前提**：已安装 istioctl 且能访问集群。

```bash
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config --method istioctl
```

## 方式三：from-yaml（无集群访问时）

若无法直接访问集群，请从有集群权限的环境导出 config_dump，再在本地解析：

```bash
# 在集群中执行（导出 config_dump）
kubectl exec -n istio-system deploy/istio-ingressgateway -- curl -s localhost:15000/config_dump > proxy_config_all.yaml

# 将 proxy_config_all.yaml 拷贝到本地后执行
python -m istio_config_parser.istio_monitor.export_ingress_gateway_config \
  --method from-yaml \
  --yaml-path <path_to_proxy_config_all.yaml>
```

**注意**：必须使用 **istio-ingressgateway** Pod 的 config_dump，不能用 sidecar 的 proxy_config，否则 Gateway 绑定项校验无效。

## 使用 main_parser 校验

采集完成后，运行：

```bash
python -m istio_config_parser.main_parser --mode unified --summary --details \
  --ingress-plane-dir istio_config_parser/istio_monitor/istio_ingress_config
```

此时 frontend-ingress、bookinfo 等 Gateway 绑定配置将参与一致性校验。

## 常见问题

| 问题 | 排查 |
|------|------|
| 未找到 Ingress Gateway Pod | `kubectl get pods -n istio-system -l app=istio-ingressgateway` |
| kubectl 命令失败 | 确认 kubectl 在 PATH 中，Windows 下可在 PowerShell 中执行 |
| 使用 sidecar 的 proxy_config | 校验结果仍为「无法校验」，需使用 ingress gateway 的 config_dump |
