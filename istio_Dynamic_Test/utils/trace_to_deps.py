import json
import argparse
import re

def normalize_service_name(service):
    # 只保留主服务名（去掉 .default、.istio-system、.svc.cluster.local 等）
    return service.split('.')[0]

def build_deps(node, deps):
    service = normalize_service_name(node["service"])
    children = node.get("children", [])
    if service not in deps:
        deps[service] = set()
    for child in children:
        child_service = normalize_service_name(child["service"])
        if child_service != service:  # 避免自环
            deps[service].add(child_service)
        build_deps(child, deps)

def main():
    parser = argparse.ArgumentParser(description="将 trace_chain.json 转为 service_dependencies.json（仅主服务名）")
    parser.add_argument("-i", "--input", required=True, help="trace_chain.json 路径")
    parser.add_argument("-o", "--output", required=True, help="输出 service_dependencies.json 路径")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        trace = json.load(f)

    deps = {}
    build_deps(trace, deps)
    # 补齐所有出现过的服务
    all_services = set(deps.keys())
    for v in deps.values():
        all_services.update(v)
    for s in all_services:
        deps.setdefault(s, set())
    deps = {k: list(v) for k, v in deps.items()}

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(deps, f, indent=2, ensure_ascii=False)
    print(f"已生成 {args.output}")

if __name__ == "__main__":
    main()