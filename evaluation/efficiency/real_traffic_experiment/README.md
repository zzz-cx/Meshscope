# 真实流量：正交 vs 穷举功能分支覆盖实验

## 目标

在现有 K8s + Istio 集群上：

1. 新建命名空间（每个规模独立：`meshscope-exp-n10` …）
2. 部署递增服务：`N ∈ {10,20,30,40,50}`（`meshscope-svc-XXXX`，v1/v2）
3. 按功能单元注入递增配置：路由 / 分流 / 熔断 / 重试 / 限流（默认功能数 = N）
4. 生成两类用例并打真实流量：
   - **exhaustive**：覆盖每个功能的全部功能分支
   - **orthogonal**：按功能类型做正交/稀疏取样，用例更少

## 快速冒烟（推荐先跑 N=10）

```bash
cd /root/configPilot/istio_check/evaluation/efficiency/real_traffic_experiment

# 各节点预拉镜像（国内用 DaoCloud）
# master 上：
ctr -n k8s.io images pull docker.m.daocloud.io/library/nginx:1.25-alpine
ctr -n k8s.io images tag docker.m.daocloud.io/library/nginx:1.25-alpine docker.io/library/nginx:1.25-alpine
# worker 同上

python3 run_experiment.py --only 10 --output-dir ./results/runs
```

## 完整阶梯

```bash
python3 run_experiment.py --scales 10,20,30,40,50 --output-dir ./results/runs
```

## 分步执行

```bash
python3 deploy_services.py --namespace meshscope-exp-n10 --services 10
python3 inject_features.py --namespace meshscope-exp-n10 --services 10 --features 10 \
  --catalog results/feature_catalog.json
python3 generate_cases.py --catalog results/feature_catalog.json --out-dir results/cases
python3 run_traffic.py --cases results/cases/exhaustive_cases.json --output results/exh.json
python3 run_traffic.py --cases results/cases/orthogonal_cases.json --output results/ortho.json
```

## 输出

`results/runs/comparison_report.json` 含各规模：

- 用例数（穷举 vs 正交）
- 生成期分支覆盖率
- 真实流量成功率 / 运行时分支覆盖 / 耗时

## 资源提示

N=50 时约 100 个业务 Pod + sidecar，请确认节点资源与镜像已预热。

## 路由注意

入口 VS（`meshscope-ingress`）对 `/s{i}/` 使用 **exact** 匹配，避免 prefix 抢走功能路径（如 `/s5/route-1/`）。功能 VS 绑定 Gateway `meshscope-gw`，hosts=`*`。

最新完整结果：`results/runs_full/comparison_report.json`
