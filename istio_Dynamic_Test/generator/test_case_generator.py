import json
import argparse
import os

class TestCaseGenerator:
    """
    解析具体的 Istio 配置文件，生成精简的正交测试用例矩阵：
    - 路由/匹配只生成正向用例
    - 重试/熔断只生成 simulate_503_error 用例（重试用例为下游服务注入故障）
    - 分流只生成一组负载测试，并根据连接池/限流/熔断配置自动调整并发
    """
    def __init__(self, config_path, service_deps_path=None):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.test_cases = []
        self.case_id_counter = 1
        self.service_deps = {}
        if service_deps_path:
            if os.path.exists(service_deps_path):
                with open(service_deps_path, 'r', encoding='utf-8') as f:
                    self.service_deps = json.load(f)

    def _generate_case_id(self):
        case_id = f"case_{self.case_id_counter:03d}"
        self.case_id_counter += 1
        return case_id

    def _calculate_requests_for_split(self, weights, z=1.96, e=0.1):
        """根据权重，使用统计学公式估算测试分流所需的最少请求数。"""
        if not weights or sum(weights) == 0:
            return 100 # Default
        
        total_weight = sum(weights)
        max_var = 0
        for w in weights:
            p = w / total_weight
            var = p * (1 - p)
            if var > max_var:
                max_var = var
        
        num = (z * z * max_var) / (e * e)
        return int(num + 1)

    def _get_dest_rule_for_host(self, host):
        for dr in self.config.get("destinationRules", []):
            dr_host = dr["spec"].get("host")
            if dr_host == host or dr_host == f"{host}.default.svc.cluster.local":
                return dr["spec"]
        return None

    def _has_conn_limit_or_outlier(self, dr_spec):
        if not dr_spec:
            return False
        tp = dr_spec.get("trafficPolicy", {})
        # 检查 outlierDetection
        if "outlierDetection" in tp:
            return True
        # 检查 connectionPool
        cp = tp.get("connectionPool", {})
        http = cp.get("http", {})
        if cp.get("maxConnections") or http.get("http1MaxPendingRequests") or http.get("maxRequestsPerConnection"):
            return True
        return False

    def _any_host_has_conn_limit_or_outlier(self):
        for dr in self.config.get("destinationRules", []):
            tp = dr["spec"].get("trafficPolicy", {})
            if "outlierDetection" in tp:
                return True
            cp = tp.get("connectionPool", {})
            http = cp.get("http", {})
            if cp.get("maxConnections") or http.get("http1MaxPendingRequests") or http.get("maxRequestsPerConnection"):
                return True
        return False

    def generate(self):
        # 只要有一个host存在熔断或限流，所有分流用例都低并发
        self.low_concurrency = self._any_host_has_conn_limit_or_outlier()
        self._parse_virtual_services()
        self._parse_destination_rules()
        return self.test_cases

    def _parse_virtual_services(self):
        for vs in self.config.get("virtualServices", []):
            host = vs["spec"]["hosts"][0]
            for route_block in vs["spec"]["http"]:
                # 只生成正向匹配用例
                if "match" in route_block:
                    params = {}
                    header_match = route_block["match"][0].get("headers", {})
                    if header_match:
                        key, rule = list(header_match.items())[0]
                        val = rule["exact"]
                        params["headers"] = {key: val}
                    uri_match = route_block["match"][0].get("uri", {})
                    if uri_match:
                        prefix = uri_match.get("prefix", "")
                        params["path"] = prefix
                    self.test_cases.append({
                        "case_id": self._generate_case_id(),
                        "description": f"正向匹配路由测试 for host '{host}'",
                        "type": "single_request",
                        "request_params": {"host": host, **params},
                        "expected_outcome": {
                            "destination": route_block["route"][0]["destination"]["subset"],
                            "note": "只验证正向命中路由。"
                        },
                        "source_service": host
                    })
                    # 如果有重试策略，生成 simulate_503_error 用例（为下游服务注入故障）
                    if "retries" in route_block:
                        downstreams = self.service_deps.get(host, [])
                        if downstreams:
                            downstream = downstreams[0]
                            self.test_cases.append({
                                "case_id": self._generate_case_id(),
                                "description": f"重试策略-故障注入测试 for host '{host}', inject fault to '{downstream}'",
                                "type": "single_request",
                                "request_params": {"host": host, **params, "trigger_condition": "simulate_503_error", "inject_fault_to": downstream},
                                "expected_outcome": {
                                    "destination": route_block["route"][0]["destination"]["subset"],
                                    "note": "验证重试时的故障注入行为。"
                                },
                                "source_service": host
                            })
                        else:
                            # 没有下游服务时，兼容原有逻辑
                            self.test_cases.append({
                                "case_id": self._generate_case_id(),
                                "description": f"重试策略-故障注入测试 for host '{host}' (无下游服务)",
                                "type": "single_request",
                                "request_params": {"host": host, **params, "trigger_condition": "simulate_503_error"},
                                "expected_outcome": {
                                    "destination": route_block["route"][0]["destination"]["subset"],
                                    "note": "验证重试时的故障注入行为。"
                                },
                                "source_service": host
                            })
                # 分流用例
                elif "route" in route_block and len(route_block["route"]) > 1:
                    weights = [r.get("weight", 0) for r in route_block["route"]]
                    num_requests = self._calculate_requests_for_split(weights)
                    concurrency = 1 if self.low_concurrency else 10
                    distribution = {
                        r["destination"]["subset"]: f"approx {r['weight']/sum(weights):.2f}"
                        for r in route_block["route"]
                    }
                    self.test_cases.append({
                        "case_id": self._generate_case_id(),
                        "description": f"分流权重测试 for host '{host}'",
                        "type": "load_test",
                        "request_params": {"host": host, "path": "/"},
                        "load_params": {"num_requests": num_requests, "concurrency": concurrency},
                        "expected_outcome": {
                            "distribution": distribution,
                            "margin_of_error": "0.05"
                        },
                        "source_service": host
                    })
                elif "retries" in route_block:
                    downstreams = self.service_deps.get(host, [])
                    if downstreams:
                        downstream = downstreams[0]
                        self.test_cases.append({
                            "case_id": self._generate_case_id(),
                            "description": f"重试策略-故障注入测试 for host '{host}' (default route), inject fault to '{downstream}'",
                            "type": "single_request",
                            "request_params": {"host": host, "trigger_condition": "simulate_503_error", "inject_fault_to": downstream},
                            "expected_outcome": {
                                "destination": route_block["route"][0]["destination"]["subset"],
                                "note": "验证重试时的故障注入行为（无 match 默认路由）。"
                            },
                            "source_service": host
                        })
                    else:
                        self.test_cases.append({
                            "case_id": self._generate_case_id(),
                            "description": f"重试策略-故障注入测试 for host '{host}' (default route, 无下游服务)",
                            "type": "single_request",
                            "request_params": {"host": host, "trigger_condition": "simulate_503_error"},
                            "expected_outcome": {
                                "destination": route_block["route"][0]["destination"]["subset"],
                                "note": "验证重试时的故障注入行为（无 match 默认路由）。"
                            },
                            "source_service": host
                        })

    def _parse_destination_rules(self):
        for dr in self.config.get("destinationRules", []):
            if "outlierDetection" in dr["spec"].get("trafficPolicy", {}):
                policy = dr["spec"]["trafficPolicy"]["outlierDetection"]
                # 只生成 simulate_503_error 用例
                self.test_cases.append({
                    "case_id": self._generate_case_id(),
                    "description": f"熔断策略-故障注入测试 for host '{dr['spec']['host']}'",
                    "type": "load_test",
                    "request_params": {"host": dr['spec']['host'], "trigger_condition": "simulate_503_error"},
                    "load_params": {
                        "concurrency": policy.get("consecutiveGatewayErrors", 5) * 2,
                        "num_requests": policy.get("consecutiveGatewayErrors", 5) * 10
                    },
                    "expected_outcome": {
                        "behavior": "验证熔断时的故障注入与恢复行为。"
                    }
                })

def main():
    parser = argparse.ArgumentParser(description="精简版 Istio 测试用例生成器（自动适配并发限制）")
    script_dir = os.path.dirname(os.path.realpath(__file__))
    default_input_path = os.path.join(script_dir, 'istio_config.json')
    parser.add_argument("-i", "--input", default=default_input_path, help="输入的 Istio 配置文件路径")
    parser.add_argument("-o", "--output", default="output_matrix.json", help="输出的测试矩阵文件路径")
    parser.add_argument("--ingress-url", required=True, help="集群入口服务的URL (例如: http://productpage:9080)")
    parser.add_argument("--service-deps", required=True, help="服务依赖关系的json文件路径（由 trace_utils 生成）")
    args = parser.parse_args()

    generator = TestCaseGenerator(args.input, args.service_deps)
    test_cases = generator.generate()

    output_data = {
        "global_settings": {
            "ingress_url": args.ingress_url
        },
        "test_cases": test_cases
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"✅ 成功生成 {len(test_cases)} 个测试用例，已保存到 {args.output}")

if __name__ == "__main__":
    main()