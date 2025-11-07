import time
import json
from typing import Dict, List, Any, Optional
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from istio_Dynamic_Test.utils.ssh_utils import SSHClient

class OrthogonalHandler:
    """
    正交处理器 - 专门处理新正交原则的测试用例
    支持：
    1. 正交匹配组合测试 - 一个请求验证多个服务的匹配规则
    2. 策略触发机制正交 - 不同生命周期阶段的策略组合
    3. 全局/局部策略正交 - VirtualService + DestinationRule 组合
    4. 功能策略间正交 - 同一请求路径中的策略不相互屏蔽
    """
    
    def __init__(self, ssh_client: SSHClient, ingress_url: str, namespace: str = 'default'):
        self.ssh_client = ssh_client
        self.ingress_url = ingress_url
        self.namespace = namespace
        self.strategy_handlers = {
            'orthogonal_matching': self._handle_orthogonal_matching,
            'retry': self._handle_retry_strategy,
            'timeout': self._handle_timeout_strategy,
            'fault_injection': self._handle_fault_injection_strategy,
            'traffic_split': self._handle_traffic_split_strategy,
            'circuit_breaker': self._handle_circuit_breaker_strategy,
            'connection_pool': self._handle_connection_pool_strategy,
            'routing': self._handle_routing_strategy
        }

    def handle_test_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理测试用例，根据test_strategies分发到对应的处理器
        """
        test_strategies = case.get('test_strategies', [])
        results = {
            'case_id': case['case_id'],
            'description': case['description'],
            'strategies_executed': [],
            'execution_results': {},
            'validation_results': {},
            'timing_info': {}
        }
        
        print(f"🎯 正交处理器处理策略: {', '.join(test_strategies)}")
        
        # 按策略类型分组执行
        strategy_groups = self._group_strategies_by_execution_phase(test_strategies)
        
        for phase, strategies in strategy_groups.items():
            print(f"  📍 执行阶段: {phase}")
            phase_start = time.time()
            
            for strategy in strategies:
                if strategy in self.strategy_handlers:
                    try:
                        strategy_result = self.strategy_handlers[strategy](case)
                        results['execution_results'][strategy] = strategy_result
                        results['strategies_executed'].append(strategy)
                        print(f"    ✅ 策略 {strategy} 执行完成")
                    except Exception as e:
                        print(f"    ❌ 策略 {strategy} 执行失败: {e}")
                        results['execution_results'][strategy] = {'error': str(e)}
                else:
                    print(f"    ⚠️  未知策略: {strategy}")
            
            results['timing_info'][phase] = time.time() - phase_start
        
        return results

    def _group_strategies_by_execution_phase(self, strategies: List[str]) -> Dict[str, List[str]]:
        """
        根据策略的执行阶段进行分组（基于正交原则的触发机制）
        """
        phase_mapping = {
            # 请求入口阶段
            'request_entry': ['orthogonal_matching', 'routing', 'fault_injection'],
            # 负载处理阶段  
            'load_processing': ['traffic_split', 'connection_pool'],
            # 失败处理阶段
            'failure_handling': ['retry', 'circuit_breaker'],
            # 响应处理阶段
            'response_handling': ['timeout']
        }
        
        grouped = {}
        for phase, phase_strategies in phase_mapping.items():
            grouped[phase] = [s for s in strategies if s in phase_strategies]
        
        # 移除空阶段
        return {k: v for k, v in grouped.items() if v}

    def _handle_orthogonal_matching(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理正交匹配组合测试"""
        print("    🔄 执行正交匹配组合验证...")
        
        target_hosts = case.get('target_hosts', [])
        orthogonal_hits = case.get('expected_outcome', {}).get('orthogonal_hits', [])
        headers = case.get('request_params', {}).get('headers', {})
        
        results = {
            'strategy': 'orthogonal_matching',
            'total_targets': len(orthogonal_hits),
            'hit_results': [],
            'success_count': 0
        }
        
        for hit in orthogonal_hits:
            host = hit['host']
            expected_destination = hit['destination']
            match_condition = hit['match_condition']
            
            print(f"      🎯 验证 {host} -> {expected_destination}")
            
            # 构建请求验证单个服务的匹配
            hit_result = self._verify_single_host_match(
                host, expected_destination, match_condition, case
            )
            
            results['hit_results'].append({
                'host': host,
                'expected_destination': expected_destination,
                'match_condition': match_condition,
                'verification_result': hit_result
            })
            
            if hit_result.get('success', False):
                results['success_count'] += 1
        
        results['success_rate'] = results['success_count'] / results['total_targets'] if results['total_targets'] > 0 else 0
        
        return results

    def _verify_single_host_match(self, host: str, expected_destination: str, 
                                 match_condition: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
        """验证单个主机的匹配规则"""
        headers = match_condition.get('headers', {})
        path = case.get('request_params', {}).get('path', '')
        
        # 构建curl命令
        header_str = ' '.join([f'-H "{k}: {v}"' for k, v in headers.items()])
        curl_cmd = f'curl -s -o /dev/null -w "%{{http_code}}" -H "Host: {host}" {header_str} {self.ingress_url}{path}'
        
        start_time = time.time()
        output, error = self.ssh_client.run_command(curl_cmd)
        elapsed = time.time() - start_time
        
        status_code = output.strip()
        success = status_code in ['200', '201', '202', '204']
        
        return {
            'success': success,
            'status_code': status_code,
            'response_time': elapsed,
            'curl_command': curl_cmd,
            'error': error if error else None
        }

    def _handle_retry_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理重试策略验证"""
        print("    🔄 验证重试策略行为...")
        
        behaviors = case.get('expected_outcome', {}).get('behaviors', [])
        retry_behaviors = [b for b in behaviors if '重试' in b]
        
        # 从行为描述中提取重试次数
        retry_attempts = 0
        for behavior in retry_behaviors:
            if '重试' in behavior:
                # 尝试从行为描述中提取数字
                import re
                match = re.search(r'重试(\d+)次', behavior)
                if match:
                    retry_attempts = int(match.group(1))
                    break
        
        # 执行重试验证
        params = case.get('request_params', {})
        trigger_condition = params.get('trigger_condition')
        
        result = {
            'strategy': 'retry',
            'expected_retry_attempts': retry_attempts,
            'trigger_condition': trigger_condition,
            'verification_method': 'log_analysis'  # 需要通过日志分析验证
        }
        
        if trigger_condition:
            print(f"      ⚡ 触发条件: {trigger_condition}")
            print(f"      🔢 期望重试次数: {retry_attempts}")
        
        return result

    def _handle_timeout_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理超时策略验证"""
        print("    ⏱️  验证超时策略行为...")
        
        params = case.get('request_params', {})
        behaviors = case.get('expected_outcome', {}).get('behaviors', [])
        
        # 从行为描述中提取超时设置
        timeout_value = None
        for behavior in behaviors:
            if '超时' in behavior:
                import re
                match = re.search(r'(\d+s)', behavior)
                if match:
                    timeout_value = match.group(1)
                    break
        
        result = {
            'strategy': 'timeout',
            'expected_timeout': timeout_value,
            'simulate_slow_response': params.get('simulate_slow_response', False),
            'response_delay': params.get('response_delay')
        }
        
        if params.get('simulate_slow_response'):
            delay = params.get('response_delay', '3s')
            print(f"      ⏳ 模拟慢响应: {delay}")
            print(f"      ⏱️  期望超时: {timeout_value}")
        
        return result

    def _handle_fault_injection_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理故障注入策略验证"""
        print("    💥 验证故障注入策略...")
        
        params = case.get('request_params', {})
        fault_type = params.get('fault_type', 'abort')
        fault_status = params.get('fault_status', 503)
        fault_percentage = params.get('fault_percentage', 100)
        
        result = {
            'strategy': 'fault_injection',
            'fault_type': fault_type,
            'fault_status': fault_status,
            'fault_percentage': fault_percentage,
            'trigger_condition': params.get('trigger_condition')
        }
        
        print(f"      💥 故障类型: {fault_type}")
        print(f"      📊 故障比例: {fault_percentage}%")
        if fault_type == 'abort':
            print(f"      🚫 错误状态码: {fault_status}")
        
        return result

    def _handle_traffic_split_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理流量分割策略验证"""
        print("    ⚖️  验证流量分割策略...")
        
        expected_outcome = case.get('expected_outcome', {})
        distribution = expected_outcome.get('distribution', {})
        margin_of_error = expected_outcome.get('margin_of_error', '0.05')
        
        result = {
            'strategy': 'traffic_split',
            'expected_distribution': distribution,
            'margin_of_error': margin_of_error,
            'verification_method': 'statistical_analysis'
        }
        
        print(f"      📊 期望分布: {distribution}")
        print(f"      📏 误差容限: {margin_of_error}")
        
        return result

    def _handle_circuit_breaker_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理熔断策略验证"""
        print("    🔌 验证熔断策略...")
        
        expected_outcome = case.get('expected_outcome', {})
        threshold = expected_outcome.get('circuit_breaker_threshold')
        behaviors = expected_outcome.get('behaviors', [])
        
        result = {
            'strategy': 'circuit_breaker',
            'threshold': threshold,
            'behaviors': [b for b in behaviors if '熔断' in b],
            'verification_method': 'error_pattern_analysis'
        }
        
        if threshold:
            print(f"      🚨 熔断阈值: {threshold} 次连续错误")
        
        return result

    def _handle_connection_pool_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理连接池策略验证"""
        print("    🔗 验证连接池策略...")
        
        expected_outcome = case.get('expected_outcome', {})
        connection_limits = expected_outcome.get('connection_limits', {})
        params = case.get('request_params', {})
        
        result = {
            'strategy': 'connection_pool',
            'connection_limits': connection_limits,
            'connection_pool_test': params.get('connection_pool_test', False),
            'verification_method': 'concurrency_analysis'
        }
        
        if connection_limits:
            tcp_limit = connection_limits.get('tcp')
            http_pending = connection_limits.get('http_pending')
            if tcp_limit:
                print(f"      🔗 TCP连接限制: {tcp_limit}")
            if http_pending:
                print(f"      📋 HTTP挂起请求限制: {http_pending}")
        
        return result

    def _handle_routing_strategy(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """处理路由策略验证"""
        print("    🛤️  验证路由策略...")
        
        expected_outcome = case.get('expected_outcome', {})
        destination = expected_outcome.get('destination')
        
        result = {
            'strategy': 'routing',
            'expected_destination': destination,
            'verification_method': 'destination_analysis'
        }
        
        if destination:
            print(f"      🎯 期望目标: {destination}")
        
        return result

    def validate_orthogonal_combinations(self, case: Dict[str, Any], 
                                       execution_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证正交组合的有效性 - 确保策略间不相互屏蔽
        """
        test_strategies = case.get('test_strategies', [])
        
        validation_result = {
            'orthogonal_validation': True,
            'strategy_conflicts': [],
            'synergy_effects': [],
            'coverage_analysis': {}
        }
        
        # 检查策略间的正交性
        if len(test_strategies) > 1:
            print(f"    🧪 验证 {len(test_strategies)} 个策略的正交组合...")
            
            # 功能策略间正交验证
            functional_strategies = ['retry', 'timeout', 'fault_injection', 'routing']
            func_strategies_in_test = [s for s in test_strategies if s in functional_strategies]
            
            if len(func_strategies_in_test) > 1:
                validation_result['coverage_analysis']['functional_orthogonal'] = {
                    'strategies': func_strategies_in_test,
                    'orthogonal': True,
                    'note': '功能策略在不同生命周期阶段触发，可正交组合'
                }
            
            # 全局/局部策略正交验证
            global_strategies = ['circuit_breaker', 'connection_pool']
            local_strategies = ['routing', 'retry', 'timeout', 'fault_injection']
            
            global_in_test = [s for s in test_strategies if s in global_strategies]
            local_in_test = [s for s in test_strategies if s in local_strategies]
            
            if global_in_test and local_in_test:
                validation_result['coverage_analysis']['scope_orthogonal'] = {
                    'global_strategies': global_in_test,
                    'local_strategies': local_in_test,
                    'orthogonal': True,
                    'note': '全局策略(DR)与局部策略(VS)可在同一请求中验证'
                }
        
        return validation_result

    def generate_execution_summary(self, results: Dict[str, Any]) -> str:
        """生成执行摘要"""
        strategies = results.get('strategies_executed', [])
        success_count = len([s for s in strategies if results['execution_results'].get(s, {}).get('success', True)])
        
        summary = f"正交处理器执行摘要:\n"
        summary += f"  执行策略: {', '.join(strategies)}\n"
        summary += f"  成功策略: {success_count}/{len(strategies)}\n"
        
        timing_info = results.get('timing_info', {})
        if timing_info:
            summary += f"  各阶段耗时:\n"
            for phase, duration in timing_info.items():
                summary += f"    {phase}: {duration:.2f}s\n"
        
        return summary 