import json
import itertools
import argparse
from math import sqrt
import os

class TestCaseGenerator:
    """
    解析具体的 Istio 配置文件，生成覆盖多种策略的正交测试用例矩阵。
    """
    def __init__(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.test_cases = []
        self.case_id_counter = 1

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

    def generate(self):
        """主生成逻辑，调用各个解析器。"""
        self._parse_virtual_services()
        self._parse_destination_rules()
        return self.test_cases

    def _parse_virtual_services(self):
        for vs in self.config.get("virtualServices", []):
            host = vs["spec"]["hosts"][0]
            for route_block in vs["spec"]["http"]:
                # 场景一：处理带 `match` 条件的路由规则 (正交单一请求)
                if "match" in route_block:
                    self._generate_matching_cases(host, route_block)
                
                # 场景二：处理带 `weight` 的分流规则 (多次请求)
                elif "route" in route_block and len(route_block["route"]) > 1:
                    self._generate_traffic_shifting_case(host, route_block)

    def _generate_matching_cases(self, host, route_block):
        """为带 match 的规则生成正交测试用例。"""
        dimensions = {}
        # 提取 header 匹配维度 (正向 + 反向)
        header_match = route_block["match"][0].get("headers", {})
        if header_match:
            key, rule = list(header_match.items())[0]
            val = rule["exact"]
            dimensions["headers"] = [{key: val}, {key: f"not-{val}"}] # 正向与反向

        # 提取 uri 匹配维度 (正向 + 反向)
        uri_match = route_block["match"][0].get("uri", {})
        if uri_match:
            prefix = uri_match["prefix"]
            dimensions["path"] = [f"{prefix}", ""]

        # 提取重试策略维度
        if "retries" in route_block:
            dimensions["trigger_condition"] = ["normal_response", "simulate_503_error"]

        # 生成正交组合
        dim_names = dimensions.keys()
        for combo in itertools.product(*dimensions.values()):
            params = dict(zip(dim_names, combo))
            self.test_cases.append({
                "case_id": self._generate_case_id(),
                "description": f"Test routing for host '{host}' with params: {params}",
                "type": "single_request",
                "request_params": { "host": host, **params },
                "expected_outcome": {
                    "destination": route_block["route"][0]["destination"]["subset"],
                    "note": "Verify response source and retry behavior if applicable."
                }
            })

    def _generate_traffic_shifting_case(self, host, route_block):
        """为权重分流生成一个多次请求的测试用例。"""
        weights = [r.get("weight", 0) for r in route_block["route"]]
        num_requests = self._calculate_requests_for_split(weights)
        
        distribution = {
            r["destination"]["subset"]: f"approx {r['weight']/sum(weights):.2f}"
            for r in route_block["route"]
        }

        self.test_cases.append({
            "case_id": self._generate_case_id(),
            "description": f"Verify {weights} traffic split for host '{host}'",
            "type": "load_test",
            "request_params": {"host": host, "path": "/"},
            "load_params": {"num_requests": num_requests, "concurrency": 10},
            "expected_outcome": {
                "distribution": distribution,
                "margin_of_error": "0.05"
            }
        })
        
    def _parse_destination_rules(self):
        for dr in self.config.get("destinationRules", []):
            # 场景三：处理熔断策略 (多次请求)
            if "outlierDetection" in dr["spec"].get("trafficPolicy", {}):
                policy = dr["spec"]["trafficPolicy"]["outlierDetection"]
                self.test_cases.append({
                    "case_id": self._generate_case_id(),
                    "description": f"Verify circuit breaker for host '{dr['spec']['host']}'",
                    "type": "load_test",
                    "request_params": {"host": dr['spec']['host']},
                    "load_params": {
                        "concurrency": policy.get("consecutiveGatewayErrors", 5) * 2,
                        "num_requests": policy.get("consecutiveGatewayErrors", 5) * 10,
                        "trigger_condition": "simulate_503_error"
                    },
                    "expected_outcome": {
                        "behavior": "Observe upstream_rq_pending_overflow and successful requests count."
                    }
                })

def main():
    parser = argparse.ArgumentParser(description="智能 Istio 测试用例生成器")
    
    # Construct the default path for the config file relative to the script's location.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    default_input_path = os.path.join(script_dir, 'istio_config.json')

    parser.add_argument("-i", "--input", default=default_input_path, help="输入的 Istio 配置文件路径")
    parser.add_argument("-o", "--output", default="output_matrix.json", help="输出的测试矩阵文件路径")
    parser.add_argument("--ingress-url", required=True, help="集群入口服务的URL (例如: http://productpage:9080)")
    args = parser.parse_args()

    generator = TestCaseGenerator(args.input)
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