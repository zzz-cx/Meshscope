# 流量分割验证：为何必须从应用容器发起请求

## 问题现象

reviews VirtualService 配置为 v1:20%、v2:80%（无 v3），但测试结果出现 v3 流量。

## 根因

**从 `istio-proxy` 容器发起 curl 会绕过 Istio 流量劫持**：

- Istio 通过 iptables 将**应用容器**的出站流量重定向到 sidecar
- `istio-proxy` 容器自身的流量被排除（避免劫持循环）
- 因此从 `istio-proxy` 发起的 curl 直接到达 K8s Service
- K8s 对 reviews 做负载均衡，会均衡到所有 pod（v1、v2、v3）
- VirtualService 的 20/80 分流不会生效

## 解决方案

MeshExecutor 改为从**应用容器**（如 `productpage`）发起请求：

```
kubectl exec deploy/productpage-v1 -c productpage -- curl ...
```

这样流量会：应用容器 → sidecar 劫持 → Envoy 应用 VirtualService → 仅 v1/v2 按权重分流。

## 配置校验

reviews VirtualService（`istio_config_parser/istio_monitor/istio_control_config/virtualservices/default/reviews.yaml`）：

```yaml
spec:
  hosts: [reviews]
  http:
  - route:
    - destination: {host: reviews, subset: v1}
      weight: 20
    - destination: {host: reviews, subset: v2}
      weight: 80
```

无 v3，符合预期。

## 前置条件

应用容器需安装 `curl`。若 productpage 镜像无 curl：

- **MeshExecutor 会自动回退到 istio-proxy**（会打印警告），此时会绕过 VS，结果可能含 v3
- 建议部署 sleep pod 并改用其作为请求源：`kubectl apply -f samples/sleep/sleep.yaml`，然后配置 `app_container=sleep`、`source_deploy=sleep`
