import sys
import os
# 添加项目路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# 添加 istio_Dynamic_Test 路径
dynamic_test_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if dynamic_test_root not in sys.path:
    sys.path.insert(0, dynamic_test_root)

import json
import argparse
import time
from collections import Counter
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from istio_Dynamic_Test.checker.fault_injector import FaultInjector
from istio_Dynamic_Test.recorder.envoy_log_collector import EnvoyLogCollector

class TrafficDriver:
    """
    根据测试矩阵，构造并发送流量，验证 Istio 策略。
    支持新的正交原则测试格式：
    - 正交匹配组合测试 (orthogonal_matching)
    - 多种测试策略组合 (test_strategies)
    - 全局/局部策略正交验证
    - 策略触发机制正交验证
    """
    def __init__(self, matrix_file, ssh_config=None, namespace='default'):
        try:
            with open(matrix_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.global_settings = data.get("global_settings", {})
            self.test_cases = data.get("test_cases", [])
            self.ingress_url = self.global_settings.get("ingress_url")
            
            # 如果提供了 ssh_config，创建 SSHClient；否则为 None（将自动检测环境）
            if ssh_config:
                self.ssh_client = SSHClient(**ssh_config)
            else:
                self.ssh_client = SSHClient()  # 自动检测环境
            
            # 支持多个故障注入器，针对不同服务
            self.fault_injectors = {}
            self.namespace = namespace
            self.envoy_log_collector = EnvoyLogCollector(self.ssh_client, namespace=namespace)
            self.enabled_deployments = set()  # 记录已启用 access log 的 deployment
            self.http_results = {}  # 存储HTTP测试结果
            
            if not self.ingress_url:
                print(f"错误: 在测试矩阵文件 '{matrix_file}' 中未找到 'global_settings.ingress_url'。")
                print("请使用 --ingress-url 参数重新生成测试用例。")
                exit(1)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"错误: 无法加载或解析测试矩阵文件 '{matrix_file}'。 {e}")
            print("请先运行 generator/test_case_generator.py 来生成它。")
            exit(1)

    def get_fault_injector(self, vs_name, route_host):
        """获取或创建指定服务的故障注入器"""
        key = f"{vs_name}_{route_host}"
        if key not in self.fault_injectors:
            self.fault_injectors[key] = FaultInjector(
                self.ssh_client, vs_name=vs_name, route_host=route_host, namespace=self.namespace
            )
        return self.fault_injectors[key]

    def discover_service_versions(self, service):
        """
        动态发现指定服务的所有版本
        :param service: 服务名（如 reviews, productpage）
        :return: 版本列表（如 ['v1', 'v2', 'v3']）
        """
        try:
            # 获取所有deployment，筛选出匹配服务名的
            cmd = f"kubectl get deployments -n {self.namespace} -o jsonpath='{{range .items[*]}}{{.metadata.name}}{{\"\\n\"}}{{end}}'"
            output, error = self.ssh_client.run_command(cmd)
            
            if error:
                print(f"⚠️  警告: 无法获取deployment列表: {error}")
                return []
            
            versions = []
            for deployment_name in output.strip().split('\n'):
                if deployment_name.startswith(f"{service}-"):
                    # 提取版本号（如 reviews-v1 -> v1）
                    version = deployment_name[len(service)+1:]  # 去掉服务名和连字符
                    versions.append(version)
            
            print(f"🔍 发现服务 {service} 的版本: {versions}")
            return versions
            
        except Exception as e:
            print(f"⚠️  警告: 发现服务版本时出错: {e}")
            return []

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
                # 使用skip_if_enabled=True，避免重复配置
                self.envoy_log_collector.ensure_envoy_access_log(deployment, skip_if_enabled=True)
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
            # 处理正交匹配组合测试的多个目标服务
            if case.get('test_strategies') and 'orthogonal_matching' in case.get('test_strategies', []):
                target_hosts = case.get('target_hosts', [])
                for host in target_hosts:
                    services_to_enable.add((host, None))
                    # 从 orthogonal_hits 中获取每个服务的目标版本
                    for hit in case.get('expected_outcome', {}).get('orthogonal_hits', []):
                        if hit['host'] == host:
                            services_to_enable.add((host, hit['destination']))
            else:
                # 传统单服务测试
                service = case['request_params'].get('host')
                subset = None
                if 'expected_outcome' in case and 'destination' in case['expected_outcome']:
                    subset = case['expected_outcome']['destination']
                
                # 对于权重分布测试，需要为所有相关版本启用access log
                if 'expected_outcome' in case and 'distribution' in case['expected_outcome']:
                    # 权重分布测试：为所有涉及的版本启用access log
                    distribution = case['expected_outcome']['distribution']
                    for version in distribution.keys():
                        services_to_enable.add((service, version))
                elif subset:
                    # 普通测试：只启用指定的版本
                    services_to_enable.add((service, subset))
                else:
                    # 没有指定版本的情况：动态发现所有相关版本并启用access log
                    versions = self.discover_service_versions(service)
                    if versions:
                        # 为所有发现的版本启用access log
                        for version in versions:
                            services_to_enable.add((service, version))
                    else:
                        # 如果没有发现版本，尝试启用服务本身（可能不存在，但让错误处理）
                        services_to_enable.add((service, None))
        
        print(f"🔧 预先为 {len(services_to_enable)} 个服务/版本启用 Envoy access log...")
        for service, subset in services_to_enable:
            if service:  # 确保服务名不为空
                self.enable_access_log_for_service(service, subset)
        
        for case in self.test_cases:
            self._execute_case(case)
        print("✅ 所有测试用例执行完毕。")

    def run_single_case(self, case_id):
        """
        执行单个指定的测试用例。
        """
        # 查找指定的测试用例
        target_case = None
        for case in self.test_cases:
            if case.get('case_id') == case_id:
                target_case = case
                break
        
        if not target_case:
            print(f"❌ 错误: 未找到测试用例 '{case_id}'")
            available_cases = [case.get('case_id', 'unknown') for case in self.test_cases]
            print(f"可用的测试用例: {', '.join(available_cases)}")
            return
        
        print(f"▶️  开始执行单个测试用例: {case_id}")
        
        # 只为这个用例启用访问日志
        services_to_enable = set()
        if target_case.get('test_strategies') and 'orthogonal_matching' in target_case.get('test_strategies', []):
            target_hosts = target_case.get('target_hosts', [])
            for host in target_hosts:
                services_to_enable.add((host, None))
                for hit in target_case.get('expected_outcome', {}).get('orthogonal_hits', []):
                    if hit['host'] == host:
                        services_to_enable.add((host, hit['destination']))
        else:
            service = target_case['request_params'].get('host')
            subset = None
            if 'expected_outcome' in target_case and 'destination' in target_case['expected_outcome']:
                subset = target_case['expected_outcome']['destination']
            
            if 'expected_outcome' in target_case and 'distribution' in target_case['expected_outcome']:
                distribution = target_case['expected_outcome']['distribution']
                for version in distribution.keys():
                    services_to_enable.add((service, version))
            elif subset:
                services_to_enable.add((service, subset))
            else:
                versions = self.discover_service_versions(service)
                if versions:
                    for version in versions:
                        services_to_enable.add((service, version))
                else:
                    services_to_enable.add((service, None))
        
        print(f"🔧 为 {len(services_to_enable)} 个服务/版本启用 Envoy access log...")
        for service, subset in services_to_enable:
            if service:
                self.enable_access_log_for_service(service, subset)
        
        # 执行测试用例
        self._execute_case(target_case)
        print(f"✅ 测试用例 {case_id} 执行完毕。")

    def _execute_case(self, case):
        """
        执行单个测试用例，支持新的正交原则格式。
        """
        print(f"\n[ RUNNING ] {case['case_id']}: {case['description']}")
        
        # 获取测试策略
        test_strategies = case.get('test_strategies', [])
        print(f"  🎯 测试策略: {', '.join(test_strategies)}")
        
        # 打印期望行为
        expected_outcome = case.get('expected_outcome', {})
        behaviors = expected_outcome.get('behaviors', [])
        if behaviors:
            print(f"  📋 期望行为:")
            for behavior in behaviors:
                print(f"    - {behavior}")

        # 获取所有参数
        all_params = {**case.get('request_params', {}), **case.get('load_params', {})}
        trigger_condition = all_params.get('trigger_condition')

        # 显示等价 shell 命令
        self._print_shell_command_preview(case)

        injector_used = None  # 初始化变量
        try:
            # 执行故障注入策略
            injector_used = self._handle_fault_injection(case, trigger_condition)
            
            # 执行流量发送
            if case['type'] == 'single_request':
                self._send_single_request(case)
            elif case['type'] == 'load_test':
                self._send_load_requests(case)
            else:
                print(f"[ SKIPPED ] 未知的测试类型: {case['type']}")
                return
                
        finally:
            # 在清理故障注入之前收集日志（重要：确保能捕获故障期间的日志）
            print("📋 收集故障注入期间的 Envoy access log...")
            self._collect_logs_for_case(case)
            
            # 对于包含故障注入的测试，也收集Gateway日志
            if trigger_condition and 'error' in trigger_condition.lower():
                print("📋 收集 Istio Gateway 日志...")
                self._collect_gateway_logs(case)
                
            # 测试访问日志是否能记录503错误（调试用）
            if case.get('case_id') == 'case_005':
                print("🔧 测试访问日志503记录能力...")
                self._test_simple_503_logging(case)
            
            # 清理故障注入
            if injector_used:
                print("🧹 清理故障注入配置...")
                injector_used.clear_faults()

        print(f"[  PASSED ] {case['case_id']}")

    def _handle_fault_injection(self, case, trigger_condition):
        """处理各种故障注入策略"""
        if not trigger_condition:
            return None
            
        test_strategies = case.get('test_strategies', [])
        params = case.get('request_params', {})
        target_service = params.get('host')
        
        # 获取故障注入器
        injector = self.get_fault_injector(target_service, target_service)
        
        if trigger_condition == "simulate_503_error":
            # 传统503错误注入
            match_headers = params.get('headers', {})
            match_path = params.get('path', '')
            if not match_path:
                match_path = None
            injector.inject_http_fault(error_code=503, match_headers=match_headers, match_path=match_path)
            
        elif trigger_condition == "simulate_config_fault":
            # 配置故障注入（支持abort和delay）
            fault_type = params.get('fault_type', 'abort')
            if fault_type == 'abort':
                fault_status = params.get('fault_status', 503)
                fault_percentage = params.get('fault_percentage', 100)
                injector.inject_config_fault(
                    fault_type='abort', 
                    status_code=fault_status,
                    percentage=fault_percentage
                )
            elif fault_type == 'delay':
                fault_delay = params.get('fault_delay', '1s')
                fault_percentage = params.get('fault_percentage', 100)
                injector.inject_config_fault(
                    fault_type='delay',
                    delay=fault_delay,
                    percentage=fault_percentage
                )
                
        elif trigger_condition == "simulate_high_load_with_errors":
            # 高负载+错误场景（用于熔断测试）
            # 使用上游错误方式，确保503能被记录到访问日志
            print("🔧 使用上游错误方式注入故障（确保日志记录）")
            injector.inject_upstream_error_scenario(error_percentage=80)
            
        elif trigger_condition == "simulate_config_fault_with_timeout":
            # 故障注入+超时组合测试
            fault_status = params.get('fault_status', 503)
            fault_percentage = params.get('fault_percentage', 100)
            timeout_limit = params.get('timeout_limit', '2s')
            injector.inject_fault_with_timeout(
                status_code=fault_status,
                percentage=fault_percentage,
                timeout=timeout_limit
            )
        
        return injector

    def _print_shell_command_preview(self, case):
        """打印等价 shell 命令预览"""
        logical_host = case['request_params'].get('host')
        path = case['request_params'].get('path', '')
        headers = case['request_params'].get('headers', {})
        ingress_url = self.ingress_url
        
        if case['type'] == 'single_request':
            header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
            curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} "{ingress_url}{path}"'
            print(f"  🔧 [Shell命令预览] {curl_cmd}")
            
        elif case['type'] == 'load_test':
            load_params = case.get('load_params', {})
            num_requests = load_params.get('num_requests', 1)
            concurrency = load_params.get('concurrency', 1)
            header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
            hey_cmd = f'hey -n {num_requests} -c {concurrency} -H "Host: {logical_host}" {header_str} "{ingress_url}"'
            print(f"  🔧 [Shell命令预览] {hey_cmd}")

    def _send_single_request(self, case):
        """发送单个请求，支持正交匹配组合"""
        params = case['request_params']
        
        # 处理正交匹配组合测试
        if params.get('orthogonal_matching'):
            print("  🔄 执行正交匹配组合测试...")
            target_hosts = case.get('target_hosts', [])
            orthogonal_hits = case.get('expected_outcome', {}).get('orthogonal_hits', [])
            
            for hit in orthogonal_hits:
                host = hit['host']
                destination = hit['destination'] 
                match_condition = hit['match_condition']
                
                print(f"    ➤ 测试服务 {host} -> {destination}")
                self._send_single_request_to_host(host, match_condition, case)
                time.sleep(0.2)  # 减少等待时间（从0.5秒减少到0.2秒）
        else:
            # 传统单服务请求
            logical_host = params.get('host')
            headers = params.get('headers', {})
            self._send_single_request_to_host(logical_host, {'headers': headers}, case)

    def _send_single_request_to_host(self, logical_host, match_condition, case):
        """向指定主机发送单个请求"""
        params = case['request_params']
        path = params.get('path', '')
        headers = match_condition.get('headers', {})
        
        # 处理特殊触发条件
        curl_options = []
        trigger_condition = params.get('trigger_condition')
        
        if params.get('simulate_slow_response'):
            response_delay = params.get('response_delay', '3s')
            print(f"    ⏱️  模拟慢响应: {response_delay}")
            # 这里需要在目标服务中注入延迟，简化处理
            
        # 构建curl命令
        header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
        curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {logical_host}" {header_str} {self.ingress_url}{path}'
        
        print(f"      执行: {curl_cmd}")
        start = time.time()
        output, error = self.ssh_client.run_command(curl_cmd)
        elapsed = time.time() - start
        
        http_status = output.strip()
        print(f"      HTTP状态码: {http_status}")
        print(f"      请求耗时: {elapsed:.2f} 秒")
        if error:
            print(f"      错误: {error}")
        
        # 保存HTTP结果
        self._save_http_result(case['case_id'], {
            'status_codes': {http_status: 1},
            'total_requests': 1,
            'success_rate': 100.0 if http_status.startswith('2') else 0.0,
            'avg_response_time': elapsed,
            'error_count': 1 if error else 0
        })

    def _send_load_requests(self, case):
        """发送负载测试请求，支持渐进加载和连接池测试"""
        params = case['request_params']
        load_params = case['load_params']
        logical_host = params.get('host')
        path = params.get('path', '')
        headers = params.get('headers', {})
        num_requests = load_params.get('num_requests', 1)
        concurrency = load_params.get('concurrency', 1)
        ramp_up_time = load_params.get('ramp_up_time')
        
        # 处理连接池测试
        if params.get('connection_pool_test'):
            print(f"    🔗 执行连接池压力测试...")
            
        # 处理渐进加载
        if ramp_up_time:
            print(f"    📈 渐进加载时间: {ramp_up_time}")
            # 可以分批执行，实现渐进加载效果
            
        # 对于高负载错误测试，使用权重路由方式不需要特殊header
        if case.get('request_params', {}).get('trigger_condition') == 'simulate_high_load_with_errors':
            print("🔧 使用权重路由方式进行故障注入（80%错误，20%正常）")
        
        # 构建hey命令
        header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
        hey_cmd = f'hey -n {num_requests} -c {concurrency} -H "Host: {logical_host}" {header_str} {self.ingress_url}'
        
        print(f"    执行: {hey_cmd}")
        output, error = self.ssh_client.run_command(hey_cmd)
        
        # 解析hey输出并获取结果
        hey_results = self._parse_hey_output(output)
        
        if error:
            print(f"    错误: {error}")
        
        # 保存HTTP结果
        if hey_results:
            self._save_http_result(case['case_id'], hey_results)

    def _parse_hey_output(self, output):
        """解析hey命令的输出并返回结构化数据"""
        status_codes = {}
        total_requests = 0
        avg_response_time = 0.0
        success_rate = 0.0
        
        in_status_section = False
        for line in output.splitlines():
            if line.strip().startswith('Status code distribution:'):
                in_status_section = True
                print("    📊 状态码分布:")
                continue
            if in_status_section:
                if line.strip() == '':
                    in_status_section = False
                    continue
                print("      " + line.strip())
                # 解析状态码分布，格式如: [200]     62 responses
                if '[' in line and ']' in line:
                    try:
                        code = line.split('[')[1].split(']')[0]
                        count = int(line.split('responses')[0].split()[-1])
                        status_codes[code] = count
                        total_requests += count
                    except (ValueError, IndexError):
                        pass
            if any(keyword in line for keyword in ["Requests/sec", "Failed requests", "Non-2xx responses", "Average", "Total"]):
                print("    📈 统计: " + line.strip())
                # 解析平均响应时间
                if "Average:" in line:
                    try:
                        avg_response_time = float(line.split("Average:")[1].split()[0])
                    except (ValueError, IndexError):
                        pass
        
        # 计算成功率
        success_requests = sum(count for code, count in status_codes.items() if code.startswith('2'))
        success_rate = (success_requests / total_requests * 100) if total_requests > 0 else 0.0
        
        return {
            'status_codes': status_codes,
            'total_requests': total_requests,
            'success_rate': success_rate,
            'avg_response_time': avg_response_time,
            'error_count': total_requests - success_requests
        }

    def _save_http_result(self, case_id, http_result):
        """保存HTTP测试结果到内存和文件"""
        # 保存到内存
        self.http_results[case_id] = http_result
        
        # 保存到文件
        import os
        import json
        from datetime import datetime
        
        # 创建http_results目录
        http_results_dir = "../results/http_results"
        os.makedirs(http_results_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{case_id}_http_result_{timestamp}.json"
        filepath = os.path.join(http_results_dir, filename)
        
        # 保存结果
        result_data = {
            'case_id': case_id,
            'timestamp': timestamp,
            'http_result': http_result
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)
        
        print(f"    💾 HTTP结果已保存到: {filepath}")

    def _collect_logs_for_case(self, case):
        """为测试用例收集Envoy access log"""
        case_id = case['case_id']
        
        # 处理正交匹配组合测试的多个服务
        if case.get('test_strategies') and 'orthogonal_matching' in case.get('test_strategies', []):
            target_hosts = case.get('target_hosts', [])
            orthogonal_hits = case.get('expected_outcome', {}).get('orthogonal_hits', [])
            
            for hit in orthogonal_hits:
                host = hit['host']
                destination = hit['destination']
                print(f"    📋 收集 {host}->{destination} 的日志...")
                # 对于负载测试，需要收集更多日志
                tail_lines = 200 if case.get('type') == 'load_test' else 100
                self.envoy_log_collector.collect_envoy_logs(f"{case_id}_{host}", host, subset=destination, tail_lines=tail_lines)
        else:
            # 传统单服务日志收集
            service = case['request_params'].get('host')
            subset = None
            if 'expected_outcome' in case and 'destination' in case['expected_outcome']:
                subset = case['expected_outcome']['destination']
            # 对于负载测试（特别是熔断测试），需要收集更多日志
            tail_lines = 200 if case.get('type') == 'load_test' else 100
            self.envoy_log_collector.collect_envoy_logs(case_id, service, subset=subset, tail_lines=tail_lines)

    def _collect_gateway_logs(self, case):
        """收集Istio Gateway的访问日志，可能包含故障注入的503错误"""
        case_id = case['case_id']
        try:
            print("    📋 收集 Istio Gateway 日志...")
            # 收集istio-proxy (gateway) 的日志
            tail_lines = 200 if case.get('type') == 'load_test' else 100
            self.envoy_log_collector.collect_gateway_logs(case_id, tail_lines=tail_lines)
        except Exception as e:
            print(f"    ⚠️ 警告: 无法收集Gateway日志: {e}")

    def _test_simple_503_logging(self, case):
        """测试访问日志是否能记录503错误（通过请求不存在的host）"""
        case_id = case['case_id']
        try:
            print("    🔧 发送测试请求到不存在的服务...")
            # 使用不存在的host触发cluster not found (503)
            test_url = f"{self.ingress_url}/"
            test_headers = {"Host": "not-exist.default.svc.cluster.local"}
            
            cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: not-exist.default.svc.cluster.local" {test_url}'
            output, error = self.ssh_client.run_command(cmd)
            
            if output and '503' in output:
                print(f"    ✅ 测试请求返回503: {output}")
            else:
                print(f"    ⚠️ 测试请求返回: {output} (期望503)")
            
            # 等待日志写入（减少等待时间）
            time.sleep(1)  # 从2秒减少到1秒
            
            # 收集测试后的日志
            print("    📋 收集测试503后的日志...")
            service = case['request_params'].get('host')
            tail_lines = 50  # 只收集最近的日志
            self.envoy_log_collector.collect_envoy_logs(f"{case_id}_test503", service, tail_lines=tail_lines)
            
        except Exception as e:
            print(f"    ⚠️ 警告: 503测试失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="Istio 测试执行驱动 (自动检测环境：K8s 或 SSH)")
    parser.add_argument("-i", "--input", default="output_matrix.json", help="输入的测试矩阵文件路径")
    parser.add_argument("--ssh-host", default=None, help="SSH 主机地址 (可选，如果不在 K8s 环境中则需要)")
    parser.add_argument("--ssh-user", default=None, help="SSH 用户名 (可选)")
    parser.add_argument("--ssh-password", default=None, help="SSH 密码 (可选)")
    parser.add_argument("--ssh-key", default=None, help="SSH 私钥路径 (可选)")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH 端口 (默认22)")
    parser.add_argument("--namespace", default="default", help="K8s 命名空间")
    parser.add_argument("--single-case", default=None, help="只运行指定的单个测试用例 (例如: case_005)")
    args = parser.parse_args()

    # 如果提供了 SSH 配置，使用它；否则为 None（将自动检测环境）
    ssh_config = None
    if args.ssh_host:
        ssh_config = {
            'hostname': args.ssh_host,
            'username': args.ssh_user,
            'password': args.ssh_password,
            'key_filename': args.ssh_key,
            'port': args.ssh_port
        }

    driver = TrafficDriver(args.input, ssh_config, namespace=args.namespace)
    
    if args.single_case:
        print(f"🎯 只运行单个测试用例: {args.single_case}")
        driver.run_single_case(args.single_case)
    else:
        driver.run()

if __name__ == "__main__":
    main() 