import json
import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    yaml = None

class TestCaseGenerator:
    """
    解析具体的 Istio 配置文件，生成精简的正交测试用例矩阵：
    - 路由/匹配只生成正向用例
    - 重试/熔断只生成 simulate_503_error 用例（重试用例为下游服务注入故障）
    - 分流只生成一组负载测试，并根据连接池/限流/熔断配置自动调整并发
    """
    def __init__(self, config_path, service_deps_path=None, namespace="default"):
        self.config_path = config_path
        self.namespace = namespace
        if os.path.isdir(config_path):
            if yaml is None:
                raise RuntimeError("PyYAML 未安装，无法从目录加载配置，请先安装 PyYAML。")
            self.config = self._load_from_directory(config_path)
        else:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        self._filter_config_by_namespace()
        if 'enabled_policies' not in self.config:
            self.config['enabled_policies'] = self._infer_enabled_policies(self.config)
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

    def _destination_label(self, destination: Dict[str, Any]) -> str:
        """根据目标配置提取标识（优先subset，其次host）"""
        subset = destination.get("subset")
        if subset:
            return subset
        host = destination.get("host")
        if host:
            return host
        return "default"

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

    def _extract_route_params(self, route_block):
        """提取路由匹配参数"""
        params = {}
        if "match" in route_block:
            header_match = route_block["match"][0].get("headers", {})
            if header_match:
                key, rule = list(header_match.items())[0]
                # 支持多种匹配类型：exact, prefix, regex
                if "exact" in rule:
                    val = rule["exact"]
                elif "prefix" in rule:
                    val = rule["prefix"] + "-test"  # 为prefix添加后缀确保匹配
                elif "regex" in rule:
                    # 为regex提供一个可能的匹配值（简化处理）
                    val = "test-value"
                else:
                    # 默认处理其他情况
                    val = str(list(rule.values())[0])
                params["headers"] = {key: val}
            uri_match = route_block["match"][0].get("uri", {})
            if uri_match:
                prefix = uri_match.get("prefix", "")
                params["path"] = prefix
        return params

    def _get_policy_combination(self, route_block):
        """基于四种正交原则获取策略组合（正交设计核心）"""
        policies = {
            "has_retries": "retries" in route_block,
            "has_timeout": "timeout" in route_block,
            "has_fault": "fault" in route_block,
            "retry_attempts": route_block.get("retries", {}).get("attempts", 0),
            "timeout_value": route_block.get("timeout", ""),
            "fault_config": route_block.get("fault", {})
        }
        
        # 新增：四种正交原则分析
        orthogonal_analysis = {
            # 1. 匹配条件维度正交 - 已在 _generate_orthogonal_matching_test 中实现
            "matching_orthogonal": True,
            
            # 2. 功能策略间正交 - 同一请求路径中的策略不相互屏蔽
            "functional_orthogonal": {
                "route_match": True,  # 路由匹配
                "retry_policy": policies["has_retries"],    # 重试策略
                "timeout_policy": policies["has_timeout"],  # 超时策略  
                "fault_injection": policies["has_fault"]    # 故障注入
            },
            
            # 3. 全局/局部策略正交 - VirtualService(局部) + DestinationRule(全局)
            "scope_orthogonal": {
                "local_policies": ["routing", "retry", "timeout", "fault"],
                "global_policies": ["circuit_breaker", "connection_pool"],
                "can_combine": True  # 可在一个请求中验证
            },
            
            # 4. 策略触发机制正交 - 不同生命周期阶段的策略可组合
            "trigger_orthogonal": {
                "request_entry": ["routing", "fault_injection"],      # 请求入口触发
                "failure_triggered": ["retry", "circuit_breaker"],    # 失败时触发  
                "load_triggered": ["connection_pool", "rate_limit"],  # 负载时触发
                "response_triggered": ["timeout"]                     # 响应超时触发
            }
        }
        
        policies["orthogonal_analysis"] = orthogonal_analysis
        return policies

    def _find_vs_policies_for_host(self, host):
        """查找特定host的VirtualService策略，用于全局/局部正交组合"""
        vs_policies = {
            "has_retries": False,
            "has_timeout": False, 
            "has_fault": False,
            "has_routing": False,
            "retry_config": {},
            "timeout_config": "",
            "fault_config": {},
            "routing_rules": []
        }
        
        for vs in self.config.get("virtualServices", []):
            spec = vs.get("spec", {})
            hosts = spec.get("hosts") or []
            if host in hosts:
                for route_block in spec.get("http", []):
                    if "retries" in route_block:
                        vs_policies["has_retries"] = True
                        vs_policies["retry_config"] = route_block["retries"]
                    if "timeout" in route_block:
                        vs_policies["has_timeout"] = True
                        vs_policies["timeout_config"] = route_block["timeout"]
                    if "fault" in route_block:
                        vs_policies["has_fault"] = True
                        vs_policies["fault_config"] = route_block["fault"]
                    if "match" in route_block:
                        vs_policies["has_routing"] = True
                        vs_policies["routing_rules"].append(route_block["match"])
                        
        return vs_policies

    def _generate_orthogonal_test_case(self, host, route_block, params, case_type="basic"):
        """生成正交组合测试用例"""
        policies = self._get_policy_combination(route_block)
        
        # 基础路由测试
        if case_type == "basic":
            return {
                "case_id": self._generate_case_id(),
                "description": f"正向匹配路由测试 for host '{host}'",
                "type": "single_request",
                "request_params": {"host": host, **params},
                "expected_outcome": {
                    "destination": self._destination_label(route_block["route"][0]["destination"]),
                    "note": "验证正向命中路由。"
                },
                "source_service": host
            }
        
        # 正交组合策略测试 - 基于四种正交原则
        elif case_type == "orthogonal_combination":
            test_strategies = []
            request_params = {"host": host, **params}
            expected_behaviors = []
            
            # 获取正交分析
            orthogonal = policies.get("orthogonal_analysis", {})
            
            # 策略1: 功能策略间正交 - 故障注入 + 重试 + 超时组合
            # 原理：故障注入(请求入口触发) + 重试(失败触发) + 超时(响应触发) 在不同生命周期阶段，可正交组合
            if policies["has_fault"] and policies["has_retries"] and policies["has_timeout"]:
                fault_config = policies["fault_config"]
                if "abort" in fault_config:
                    request_params["trigger_condition"] = "simulate_config_fault_with_timeout"
                    request_params["fault_type"] = "abort"
                    request_params["fault_status"] = fault_config["abort"]["httpStatus"]
                    request_params["fault_percentage"] = fault_config["abort"]["percent"]
                    request_params["timeout_limit"] = policies["timeout_value"]
                    test_strategies.extend(["fault_injection", "retry", "timeout"])
                    expected_behaviors.extend([
                        f"故障注入：{fault_config['abort']['httpStatus']}错误({fault_config['abort']['percent']}%)",
                        f"重试机制：失败时重试{policies['retry_attempts']}次",
                        f"超时控制：请求不超过{policies['timeout_value']}"
                    ])
            
            # 策略2: 超时 + 重试组合测试（响应触发 + 失败触发）
            elif policies["has_timeout"] and policies["has_retries"]:
                request_params["simulate_slow_response"] = True
                request_params["response_delay"] = "3s"  # 超过timeout的延迟
                test_strategies.extend(["timeout", "retry"])
                expected_behaviors.extend([
                    f"超时触发：请求超过{policies['timeout_value']}",
                    f"重试机制：超时后重试{policies['retry_attempts']}次"
                ])
            
            # 策略3: 故障注入 + 重试组合测试（入口触发 + 失败触发）
            elif policies["has_fault"] and policies["has_retries"]:
                fault_config = policies["fault_config"]
                if "abort" in fault_config:
                    request_params["trigger_condition"] = "simulate_config_fault"
                    request_params["fault_type"] = "abort"
                    request_params["fault_status"] = fault_config["abort"]["httpStatus"]
                    request_params["fault_percentage"] = fault_config["abort"]["percent"]
                    test_strategies.extend(["fault_injection", "retry"])
                    expected_behaviors.extend([
                        f"故障注入：{fault_config['abort']['httpStatus']}错误({fault_config['abort']['percent']}%)",
                        f"重试机制：故障后重试{policies['retry_attempts']}次"
                    ])
                elif "delay" in fault_config:
                    request_params["trigger_condition"] = "simulate_config_fault"
                    request_params["fault_type"] = "delay"
                    request_params["fault_delay"] = fault_config["delay"]["fixedDelay"]
                    request_params["fault_percentage"] = fault_config["delay"]["percent"]
                    test_strategies.extend(["delay_injection", "retry"])
                    expected_behaviors.extend([
                        f"延迟注入：{fault_config['delay']['fixedDelay']}延迟({fault_config['delay']['percent']}%)",
                        f"重试机制：延迟后重试{policies['retry_attempts']}次"
                    ])
            
            # 策略4: 仅超时测试（响应触发）
            elif policies["has_timeout"]:
                request_params["simulate_slow_response"] = True
                request_params["response_delay"] = "3s"
                test_strategies.append("timeout")
                expected_behaviors.append(f"验证{policies['timeout_value']}超时设置")
            
            # 策略5: 仅故障注入测试（入口触发）
            elif policies["has_fault"]:
                fault_config = policies["fault_config"]
                if "abort" in fault_config:
                    request_params["trigger_condition"] = "simulate_config_fault"
                    request_params["fault_type"] = "abort"
                    request_params["fault_status"] = fault_config["abort"]["httpStatus"]
                    request_params["fault_percentage"] = fault_config["abort"]["percent"]
                    test_strategies.append("fault_injection")
                    expected_behaviors.append(f"验证配置故障注入({fault_config['abort']['httpStatus']}, {fault_config['abort']['percent']}%)")
            
            # 策略6: 仅重试测试（失败触发）
            elif policies["has_retries"]:
                downstreams = self.service_deps.get(host, [])
                if downstreams:
                    request_params["trigger_condition"] = "simulate_503_error"
                    request_params["inject_fault_to"] = downstreams[0]
                    test_strategies.append("retry")
                    expected_behaviors.append(f"下游故障重试{policies['retry_attempts']}次")
                else:
                    request_params["trigger_condition"] = "simulate_503_error"
                    test_strategies.append("retry")
                    expected_behaviors.append(f"服务故障重试{policies['retry_attempts']}次")
            
            if test_strategies:
                return {
                    "case_id": self._generate_case_id(),
                    "description": f"正交组合策略测试({'+'.join(test_strategies)}) for host '{host}'",
                    "type": "single_request",
                    "request_params": request_params,
                    "expected_outcome": {
                        "destination": self._destination_label(route_block["route"][0]["destination"]),
                        "behaviors": expected_behaviors,
                        "note": f"验证{'+'.join(test_strategies)}策略组合行为。"
                    },
                    "source_service": host,
                    "test_strategies": test_strategies
                }
        
        return None

    def _group_routes_by_destination(self):
        """按目标版本分组路由规则，实现匹配条件的正交组合"""
        destination_groups = {}
        
        for vs in self.config.get("virtualServices", []):
            spec = vs.get("spec")
            if not spec:
                continue
            hosts = spec.get("hosts") or []
            if not hosts:
                continue
            host = hosts[0]
            for route_block in spec.get("http", []):
                if "match" in route_block and "route" in route_block:
                    destination = self._destination_label(route_block["route"][0]["destination"])
                    
                    if destination not in destination_groups:
                        destination_groups[destination] = []
                    
                    destination_groups[destination].append({
                        "host": host,
                        "route_block": route_block,
                        "params": self._extract_route_params(route_block)
                    })
        
        return destination_groups

    def _generate_orthogonal_matching_test(self, destination, route_group):
        """生成匹配条件的正交组合测试用例"""
        if len(route_group) < 2:
            return None
        
        # 构建正交匹配测试
        combined_params = {}
        expected_hits = []
        test_description_parts = []
        
        for route_info in route_group:
            host = route_info["host"]
            params = route_info["params"]
            
            # 合并请求参数
            if "headers" in params:
                if "headers" not in combined_params:
                    combined_params["headers"] = {}
                combined_params["headers"].update(params["headers"])
            
            if "path" in params:
                combined_params["path"] = params["path"]
            
            # 记录期望命中的服务和目标
            expected_hits.append({
                "host": host,
                "destination": destination,
                "match_condition": params
            })
            
            # 构建描述
            match_desc = ""
            if "headers" in params:
                header_key = list(params["headers"].keys())[0]
                header_val = list(params["headers"].values())[0]
                match_desc = f"{header_key}={header_val}"
            if "path" in params:
                match_desc += f" path={params['path']}" if match_desc else f"path={params['path']}"
            
            test_description_parts.append(f"{host}({match_desc})")
        
        return {
            "case_id": self._generate_case_id(),
            "description": f"正交匹配组合测试({'+'.join(test_description_parts)}) -> {destination}",
            "type": "single_request",
            "request_params": {
                "orthogonal_matching": True,
                **combined_params
            },
            "expected_outcome": {
                "orthogonal_hits": expected_hits,
                "note": f"一个用例验证多个服务到{destination}的匹配规则"
            },
            "test_strategies": ["orthogonal_matching"],
            "target_hosts": [route_info["host"] for route_info in route_group]
        }

    def _parse_virtual_services(self):
        # 首先按目标版本分组，寻找正交匹配机会
        destination_groups = self._group_routes_by_destination()
        
        # 生成正交匹配测试用例
        for destination, route_group in destination_groups.items():
            orthogonal_matching_case = self._generate_orthogonal_matching_test(destination, route_group)
            if orthogonal_matching_case:
                self.test_cases.append(orthogonal_matching_case)
                # 标记已处理的路由，避免重复生成
                for route_info in route_group:
                    route_info["processed"] = True
        
        # 处理剩余的路由规则
        for vs in self.config.get("virtualServices", []):
            spec = vs.get("spec")
            if not spec:
                continue
            hosts = spec.get("hosts") or []
            if not hosts:
                continue
            host = hosts[0]
            for route_block in spec.get("http", []):
                params = self._extract_route_params(route_block)
                
                # 检查是否已被正交匹配处理
                already_processed = False
                if "match" in route_block and "route" in route_block:
                    destination = self._destination_label(route_block["route"][0]["destination"])
                    for route_group in destination_groups.values():
                        for route_info in route_group:
                            if (route_info["host"] == host and 
                                route_info.get("processed") and
                                route_info["route_block"] == route_block):
                                already_processed = True
                                break
                
                # 1. 基础路由测试（如果有match规则且未被正交处理）
                if "match" in route_block and not already_processed:
                    basic_case = self._generate_orthogonal_test_case(host, route_block, params, "basic")
                    if basic_case:
                        self.test_cases.append(basic_case)
                
                # 2. 分流权重测试（优先检查，避免重复）
                if "route" in route_block and len(route_block["route"]) > 1:
                    weights = [r.get("weight", 0) for r in route_block["route"]]
                    num_requests = self._calculate_requests_for_split(weights)
                    concurrency = 1 if self.low_concurrency else 10
                    total_weight = sum(weights) if sum(weights) else 0
                    distribution = {}
                    split_descriptions = []
                    for route in route_block["route"]:
                        dest_label = self._destination_label(route["destination"])
                        weight_value = route.get("weight", 0)
                        ratio = (weight_value / total_weight) if total_weight else 0
                        distribution[dest_label] = f"approx {ratio:.2f}"
                        split_descriptions.append(f"{dest_label}({weight_value}%)")

                    # 正交组合：分流 + 故障注入（一个用例同时验证两个功能）
                    load_params = {"host": host, "path": "/"}
                    test_strategies = ["traffic_split"]
                    expected_behaviors = [f"验证流量分割：{', '.join(split_descriptions)}"]
                    
                    if "fault" in route_block:
                        fault_config = route_block["fault"]
                        if "abort" in fault_config:
                            load_params["trigger_condition"] = "simulate_config_fault"
                            load_params["fault_type"] = "abort"
                            load_params["fault_status"] = fault_config["abort"]["httpStatus"]
                            load_params["fault_percentage"] = fault_config["abort"]["percent"]
                            test_strategies.append("fault_injection")
                            expected_behaviors.append(f"验证故障注入：{fault_config['abort']['httpStatus']}错误({fault_config['abort']['percent']}%)")
                        elif "delay" in fault_config:
                            load_params["trigger_condition"] = "simulate_config_fault"
                            load_params["fault_type"] = "delay"
                            load_params["fault_delay"] = fault_config["delay"]["fixedDelay"]
                            load_params["fault_percentage"] = fault_config["delay"]["percent"]
                            test_strategies.append("fault_injection")
                            expected_behaviors.append(f"验证延迟注入：{fault_config['delay']['fixedDelay']}({fault_config['delay']['percent']}%)")
                    
                    test_description = f"正交组合测试({'+'.join(test_strategies)}) for host '{host}'"
                    
                    self.test_cases.append({
                        "case_id": self._generate_case_id(),
                        "description": test_description,
                        "type": "load_test",
                        "request_params": load_params,
                        "load_params": {"num_requests": num_requests, "concurrency": concurrency},
                        "expected_outcome": {
                            "distribution": distribution,
                            "margin_of_error": "0.05",
                            "behaviors": expected_behaviors
                        },
                        "source_service": host,
                        "test_strategies": test_strategies
                    })
                
                # 3. 其他正交组合策略测试（仅针对非分流场景）
                elif not ("route" in route_block and len(route_block["route"]) > 1):
                    orthogonal_case = self._generate_orthogonal_test_case(host, route_block, params, "orthogonal_combination")
                    if orthogonal_case:
                        self.test_cases.append(orthogonal_case)

    def _generate_destination_rule_orthogonal_tests(self, dr_spec):
        """基于四种正交原则为DestinationRule生成组合测试"""
        host = dr_spec.get("host")
        if not host:
            return []
        traffic_policy = dr_spec.get("trafficPolicy", {})
        
        # 获取全局策略组合
        has_outlier = "outlierDetection" in traffic_policy
        has_conn_pool = "connectionPool" in traffic_policy
        
        outlier_config = traffic_policy.get("outlierDetection", {}) if has_outlier else {}
        conn_pool_config = traffic_policy.get("connectionPool", {}) if has_conn_pool else {}
        
        # 查找对应的VirtualService局部策略，实现全局/局部策略正交
        vs_policies = self._find_vs_policies_for_host(host)
        
        test_cases = []
        
        # 正交组合1: 全局/局部策略正交 - 熔断+连接池(全局) + 重试+路由(局部)
        if has_outlier and has_conn_pool:
            consecutive_errors = outlier_config.get("consecutiveErrors", outlier_config.get("consecutive5xxErrors", 5))
            tcp_max = conn_pool_config.get("tcp", {}).get("maxConnections", 10)
            http_pending = conn_pool_config.get("http", {}).get("http1MaxPendingRequests", 5)
            
            # 构建请求参数 - 结合VirtualService策略
            request_params = {
                "host": host,
                "trigger_condition": "simulate_high_load_with_errors",
                "connection_pool_test": True
            }
            
            test_strategies = ["circuit_breaker", "connection_pool"]
            expected_behaviors = [
                f"连接池限制：最大TCP连接{tcp_max}，HTTP挂起请求{http_pending}",
                f"熔断触发：{consecutive_errors}次连续错误后熔断"
            ]
            
            # 如果VirtualService有重试策略，则组合测试（全局+局部正交）
            if vs_policies["has_retries"]:
                retry_attempts = vs_policies["retry_config"].get("attempts", 3)
                request_params["enable_vs_retry"] = True
                test_strategies.append("retry")
                expected_behaviors.append(f"重试机制：失败时重试{retry_attempts}次")
            
            # 如果VirtualService有路由匹配，添加路由验证
            if vs_policies["has_routing"]:
                test_strategies.append("routing")
                expected_behaviors.append("路由匹配：验证请求正确路由到目标版本")
            
            description_suffix = "+".join(test_strategies)
            
            test_cases.append({
                "case_id": self._generate_case_id(),
                "description": f"全局/局部正交组合测试({description_suffix}) for host '{host}'",
                "type": "load_test",
                "request_params": request_params,
                "load_params": {
                    "concurrency": max(tcp_max * 2, 20),  # 超过连接池限制
                    "num_requests": consecutive_errors * 15,  # 足够触发熔断
                    "ramp_up_time": "10s"
                },
                "expected_outcome": {
                    "behaviors": expected_behaviors,
                    "circuit_breaker_threshold": consecutive_errors,
                    "connection_limits": {"tcp": tcp_max, "http_pending": http_pending},
                    "orthogonal_note": "全局策略(DR)与局部策略(VS)的正交验证"
                },
                "source_service": host,
                "test_strategies": test_strategies
            })
        
        # 正交组合2: 仅熔断测试
        elif has_outlier:
            consecutive_errors = outlier_config.get("consecutiveErrors", outlier_config.get("consecutive5xxErrors", 5))
            interval = outlier_config.get("interval", "30s")
            
            test_cases.append({
                "case_id": self._generate_case_id(),
                "description": f"正交组合策略测试(熔断) for host '{host}'",
                "type": "load_test",
                "request_params": {
                    "host": host,
                    "trigger_condition": "simulate_503_error"
                },
                "load_params": {
                    "concurrency": 10,
                    "num_requests": consecutive_errors * 12,
                    "error_rate": 0.8  # 高错误率触发熔断
                },
                "expected_outcome": {
                    "behaviors": [
                        f"熔断触发：{consecutive_errors}次连续错误",
                        f"检测间隔：{interval}",
                        "验证熔断策略的故障注入与恢复行为"
                    ],
                    "circuit_breaker_threshold": consecutive_errors
                },
                "source_service": host,
                "test_strategies": ["circuit_breaker"]
            })
        
        # 正交组合3: 仅连接池测试
        elif has_conn_pool:
            tcp_max = conn_pool_config.get("tcp", {}).get("maxConnections", 10)
            http_pending = conn_pool_config.get("http", {}).get("http1MaxPendingRequests", 5)
            
            test_cases.append({
                "case_id": self._generate_case_id(),
                "description": f"正交组合策略测试(连接池) for host '{host}'",
                "type": "load_test",
                "request_params": {
                    "host": host,
                    "connection_pool_test": True,
                    "simulate_slow_response": True,
                    "response_delay": "2s"  # 慢响应增加连接池压力
                },
                "load_params": {
                    "concurrency": tcp_max * 3,  # 超过连接池限制
                    "num_requests": 100,
                    "sustained_load": True
                },
                "expected_outcome": {
                    "behaviors": [
                        f"连接池限制：最大TCP连接{tcp_max}",
                        f"HTTP挂起请求限制：{http_pending}",
                        "验证连接池限制的有效性"
                    ],
                    "connection_limits": {"tcp": tcp_max, "http_pending": http_pending}
                },
                "source_service": host,
                "test_strategies": ["connection_pool"]
            })
        
        return test_cases

    def _parse_destination_rules(self):
        for dr in self.config.get("destinationRules", []):
            dr_spec = dr.get("spec")
            if not dr_spec:
                continue
            orthogonal_tests = self._generate_destination_rule_orthogonal_tests(dr_spec)
            self.test_cases.extend(orthogonal_tests)

    # ---------------------------- 新增辅助方法 ----------------------------

    def _load_from_directory(self, base_dir: str) -> Dict[str, Any]:
        """从控制平面配置目录加载并组装生成器所需的结构。"""
        base_path = Path(base_dir)
        config: Dict[str, Any] = {
            "description": f"Generated from: {str(base_path)}",
            "virtualServices": [],
            "destinationRules": [],
            "envoyFilters": [],
            "serviceEntries": [],
            "gateways": []
        }

        resource_map = {
            'virtualservices': 'virtualServices',
            'destinationrules': 'destinationRules',
            'envoyfilters': 'envoyFilters',
            'serviceentries': 'serviceEntries',
            'gateways': 'gateways'
        }

        for resource_dir, key in resource_map.items():
            dir_path = base_path / resource_dir
            if not dir_path.exists():
                continue
            for ext in ("*.yaml", "*.yml", "*.json"):
                for file_path in dir_path.rglob(ext):
                    documents = self._load_resource_file(file_path)
                    if documents:
                        config[key].extend(documents)

        # 删除空资源项，保持结构简洁
        for key in list(config.keys()):
            if isinstance(config[key], list) and not config[key]:
                config.pop(key)

        config["enabled_policies"] = self._infer_enabled_policies(config)
        return config

    def _load_resource_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """加载单个资源文件，支持 YAML / JSON，多文档时逐个读取。"""
        documents: List[Dict[str, Any]] = []
        suffix = file_path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            with file_path.open('r', encoding='utf-8') as f:
                for doc in yaml.safe_load_all(f):
                    if doc:
                        documents.append(doc)
        elif suffix == ".json":
            with file_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    documents.extend([item for item in data if item])
                elif isinstance(data, dict):
                    documents.append(data)
        return documents

    def _infer_enabled_policies(self, config: Dict[str, Any]) -> Dict[str, bool]:
        """根据配置推断启用的策略类型。"""
        enabled = {
            "routing": False,
            "retry": False,
            "circuit_breaker": False,
            "rate_limit": False,
            "fault_injection": False
        }

        for vs in config.get("virtualServices", []):
            spec = vs.get("spec", {})
            http_rules = spec.get("http", [])
            if http_rules:
                enabled["routing"] = True
            for rule in http_rules:
                if "retries" in rule:
                    enabled["retry"] = True
                if "fault" in rule:
                    enabled["fault_injection"] = True

        for dr in config.get("destinationRules", []):
            spec = dr.get("spec", {})
            traffic_policy = spec.get("trafficPolicy", {})
            if traffic_policy.get("outlierDetection") or traffic_policy.get("connectionPool"):
                enabled["circuit_breaker"] = True
            for subset in spec.get("subsets", []):
                subset_tp = subset.get("trafficPolicy", {})
                if subset_tp.get("outlierDetection") or subset_tp.get("connectionPool"):
                    enabled["circuit_breaker"] = True

        if config.get("envoyFilters"):
            enabled["rate_limit"] = True

        return enabled

    def _filter_config_by_namespace(self):
        """只保留目标命名空间下的资源"""
        if not isinstance(self.config, dict):
            return

        scoped_keys = [
            "virtualServices",
            "destinationRules",
            "envoyFilters",
            "serviceEntries",
            "gateways",
            "sidecars",
            "workloadEntries",
            "workloadGroups",
            "authorizationPolicies"
        ]

        for key in scoped_keys:
            resources = self.config.get(key)
            if not isinstance(resources, list):
                continue

            filtered = []
            for resource in resources:
                metadata = resource.get("metadata", {})
                resource_ns = metadata.get("namespace")
                if resource_ns and resource_ns != self.namespace:
                    continue
                filtered.append(resource)
            self.config[key] = filtered

def main():
    parser = argparse.ArgumentParser(description="精简版 Istio 测试用例生成器（自动适配并发限制）")
    script_dir = os.path.dirname(os.path.realpath(__file__))
    default_input_path = os.path.join(script_dir, 'istio_config.json')
    parser.add_argument("-i", "--input", default=default_input_path, help="输入的 Istio 配置文件路径")
    parser.add_argument("-o", "--output", default="output_matrix.json", help="输出的测试矩阵文件路径")
    parser.add_argument("--ingress-url", required=True, help="集群入口服务的URL (例如: http://productpage:9080)")
    parser.add_argument("--service-deps", required=True, help="服务依赖关系的json文件路径（由 trace_utils 生成）")
    parser.add_argument("--namespace", default="default", help="目标命名空间，仅生成该命名空间的测试用例")
    args = parser.parse_args()

    generator = TestCaseGenerator(args.input, args.service_deps, namespace=args.namespace)
    test_cases = generator.generate()

    output_data = {
        "global_settings": {
            "ingress_url": args.ingress_url
        },
        "test_cases": test_cases
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"[SUCCESS] Generated {len(test_cases)} test cases, saved to {args.output}")

if __name__ == "__main__":
    main()