import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import argparse
import time
from collections import Counter
from utils.ssh_utils import SSHClient
from checker.fault_injector import FaultInjector
from recorder.envoy_log_collector import EnvoyLogCollector

class TrafficDriver:
    """
    根据测试矩阵，构造并发送流量，验证 Istio 策略。
    支持通过 SSH 在集群主机上执行命令。
    用例执行后自动采集 Envoy access log。
    """
    def __init__(self, matrix_file, ssh_config, namespace='default'):
        try:
            with open(matrix_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.global_settings = data.get("global_settings", {})
            self.test_cases = data.get("test_cases", [])
            self.ingress_url = self.global_settings.get("ingress_url")
            self.ssh_client = SSHClient(**ssh_config)
            self.injector = FaultInjector(self.ssh_client,vs_name='reviews', route_host='reviews')
            self.namespace = namespace
            self.envoy_log_collector = EnvoyLogCollector(self.ssh_client, namespace=namespace)
            self.enabled_deployments = set()  # 记录已启用 access log 的 deployment
            if not self.ingress_url:
                print(f"错误: 在测试矩阵文件 '{matrix_file}' 中未找到 'global_settings.ingress_url'。")
                print("请使用 --ingress-url 参数重新生成测试用例。")
                exit(1)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"错误: 无法加载或解析测试矩阵文件 '{matrix_file}'。 {e}")
            print("请先运行 generator/test_case_generator.py 来生成它。")
            exit(1)

    def enable_access_log_for_service(self, service, subset=None):
        """
        为指定服务/版本启用 Envoy access log。
        :param service: 服务名（如 reviews）
        :param subset: 版本（如 v2），可为 None
        """
        if subset:
            deployment = f"{service}-{subset}"
        else:
            deployment = service
            
        if deployment not in self.enabled_deployments:
            print(f"🔧 为 deployment/{deployment} 启用 Envoy access log...")
            try:
                self.envoy_log_collector.ensure_envoy_access_log(deployment)
                self.enabled_deployments.add(deployment)
                print(f"✅ deployment/{deployment} 的 Envoy access log 已启用")
            except Exception as e:
                print(f"⚠️  警告: 无法为 deployment/{deployment} 启用 access log: {e}")
        else:
            print(f"ℹ️  deployment/{deployment} 的 Envoy access log 已经启用过了")

    def run(self):
        """
        执行所有测试用例。
        """
        print(f"▶️  开始执行 {len(self.test_cases)} 个测试用例...")
        
        # 预先分析所有用例，提前启用需要的服务的 access log
        services_to_enable = set()
        for case in self.test_cases:
            service = case['request_params'].get('host')
            subset = None
            if 'expected_outcome' in case and 'destination' in case['expected_outcome']:
                subset = case['expected_outcome']['destination']
            services_to_enable.add((service, subset))
        
        print(f"🔧 预先为 {len(services_to_enable)} 个服务/版本启用 Envoy access log...")
        for service, subset in services_to_enable:
            self.enable_access_log_for_service(service, subset)
        
        for case in self.test_cases:
            self._execute_case(case)
        print("✅ 所有测试用例执行完毕。")

    def _execute_case(self, case):
        """
        执行单个测试用例。
        """
        print(f"\n[ RUNNING ] {case['case_id']}: {case['description']}")
        
        # 检查是否需要注入故障
        all_params = {**case.get('request_params', {}), **case.get('load_params', {})}
        trigger_condition = all_params.get('trigger_condition')
        target_service = case['request_params'].get('host')

        # === 打印等价 shell 命令 ===
        logical_host = case['request_params'].get('host')
        path = case['request_params'].get('path', '')
        headers = case['request_params'].get('headers', {})
        ingress_url = self.ingress_url
        if case['type'] == 'single_request':
            header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
            curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} "{ingress_url}{path}"'
            print(f"[Shell命令预览] {curl_cmd}")
        elif case['type'] == 'load_test':
            load_params = case.get('load_params', {})
            num_requests = load_params.get('num_requests', 1)
            concurrency = load_params.get('concurrency', 1)
            hey_cmd = f'hey -n {num_requests} -c {concurrency} -H "Host: {logical_host}" "{ingress_url}"'
            print(f"[Shell命令预览] {hey_cmd}")
        # =========================

        try:
            if trigger_condition == "simulate_503_error":
                match_headers = case['request_params'].get('headers', {})
                match_path = case['request_params'].get('path', '')
                if not match_path:
                    match_path = None
                self.injector.inject_http_fault(error_code=503, match_headers=match_headers, match_path=match_path)

            if case['type'] == 'single_request':
                self._send_single_request(case)
            elif case['type'] == 'load_test':
                self._send_load_requests(case)
            else:
                print(f"[ SKIPPED ] 未知的测试类型: {case['type']}")
                return
        finally:
            if trigger_condition == "simulate_503_error":
                self.injector.clear_faults()

        # === 用例执行后自动收集 Envoy access log ===
        service = case['request_params'].get('host')
        case_id = case['case_id']
        subset = None
        if 'expected_outcome' in case and 'destination' in case['expected_outcome']:
            subset = case['expected_outcome']['destination']
        self.envoy_log_collector.collect_envoy_logs(case_id, service, subset=subset)
        print(f"[  PASSED ] {case['case_id']}")

    def _send_single_request(self, case):
        params = case['request_params']
        logical_host = params.get('host')
        ingress_url = self.ingress_url
        path = params.get('path', '')
        headers = params.get('headers', {})
        header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
        # 直接在主机上执行 curl
        curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} {ingress_url}{path}'
        print(f"  - 在主机上执行: {curl_cmd}")
        start = time.time()
        output, error = self.ssh_client.run_command(curl_cmd)
        elapsed = time.time() - start
        print(f"  - HTTP状态码: {output.strip()}")
        print(f"  - 请求耗时: {elapsed:.2f} 秒")
        if error:
            print(f"  - 错误: {error}")

    def _send_load_requests(self, case):
        params = case['request_params']
        load_params = case['load_params']
        logical_host = params.get('host')
        ingress_url = self.ingress_url
        path = params.get('path', '')
        num_requests = load_params.get('num_requests', 1)
        concurrency = load_params.get('concurrency', 1)
        hey_cmd = f'hey -n {num_requests} -c {concurrency} -H "Host: {logical_host}" {ingress_url}'
        print(f"  - 在主机上执行: {hey_cmd}")
        output, error = self.ssh_client.run_command(hey_cmd)
        # 解析 hey 输出，统计状态码分布
        in_status_section = False
        for line in output.splitlines():
            if line.strip().startswith('Status code distribution:'):
                in_status_section = True
                print("  - 状态码分布:")
                continue
            if in_status_section:
                if line.strip() == '':
                    in_status_section = False
                    continue
                print("    " + line.strip())
            if "Requests/sec" in line or "Failed requests" in line or "Non-2xx responses" in line:
                print("  - 统计: " + line)
        if error:
            print(f"  - 错误: {error}")

def main():
    parser = argparse.ArgumentParser(description="Istio 测试执行驱动 (SSH 远程+mesh内流量模式)")
    parser.add_argument("-i", "--input", default="output_matrix.json", help="输入的测试矩阵文件路径")
    parser.add_argument("--ssh-host", required=True, help="SSH 主机地址")
    parser.add_argument("--ssh-user", required=True, help="SSH 用户名")
    parser.add_argument("--ssh-password", default=None, help="SSH 密码 (可选)")
    parser.add_argument("--ssh-key", default=None, help="SSH 私钥路径 (可选)")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH 端口 (默认22)")
    parser.add_argument("--namespace", default="default", help="K8s 命名空间")
    args = parser.parse_args()

    ssh_config = {
        'hostname': args.ssh_host,
        'username': args.ssh_user,
        'password': args.ssh_password,
        'key_filename': args.ssh_key,
        'port': args.ssh_port
    }

    driver = TrafficDriver(args.input, ssh_config, namespace=args.namespace)
    driver.run()

if __name__ == "__main__":
    main() 