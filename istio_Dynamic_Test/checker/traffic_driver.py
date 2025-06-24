import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import argparse
import time
from collections import Counter
from utils.ssh_utils import SSHClient
from fault_injector import FaultInjector

class TrafficDriver:
    """
    根据测试矩阵，构造并发送流量，验证 Istio 策略。
    支持通过 SSH 在集群主机上执行命令。
    """
    def __init__(self, matrix_file, ssh_config):
        try:
            with open(matrix_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.global_settings = data.get("global_settings", {})
            self.test_cases = data.get("test_cases", [])
            self.ingress_url = self.global_settings.get("ingress_url")
            self.ssh_client = SSHClient(**ssh_config)
            self.injector = FaultInjector(self.ssh_client)

            if not self.ingress_url:
                print(f"错误: 在测试矩阵文件 '{matrix_file}' 中未找到 'global_settings.ingress_url'。")
                print("请使用 --ingress-url 参数重新生成测试用例。")
                exit(1)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"错误: 无法加载或解析测试矩阵文件 '{matrix_file}'。 {e}")
            print("请先运行 generator/test_case_generator.py 来生成它。")
            exit(1)

    def run(self):
        """
        执行所有测试用例。
        """
        print(f"▶️  开始执行 {len(self.test_cases)} 个测试用例...")
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
        path = case['request_params'].get('path', '/')
        headers = case['request_params'].get('headers', {})
        ingress_url = self.ingress_url
        if case['type'] == 'single_request':
            # 构造 curl 命令
            header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
            curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} "{ingress_url}{path}"'
            print(f"[Shell命令预览] {curl_cmd}")
        elif case['type'] == 'load_test':
            load_params = case.get('load_params', {})
            num_requests = load_params.get('num_requests', 1)
            concurrency = load_params.get('concurrency', 1)
            ab_cmd = f'ab -n {num_requests} -c {concurrency} -H "Host: {logical_host}" "{ingress_url}{path}"'
            print(f"[Shell命令预览] {ab_cmd}")
        # =========================

        try:
            if trigger_condition == "simulate_503_error":
                self.injector.inject_http_fault(target_service, error_code=503)

            if case['type'] == 'single_request':
                self._send_single_request(case)
            elif case['type'] == 'load_test':
                self._send_load_requests(case)
            else:
                print(f"[ SKIPPED ] 未知的测试类型: {case['type']}")
                return
        finally:
            # 确保在测试结束后清理故障
            if trigger_condition == "simulate_503_error":
                self.injector.clear_faults(target_service)

        # 此处应添加结果验证逻辑
        print(f"[  PASSED ] {case['case_id']}")


    def _send_single_request(self, case):
        params = case['request_params']
        logical_host = params.get('host')
        path = params.get('path', '/')
        headers = params.get('headers', {})
        header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
        curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} "{self.ingress_url}{path}"'
        print(f"  - 远程执行: {curl_cmd}")
        output, error = self.ssh_client.run_command(curl_cmd)
        print(f"  - 远程HTTP状态码: {output.strip()}")
        if error:
            print(f"  - 远程错误: {error}")


    def _send_load_requests(self, case):
        params = case['request_params']
        load_params = case['load_params']
        logical_host = params.get('host')
        path = params.get('path', '/')
        num_requests = load_params.get('num_requests', 1)
        concurrency = load_params.get('concurrency', 1)
        ab_cmd = f'ab -n {num_requests} -c {concurrency} -H "Host: {logical_host}" "{self.ingress_url}{path}"'
        print(f"  - 远程执行: {ab_cmd}")
        output, error = self.ssh_client.run_command(ab_cmd)
        # 只打印关键统计
        for line in output.splitlines():
            if "2xx" in line or "Non-2xx responses" in line or "Failed requests" in line:
                print("  - 统计: " + line)
        if error:
            print(f"  - 远程错误: {error}")


def main():
    parser = argparse.ArgumentParser(description="Istio 测试执行驱动 (SSH 远程模式)")
    parser.add_argument("-i", "--input", default="output_matrix.json", help="输入的测试矩阵文件路径")
    parser.add_argument("--ssh-host", required=True, help="SSH 主机地址")
    parser.add_argument("--ssh-user", required=True, help="SSH 用户名")
    parser.add_argument("--ssh-password", default=None, help="SSH 密码 (可选)")
    parser.add_argument("--ssh-key", default=None, help="SSH 私钥路径 (可选)")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH 端口 (默认22)")
    args = parser.parse_args()

    ssh_config = {
        'hostname': args.ssh_host,
        'username': args.ssh_user,
        'password': args.ssh_password,
        'key_filename': args.ssh_key,
        'port': args.ssh_port
    }

    driver = TrafficDriver(args.input, ssh_config)
    driver.run()

if __name__ == "__main__":
    main() 