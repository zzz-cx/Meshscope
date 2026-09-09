#!/usr/bin/env python3
"""
静态检测方法实现
仅进行静态配置解析与一致性检测
"""

import yaml
import json
import re
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
import logging
from datetime import datetime

class StaticOnlyDetector:
    """静态检测器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化静态检测器"""
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 检测规则配置
        self.detection_rules = {
            'routing_conflict': self._detect_routing_conflict,
            'missing_subset': self._detect_missing_subset,
            'weight_error': self._detect_weight_error,
            'duplicate_config': self._detect_duplicate_config,
            'missing_service_ref': self._detect_missing_service_ref,
            'gateway_selector_error': self._detect_gateway_selector_error,
            'fault_injection_error': self._detect_fault_injection_error,
            'rate_limit_error': self._detect_rate_limit_error,
            'retry_policy_error': self._detect_retry_policy_error,
            'circuit_breaker_error': self._detect_circuit_breaker_error,
            'timeout_error': self._detect_timeout_error
        }
    
    def detect_faults(self, config_files: List[str]) -> Dict[str, Any]:
        """检测配置文件中的故障"""
        detection_result = {
            "method": "static_only",
            "start_time": datetime.now().isoformat(),
            "config_files": config_files,
            "detected_faults": [],
            "summary": {
                "total_files": len(config_files),
                "files_with_faults": 0,
                "total_faults": 0,
                "fault_types": {}
            }
        }
        
        try:
            # 解析所有配置文件
            parsed_configs = self._parse_config_files(config_files)
            
            # 对每个配置进行检测
            for config_file, config_data in parsed_configs.items():
                file_faults = self._detect_faults_in_config(config_file, config_data, parsed_configs)
                detection_result["detected_faults"].extend(file_faults)
            
            # 计算统计信息
            detection_result["summary"]["files_with_faults"] = len(set(
                fault["config_file"] for fault in detection_result["detected_faults"]
            ))
            detection_result["summary"]["total_faults"] = len(detection_result["detected_faults"])
            
            # 统计故障类型
            for fault in detection_result["detected_faults"]:
                fault_type = fault["fault_type"]
                detection_result["summary"]["fault_types"][fault_type] = \
                    detection_result["summary"]["fault_types"].get(fault_type, 0) + 1
            
        except Exception as e:
            self.logger.error(f"静态检测过程中发生错误: {e}")
            detection_result["error"] = str(e)
        
        detection_result["end_time"] = datetime.now().isoformat()
        return detection_result
    
    def _parse_config_files(self, config_files: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """解析配置文件"""
        parsed_configs = {}
        
        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 处理多文档YAML
                documents = list(yaml.safe_load_all(content))
                parsed_configs[config_file] = [doc for doc in documents if doc is not None]
                
            except Exception as e:
                self.logger.error(f"解析配置文件失败 {config_file}: {e}")
                parsed_configs[config_file] = []
        
        return parsed_configs
    
    def _detect_faults_in_config(self, config_file: str, config_data: List[Dict[str, Any]], 
                                all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测单个配置文件中的故障"""
        faults = []
        
        for config_doc in config_data:
            if not isinstance(config_doc, dict):
                continue
            
            kind = config_doc.get('kind', '')
            metadata = config_doc.get('metadata', {})
            spec = config_doc.get('spec', {})
            
            # 根据资源类型进行相应检测
            if kind == 'VirtualService':
                faults.extend(self._detect_virtualservice_faults(config_file, config_doc, all_configs))
            elif kind == 'DestinationRule':
                faults.extend(self._detect_destinationrule_faults(config_file, config_doc, all_configs))
            elif kind == 'Gateway':
                faults.extend(self._detect_gateway_faults(config_file, config_doc, all_configs))
            elif kind == 'EnvoyFilter':
                faults.extend(self._detect_envoyfilter_faults(config_file, config_doc, all_configs))
        
        return faults
    
    def _detect_virtualservice_faults(self, config_file: str, vs_config: Dict[str, Any], 
                                    all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测VirtualService中的故障"""
        faults = []
        
        # 检测路由冲突
        routing_faults = self._detect_routing_conflict(config_file, vs_config)
        faults.extend(routing_faults)
        
        # 检测权重错误
        weight_faults = self._detect_weight_error(config_file, vs_config)
        faults.extend(weight_faults)
        
        # 检测缺失子集
        subset_faults = self._detect_missing_subset(config_file, vs_config, all_configs)
        faults.extend(subset_faults)
        
        # 检测故障注入错误
        fault_injection_faults = self._detect_fault_injection_error(config_file, vs_config)
        faults.extend(fault_injection_faults)
        
        # 检测重试策略错误
        retry_faults = self._detect_retry_policy_error(config_file, vs_config)
        faults.extend(retry_faults)
        
        # 检测超时错误
        timeout_faults = self._detect_timeout_error(config_file, vs_config)
        faults.extend(timeout_faults)
        
        return faults
    
    def _detect_destinationrule_faults(self, config_file: str, dr_config: Dict[str, Any], 
                                     all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测DestinationRule中的故障"""
        faults = []
        
        # 检测熔断器错误
        circuit_breaker_faults = self._detect_circuit_breaker_error(config_file, dr_config)
        faults.extend(circuit_breaker_faults)
        
        return faults
    
    def _detect_gateway_faults(self, config_file: str, gateway_config: Dict[str, Any], 
                             all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测Gateway中的故障"""
        faults = []
        
        # 检测选择器错误
        selector_faults = self._detect_gateway_selector_error(config_file, gateway_config)
        faults.extend(selector_faults)
        
        return faults
    
    def _detect_envoyfilter_faults(self, config_file: str, ef_config: Dict[str, Any], 
                                 all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测EnvoyFilter中的故障"""
        faults = []
        
        # 检测重复配置
        duplicate_faults = self._detect_duplicate_config(config_file, ef_config, all_configs)
        faults.extend(duplicate_faults)
        
        # 检测限流错误
        rate_limit_faults = self._detect_rate_limit_error(config_file, ef_config)
        faults.extend(rate_limit_faults)
        
        return faults
    
    def _detect_routing_conflict(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测路由冲突"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        total_weight = 0
        for route in http_routes:
            route_destinations = route.get('route', [])
            for dest in route_destinations:
                weight = dest.get('weight', 0)
                total_weight += weight
        
        if total_weight > 100:
            fault = {
                "config_file": config_file,
                "fault_type": "routing_conflict",
                "severity": "high",
                "description": f"路由权重总和超过100%: {total_weight}%",
                "details": {
                    "total_weight": total_weight,
                    "expected_max": 100,
                    "excess_weight": total_weight - 100
                },
                "confidence": 0.9,
                "detection_time": datetime.now().isoformat()
            }
            faults.append(fault)
        
        return faults
    
    def _detect_weight_error(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测权重错误"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        for route in http_routes:
            route_destinations = route.get('route', [])
            if len(route_destinations) > 1:  # 只有多个目标时才检查权重
                total_weight = sum(dest.get('weight', 0) for dest in route_destinations)
                
                if total_weight != 100:
                    fault = {
                        "config_file": config_file,
                        "fault_type": "weight_error",
                        "severity": "medium",
                        "description": f"权重总和不等于100%: {total_weight}%",
                        "details": {
                            "total_weight": total_weight,
                            "expected_weight": 100,
                            "weight_difference": abs(total_weight - 100)
                        },
                        "confidence": 0.8,
                        "detection_time": datetime.now().isoformat()
                    }
                    faults.append(fault)
        
        return faults
    
    def _detect_missing_subset(self, config_file: str, vs_config: Dict[str, Any], 
                             all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测缺失子集"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        # 收集所有引用的子集
        referenced_subsets = set()
        for route in http_routes:
            route_destinations = route.get('route', [])
            for dest in route_destinations:
                subset = dest.get('subset')
                if subset:
                    referenced_subsets.add(subset)
        
        # 查找对应的DestinationRule
        vs_name = vs_config.get('metadata', {}).get('name', '')
        vs_namespace = vs_config.get('metadata', {}).get('namespace', 'default')
        
        available_subsets = set()
        for file_path, configs in all_configs.items():
            for config in configs:
                if (config.get('kind') == 'DestinationRule' and 
                    config.get('metadata', {}).get('name') == vs_name and
                    config.get('metadata', {}).get('namespace') == vs_namespace):
                    
                    subsets = config.get('spec', {}).get('subsets', [])
                    for subset in subsets:
                        available_subsets.add(subset.get('name'))
        
        # 检查缺失的子集
        missing_subsets = referenced_subsets - available_subsets
        for subset in missing_subsets:
            fault = {
                "config_file": config_file,
                "fault_type": "missing_subset",
                "severity": "high",
                "description": f"引用的子集 '{subset}' 在DestinationRule中不存在",
                "details": {
                    "missing_subset": subset,
                    "referenced_subsets": list(referenced_subsets),
                    "available_subsets": list(available_subsets)
                },
                "confidence": 0.95,
                "detection_time": datetime.now().isoformat()
            }
            faults.append(fault)
        
        return faults
    
    def _detect_duplicate_config(self, config_file: str, ef_config: Dict[str, Any], 
                               all_configs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """检测重复配置"""
        faults = []
        
        ef_name = ef_config.get('metadata', {}).get('name', '')
        ef_namespace = ef_config.get('metadata', {}).get('namespace', 'default')
        workload_selector = ef_config.get('spec', {}).get('workloadSelector', {})
        config_patches = ef_config.get('spec', {}).get('configPatches', [])
        
        # 检查是否有其他EnvoyFilter使用相同的工作负载选择器和补丁位置
        for file_path, configs in all_configs.items():
            if file_path == config_file:
                continue
                
            for config in configs:
                if (config.get('kind') == 'EnvoyFilter' and
                    config.get('metadata', {}).get('name') != ef_name and
                    config.get('metadata', {}).get('namespace') == ef_namespace):
                    
                    other_workload_selector = config.get('spec', {}).get('workloadSelector', {})
                    other_config_patches = config.get('spec', {}).get('configPatches', [])
                    
                    # 检查工作负载选择器是否相同
                    if workload_selector == other_workload_selector:
                        # 检查补丁位置是否冲突
                        for patch in config_patches:
                            for other_patch in other_config_patches:
                                if self._patches_conflict(patch, other_patch):
                                    fault = {
                                        "config_file": config_file,
                                        "fault_type": "duplicate_config",
                                        "severity": "medium",
                                        "description": f"EnvoyFilter配置冲突: {ef_name} 与 {config.get('metadata', {}).get('name')}",
                                        "details": {
                                            "conflicting_filters": [ef_name, config.get('metadata', {}).get('name')],
                                            "workload_selector": workload_selector,
                                            "conflict_type": "same_workload_same_patch"
                                        },
                                        "confidence": 0.7,
                                        "detection_time": datetime.now().isoformat()
                                    }
                                    faults.append(fault)
        
        return faults
    
    def _patches_conflict(self, patch1: Dict[str, Any], patch2: Dict[str, Any]) -> bool:
        """检查两个补丁是否冲突"""
        # 简化的冲突检测逻辑
        match1 = patch1.get('match', {})
        match2 = patch2.get('match', {})
        
        # 检查上下文是否相同
        if match1.get('context') != match2.get('context'):
            return False
        
        # 检查监听器过滤器是否相同
        listener1 = match1.get('listener', {})
        listener2 = match2.get('listener', {})
        
        filter_chain1 = listener1.get('filterChain', {})
        filter_chain2 = listener2.get('filterChain', {})
        
        filter1 = filter_chain1.get('filter', {})
        filter2 = filter_chain2.get('filter', {})
        
        if filter1.get('name') != filter2.get('name'):
            return False
        
        # 检查子过滤器是否相同
        sub_filter1 = filter1.get('subFilter', {})
        sub_filter2 = filter2.get('subFilter', {})
        
        return sub_filter1.get('name') == sub_filter2.get('name')
    
    def _detect_missing_service_ref(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测缺失的服务引用"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        for route in http_routes:
            route_destinations = route.get('route', [])
            for dest in route_destinations:
                host = dest.get('host', '')
                
                # 检查是否是外部服务引用
                if 'non-existent-service' in host:
                    fault = {
                        "config_file": config_file,
                        "fault_type": "missing_service_ref",
                        "severity": "high",
                        "description": f"引用的服务不存在: {host}",
                        "details": {
                            "missing_service": host,
                            "referenced_in": "VirtualService"
                        },
                        "confidence": 0.9,
                        "detection_time": datetime.now().isoformat()
                    }
                    faults.append(fault)
        
        return faults
    
    def _detect_gateway_selector_error(self, config_file: str, gateway_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测Gateway选择器错误"""
        faults = []
        
        spec = gateway_config.get('spec', {})
        selector = spec.get('selector', {})
        
        # 检查选择器是否匹配已知的gateway
        if 'non-existent-gateway' in str(selector):
            fault = {
                "config_file": config_file,
                "fault_type": "gateway_selector_error",
                "severity": "medium",
                "description": "Gateway选择器不匹配任何实际的ingress gateway",
                "details": {
                    "configured_selector": selector,
                    "expected_selectors": ["istio: ingressgateway"]
                },
                "confidence": 0.8,
                "detection_time": datetime.now().isoformat()
            }
            faults.append(fault)
        
        return faults
    
    def _detect_fault_injection_error(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测故障注入错误"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        for route in http_routes:
            fault_config = route.get('fault', {})
            
            # 检查是否同时配置了delay和abort
            if 'delay' in fault_config and 'abort' in fault_config:
                fault = {
                    "config_file": config_file,
                    "fault_type": "fault_injection_error",
                    "severity": "medium",
                    "description": "同时配置了延迟和错误注入，可能导致不可预测的行为",
                    "details": {
                        "delay_config": fault_config.get('delay'),
                        "abort_config": fault_config.get('abort'),
                        "conflict_type": "delay_and_abort_together"
                    },
                    "confidence": 0.85,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _detect_rate_limit_error(self, config_file: str, ef_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测限流错误"""
        faults = []
        
        spec = ef_config.get('spec', {})
        config_patches = spec.get('configPatches', [])
        
        for patch in config_patches:
            patch_value = patch.get('patch', {}).get('value', {})
            
            # 检查是否是限流配置
            if patch_value.get('name') == 'envoy.filters.http.local_ratelimit':
                typed_config = patch_value.get('typed_config', {})
                if 'LocalRateLimit' in typed_config.get('type_url', ''):
                    value = typed_config.get('value', {})
                    token_bucket = value.get('token_bucket', {})
                    
                    max_tokens = token_bucket.get('max_tokens', 0)
                    tokens_per_fill = token_bucket.get('tokens_per_fill', 0)
                    fill_interval = token_bucket.get('fill_interval', '')
                    
                    # 检查令牌桶配置是否合理
                    if max_tokens < tokens_per_fill:
                        fault = {
                            "config_file": config_file,
                            "fault_type": "rate_limit_error",
                            "severity": "high",
                            "description": "限流配置中的令牌桶参数不合理",
                            "details": {
                                "max_tokens": max_tokens,
                                "tokens_per_fill": tokens_per_fill,
                                "fill_interval": fill_interval,
                                "issue": "bucket_size_too_small"
                            },
                            "confidence": 0.8,
                            "detection_time": datetime.now().isoformat()
                        }
                        faults.append(fault)
        
        return faults
    
    def _detect_retry_policy_error(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测重试策略错误"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        for route in http_routes:
            retries = route.get('retries', {})
            attempts = retries.get('attempts', 0)
            
            # 检查重试次数是否过多
            if attempts > 5:
                fault = {
                    "config_file": config_file,
                    "fault_type": "retry_policy_error",
                    "severity": "low",
                    "description": f"重试次数过多: {attempts}",
                    "details": {
                        "retry_attempts": attempts,
                        "max_recommended": 5,
                        "impact": "excessive_retry_overhead"
                    },
                    "confidence": 0.75,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _detect_circuit_breaker_error(self, config_file: str, dr_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测熔断器错误"""
        faults = []
        
        spec = dr_config.get('spec', {})
        traffic_policy = spec.get('trafficPolicy', {})
        outlier_detection = traffic_policy.get('outlierDetection', {})
        
        if outlier_detection:
            consecutive_errors = outlier_detection.get('consecutive5xxErrors', 0)
            max_connections = traffic_policy.get('connectionPool', {}).get('tcp', {}).get('maxConnections', 0)
            
            # 检查熔断器配置是否过于激进
            if consecutive_errors < 3 and max_connections < 5:
                fault = {
                    "config_file": config_file,
                    "fault_type": "circuit_breaker_error",
                    "severity": "medium",
                    "description": "熔断器配置参数过于激进",
                    "details": {
                        "consecutive_errors": consecutive_errors,
                        "max_connections": max_connections,
                        "issue": "too_aggressive_circuit_breaking"
                    },
                    "confidence": 0.8,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _detect_timeout_error(self, config_file: str, vs_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测超时错误"""
        faults = []
        
        spec = vs_config.get('spec', {})
        http_routes = spec.get('http', [])
        
        for route in http_routes:
            timeout = route.get('timeout', '')
            
            # 解析超时时间
            if timeout:
                timeout_seconds = self._parse_timeout(timeout)
                
                # 检查超时时间是否过短
                if timeout_seconds < 1.0:
                    fault = {
                        "config_file": config_file,
                        "fault_type": "timeout_error",
                        "severity": "low",
                        "description": f"超时时间配置过短: {timeout}",
                        "details": {
                            "timeout_seconds": timeout_seconds,
                            "recommended_minimum": 1.0,
                            "impact": "frequent_timeouts"
                        },
                        "confidence": 0.7,
                        "detection_time": datetime.now().isoformat()
                    }
                    faults.append(fault)
        
        return faults
    
    def _parse_timeout(self, timeout_str: str) -> float:
        """解析超时时间字符串"""
        if timeout_str.endswith('s'):
            return float(timeout_str[:-1])
        elif timeout_str.endswith('ms'):
            return float(timeout_str[:-2]) / 1000
        elif timeout_str.endswith('m'):
            return float(timeout_str[:-1]) * 60
        elif timeout_str.endswith('h'):
            return float(timeout_str[:-1]) * 3600
        else:
            return float(timeout_str)
