#!/usr/bin/env python3
"""
混合检测方法实现
动静态结合，静态建模辅助生成正交用例，结果融合
"""

import asyncio
import json
import yaml
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import logging
from datetime import datetime
import numpy as np

# 导入静态和动态检测器
from .static_only import StaticOnlyDetector
from .dynamic_only import DynamicOnlyDetector

class HybridDetector:
    """混合检测器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化混合检测器"""
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 初始化子检测器
        self.static_detector = StaticOnlyDetector(config)
        self.dynamic_detector = DynamicOnlyDetector(config)
        
        # 混合检测配置
        self.hybrid_config = self.config.get('hybrid', {})
        self.fusion_config = self.hybrid_config.get('result_fusion', {})
        self.orthogonal_config = self.hybrid_config.get('orthogonal_generation', {})
        
        # 权重配置
        self.static_weight = self.fusion_config.get('static_weight', 0.4)
        self.dynamic_weight = self.fusion_config.get('dynamic_weight', 0.6)
        
        # 置信度阈值
        self.confidence_threshold = self.fusion_config.get('confidence_threshold', 0.7)
    
    async def detect_faults(self, config_files: List[str]) -> Dict[str, Any]:
        """检测配置文件中的故障"""
        detection_result = {
            "method": "hybrid",
            "start_time": datetime.now().isoformat(),
            "config_files": config_files,
            "detected_faults": [],
            "summary": {
                "total_files": len(config_files),
                "files_with_faults": 0,
                "total_faults": 0,
                "fault_types": {},
                "detection_methods": {
                    "static_detected": 0,
                    "dynamic_detected": 0,
                    "both_detected": 0,
                    "fusion_detected": 0
                }
            },
            "orthogonal_test_cases": [],
            "fusion_details": {}
        }
        
        try:
            # 阶段1: 静态分析
            self.logger.info("阶段1: 执行静态分析")
            static_result = self.static_detector.detect_faults(config_files)
            
            # 阶段2: 基于静态分析生成正交测试用例
            self.logger.info("阶段2: 生成正交测试用例")
            orthogonal_cases = await self._generate_orthogonal_test_cases(config_files, static_result)
            detection_result["orthogonal_test_cases"] = orthogonal_cases
            
            # 阶段3: 动态验证
            self.logger.info("阶段3: 执行动态验证")
            dynamic_result = await self.dynamic_detector.detect_faults(config_files)
            
            # 阶段4: 结果融合
            self.logger.info("阶段4: 融合检测结果")
            fused_faults, fusion_details = await self._fuse_detection_results(
                static_result, dynamic_result, orthogonal_cases
            )
            detection_result["detected_faults"] = fused_faults
            detection_result["fusion_details"] = fusion_details
            
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
            
            # 统计检测方法
            detection_result["summary"]["detection_methods"] = self._calculate_detection_method_stats(
                static_result, dynamic_result, fused_faults
            )
            
        except Exception as e:
            self.logger.error(f"混合检测过程中发生错误: {e}")
            detection_result["error"] = str(e)
        
        detection_result["end_time"] = datetime.now().isoformat()
        return detection_result
    
    async def _generate_orthogonal_test_cases(self, config_files: List[str], 
                                            static_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """基于静态分析生成正交测试用例"""
        orthogonal_cases = []
        
        try:
            # 分析静态检测结果
            static_faults = static_result.get("detected_faults", [])
            
            # 根据静态检测结果生成针对性的动态测试用例
            for fault in static_faults:
                fault_type = fault.get("fault_type", "")
                config_file = fault.get("config_file", "")
                
                # 为每种故障类型生成相应的正交测试用例
                test_cases = self._generate_fault_specific_test_cases(fault_type, config_file, fault)
                orthogonal_cases.extend(test_cases)
            
            # 如果没有静态检测到故障，生成通用测试用例
            if not static_faults:
                for config_file in config_files:
                    generic_cases = self._generate_generic_test_cases(config_file)
                    orthogonal_cases.extend(generic_cases)
            
            # 优化测试用例集合（去重、优先级排序）
            orthogonal_cases = self._optimize_test_cases(orthogonal_cases)
            
        except Exception as e:
            self.logger.error(f"生成正交测试用例时发生错误: {e}")
        
        return orthogonal_cases
    
    def _generate_fault_specific_test_cases(self, fault_type: str, config_file: str, 
                                          fault_details: Dict[str, Any]) -> List[Dict[str, Any]]:
        """为特定故障类型生成测试用例"""
        test_cases = []
        
        if fault_type == "routing_conflict":
            test_cases.append({
                "test_case_id": f"routing_conflict_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "traffic_distribution",
                "description": "验证路由冲突对流量分发的影响",
                "traffic_pattern": {
                    "qps": 10,
                    "duration": 120,
                    "endpoints": ["/productpage", "/api/v1/products"],
                    "user_agents": ["jason", "alice", "bob"]
                },
                "expected_behavior": {
                    "traffic_split_consistency": True,
                    "error_rate_threshold": 0.1
                },
                "priority": "high"
            })
        
        elif fault_type == "missing_subset":
            test_cases.append({
                "test_case_id": f"missing_subset_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "service_availability",
                "description": "验证缺失子集对服务可用性的影响",
                "traffic_pattern": {
                    "qps": 5,
                    "duration": 90,
                    "endpoints": ["/reviews"],
                    "target_subset": fault_details.get("details", {}).get("missing_subset", "v4")
                },
                "expected_behavior": {
                    "service_availability": False,
                    "error_response_codes": [503, 502]
                },
                "priority": "high"
            })
        
        elif fault_type == "weight_error":
            test_cases.append({
                "test_case_id": f"weight_error_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "traffic_weight_validation",
                "description": "验证权重错误对流量分发的影响",
                "traffic_pattern": {
                    "qps": 8,
                    "duration": 150,
                    "endpoints": ["/reviews"],
                    "sample_size": 1000
                },
                "expected_behavior": {
                    "weight_distribution_accuracy": False,
                    "total_weight": fault_details.get("details", {}).get("total_weight", 80)
                },
                "priority": "medium"
            })
        
        elif fault_type == "fault_injection_error":
            test_cases.append({
                "test_case_id": f"fault_injection_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "fault_injection_validation",
                "description": "验证故障注入配置的有效性",
                "traffic_pattern": {
                    "qps": 6,
                    "duration": 180,
                    "endpoints": ["/productpage"],
                    "user_header": "jason"
                },
                "expected_behavior": {
                    "delay_injection": True,
                    "abort_injection": True,
                    "injection_consistency": False
                },
                "priority": "medium"
            })
        
        elif fault_type == "rate_limit_error":
            test_cases.append({
                "test_case_id": f"rate_limit_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "rate_limiting_validation",
                "description": "验证限流配置的有效性",
                "traffic_pattern": {
                    "qps": 20,
                    "duration": 120,
                    "endpoints": ["/adservice"],
                    "burst_pattern": True
                },
                "expected_behavior": {
                    "rate_limiting_effectiveness": False,
                    "expected_429_responses": True
                },
                "priority": "high"
            })
        
        elif fault_type == "retry_policy_error":
            test_cases.append({
                "test_case_id": f"retry_policy_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "retry_behavior_validation",
                "description": "验证重试策略的有效性",
                "traffic_pattern": {
                    "qps": 5,
                    "duration": 200,
                    "endpoints": ["/api/v1/products"],
                    "inject_errors": True
                },
                "expected_behavior": {
                    "retry_attempts": fault_details.get("details", {}).get("retry_attempts", 10),
                    "retry_efficiency": False
                },
                "priority": "low"
            })
        
        elif fault_type == "circuit_breaker_error":
            test_cases.append({
                "test_case_id": f"circuit_breaker_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "circuit_breaker_validation",
                "description": "验证熔断器配置的有效性",
                "traffic_pattern": {
                    "qps": 15,
                    "duration": 180,
                    "endpoints": ["/reviews"],
                    "error_injection_rate": 0.3
                },
                "expected_behavior": {
                    "circuit_breaker_activation": True,
                    "ejection_frequency": "high"
                },
                "priority": "medium"
            })
        
        elif fault_type == "timeout_error":
            test_cases.append({
                "test_case_id": f"timeout_{len(test_cases)}",
                "config_file": config_file,
                "test_type": "timeout_validation",
                "description": "验证超时配置的有效性",
                "traffic_pattern": {
                    "qps": 8,
                    "duration": 150,
                    "endpoints": ["/api/v1/products"],
                    "slow_response_simulation": True
                },
                "expected_behavior": {
                    "timeout_effectiveness": False,
                    "frequent_timeouts": True
                },
                "priority": "low"
            })
        
        return test_cases
    
    def _generate_generic_test_cases(self, config_file: str) -> List[Dict[str, Any]]:
        """生成通用测试用例"""
        return [
            {
                "test_case_id": f"generic_health_check_{len([])}",
                "config_file": config_file,
                "test_type": "health_check",
                "description": "通用健康检查测试",
                "traffic_pattern": {
                    "qps": 3,
                    "duration": 60,
                    "endpoints": ["/productpage", "/health"]
                },
                "expected_behavior": {
                    "service_availability": True,
                    "response_time_threshold": 2000
                },
                "priority": "low"
            },
            {
                "test_case_id": f"generic_load_test_{len([])}",
                "config_file": config_file,
                "test_type": "load_test",
                "description": "通用负载测试",
                "traffic_pattern": {
                    "qps": 10,
                    "duration": 120,
                    "endpoints": ["/productpage"]
                },
                "expected_behavior": {
                    "error_rate_threshold": 0.05,
                    "response_time_p95_threshold": 3000
                },
                "priority": "medium"
            }
        ]
    
    def _optimize_test_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """优化测试用例集合"""
        # 去重
        unique_cases = []
        seen_cases = set()
        
        for case in test_cases:
            case_key = (case["config_file"], case["test_type"], case["description"])
            if case_key not in seen_cases:
                unique_cases.append(case)
                seen_cases.add(case_key)
        
        # 按优先级排序
        priority_order = {"high": 3, "medium": 2, "low": 1}
        unique_cases.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 1), reverse=True)
        
        # 限制测试用例数量
        max_cases = self.orthogonal_config.get('max_test_cases', 10)
        return unique_cases[:max_cases]
    
    async def _fuse_detection_results(self, static_result: Dict[str, Any], 
                                    dynamic_result: Dict[str, Any],
                                    orthogonal_cases: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """融合静态和动态检测结果"""
        fused_faults = []
        fusion_details = {
            "static_faults_count": len(static_result.get("detected_faults", [])),
            "dynamic_faults_count": len(dynamic_result.get("detected_faults", [])),
            "fusion_rules_applied": [],
            "confidence_adjustments": []
        }
        
        try:
            # 获取静态和动态检测结果
            static_faults = static_result.get("detected_faults", [])
            dynamic_faults = dynamic_result.get("detected_faults", [])
            
            # 创建故障映射
            static_fault_map = self._create_fault_map(static_faults)
            dynamic_fault_map = self._create_fault_map(dynamic_faults)
            
            # 融合规则1: 静态和动态都检测到的故障
            for fault_key, static_fault in static_fault_map.items():
                if fault_key in dynamic_fault_map:
                    dynamic_fault = dynamic_fault_map[fault_key]
                    fused_fault = self._fuse_matching_faults(static_fault, dynamic_fault)
                    fused_faults.append(fused_fault)
                    fusion_details["fusion_rules_applied"].append("both_methods_detected")
            
            # 融合规则2: 仅静态检测到的高置信度故障
            for fault_key, static_fault in static_fault_map.items():
                if fault_key not in dynamic_fault_map:
                    if static_fault.get("confidence", 0) >= self.confidence_threshold:
                        # 检查是否有对应的正交测试用例支持
                        if self._has_orthogonal_support(fault_key, orthogonal_cases):
                            enhanced_fault = self._enhance_static_fault(static_fault, orthogonal_cases)
                            fused_faults.append(enhanced_fault)
                            fusion_details["fusion_rules_applied"].append("static_high_confidence_with_orthogonal")
                        else:
                            # 降低置信度但保留
                            static_fault["confidence"] *= 0.8
                            static_fault["detection_method"] = "static_only"
                            fused_faults.append(static_fault)
                            fusion_details["fusion_rules_applied"].append("static_only_reduced_confidence")
            
            # 融合规则3: 仅动态检测到的故障
            for fault_key, dynamic_fault in dynamic_fault_map.items():
                if fault_key not in static_fault_map:
                    # 检查是否与静态分析结果相关
                    if self._is_dynamic_fault_related_to_static(dynamic_fault, static_faults):
                        enhanced_fault = self._enhance_dynamic_fault(dynamic_fault, static_faults)
                        fused_faults.append(enhanced_fault)
                        fusion_details["fusion_rules_applied"].append("dynamic_with_static_context")
                    else:
                        # 纯动态检测的故障，降低置信度
                        dynamic_fault["confidence"] *= 0.7
                        dynamic_fault["detection_method"] = "dynamic_only"
                        fused_faults.append(dynamic_fault)
                        fusion_details["fusion_rules_applied"].append("dynamic_only_reduced_confidence")
            
            # 融合规则4: 基于正交测试用例的增强检测
            orthogonal_enhanced_faults = self._enhance_with_orthogonal_results(fused_faults, orthogonal_cases)
            fused_faults.extend(orthogonal_enhanced_faults)
            
            # 去重和排序
            fused_faults = self._deduplicate_and_rank_faults(fused_faults)
            
        except Exception as e:
            self.logger.error(f"融合检测结果时发生错误: {e}")
        
        return fused_faults, fusion_details
    
    def _create_fault_map(self, faults: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """创建故障映射"""
        fault_map = {}
        
        for fault in faults:
            # 使用配置文件和故障类型作为键
            key = f"{fault.get('config_file', '')}:{fault.get('fault_type', '')}"
            fault_map[key] = fault
        
        return fault_map
    
    def _fuse_matching_faults(self, static_fault: Dict[str, Any], 
                            dynamic_fault: Dict[str, Any]) -> Dict[str, Any]:
        """融合匹配的静态和动态故障"""
        # 计算融合后的置信度
        static_confidence = static_fault.get("confidence", 0)
        dynamic_confidence = dynamic_fault.get("confidence", 0)
        
        # 加权平均
        fused_confidence = (static_confidence * self.static_weight + 
                          dynamic_confidence * self.dynamic_weight)
        
        # 创建融合后的故障
        fused_fault = {
            "config_file": static_fault.get("config_file"),
            "fault_type": static_fault.get("fault_type"),
            "severity": max(static_fault.get("severity", "low"), 
                          dynamic_fault.get("severity", "low"), 
                          key=lambda x: {"low": 1, "medium": 2, "high": 3}[x]),
            "description": f"融合检测: {static_fault.get('description', '')} | {dynamic_fault.get('description', '')}",
            "confidence": fused_confidence,
            "detection_method": "hybrid",
            "details": {
                "static_details": static_fault.get("details", {}),
                "dynamic_details": dynamic_fault.get("details", {}),
                "fusion_confidence": fused_confidence
            },
            "detection_time": datetime.now().isoformat()
        }
        
        return fused_fault
    
    def _has_orthogonal_support(self, fault_key: str, orthogonal_cases: List[Dict[str, Any]]) -> bool:
        """检查是否有正交测试用例支持"""
        for case in orthogonal_cases:
            if fault_key.split(':')[0] in case.get("config_file", ""):
                return True
        return False
    
    def _enhance_static_fault(self, static_fault: Dict[str, Any], 
                            orthogonal_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用正交测试用例增强静态故障"""
        enhanced_fault = static_fault.copy()
        enhanced_fault["detection_method"] = "static_enhanced_with_orthogonal"
        enhanced_fault["confidence"] = min(enhanced_fault.get("confidence", 0) * 1.1, 1.0)
        
        # 添加正交测试支持信息
        enhanced_fault["details"]["orthogonal_support"] = True
        enhanced_fault["details"]["orthogonal_test_cases"] = [
            case["test_case_id"] for case in orthogonal_cases 
            if static_fault.get("config_file", "") in case.get("config_file", "")
        ]
        
        return enhanced_fault
    
    def _is_dynamic_fault_related_to_static(self, dynamic_fault: Dict[str, Any], 
                                          static_faults: List[Dict[str, Any]]) -> bool:
        """检查动态故障是否与静态分析结果相关"""
        dynamic_config = dynamic_fault.get("config_file", "")
        dynamic_type = dynamic_fault.get("fault_type", "")
        
        for static_fault in static_faults:
            static_config = static_fault.get("config_file", "")
            static_type = static_fault.get("fault_type", "")
            
            # 检查是否是同一个配置文件
            if dynamic_config == static_config:
                # 检查故障类型是否相关
                if self._are_fault_types_related(dynamic_type, static_type):
                    return True
        
        return False
    
    def _are_fault_types_related(self, type1: str, type2: str) -> bool:
        """检查两个故障类型是否相关"""
        related_groups = [
            ["routing_conflict", "traffic_distribution_anomaly"],
            ["missing_subset", "service_availability"],
            ["weight_error", "traffic_weight_validation"],
            ["fault_injection_error", "fault_injection_validation"],
            ["rate_limit_error", "rate_limit_anomaly"],
            ["retry_policy_error", "retry_behavior_anomaly"],
            ["circuit_breaker_error", "circuit_breaker_anomaly"],
            ["timeout_error", "timeout_validation"]
        ]
        
        for group in related_groups:
            if type1 in group and type2 in group:
                return True
        
        return False
    
    def _enhance_dynamic_fault(self, dynamic_fault: Dict[str, Any], 
                             static_faults: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用静态分析结果增强动态故障"""
        enhanced_fault = dynamic_fault.copy()
        enhanced_fault["detection_method"] = "dynamic_enhanced_with_static"
        enhanced_fault["confidence"] = min(enhanced_fault.get("confidence", 0) * 1.2, 1.0)
        
        # 添加静态分析上下文
        enhanced_fault["details"]["static_context"] = True
        enhanced_fault["details"]["related_static_faults"] = [
            fault for fault in static_faults 
            if fault.get("config_file") == dynamic_fault.get("config_file")
        ]
        
        return enhanced_fault
    
    def _enhance_with_orthogonal_results(self, faults: List[Dict[str, Any]], 
                                       orthogonal_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """使用正交测试结果增强故障检测"""
        enhanced_faults = []
        
        # 这里可以添加基于正交测试结果的额外故障检测逻辑
        # 例如，如果正交测试发现异常行为，但静态和动态检测都没有发现，可以添加新的故障
        
        return enhanced_faults
    
    def _deduplicate_and_rank_faults(self, faults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重和排序故障"""
        # 去重
        unique_faults = []
        seen_faults = set()
        
        for fault in faults:
            fault_key = (fault.get("config_file", ""), fault.get("fault_type", ""), 
                        fault.get("description", ""))
            if fault_key not in seen_faults:
                unique_faults.append(fault)
                seen_faults.add(fault_key)
        
        # 按置信度排序
        unique_faults.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return unique_faults
    
    def _calculate_detection_method_stats(self, static_result: Dict[str, Any], 
                                        dynamic_result: Dict[str, Any],
                                        fused_faults: List[Dict[str, Any]]) -> Dict[str, int]:
        """计算检测方法统计"""
        stats = {
            "static_detected": len(static_result.get("detected_faults", [])),
            "dynamic_detected": len(dynamic_result.get("detected_faults", [])),
            "both_detected": 0,
            "fusion_detected": len(fused_faults)
        }
        
        # 计算同时被两种方法检测到的故障数量
        static_faults = static_result.get("detected_faults", [])
        dynamic_faults = dynamic_result.get("detected_faults", [])
        
        static_keys = set(f"{f.get('config_file', '')}:{f.get('fault_type', '')}" for f in static_faults)
        dynamic_keys = set(f"{f.get('config_file', '')}:{f.get('fault_type', '')}" for f in dynamic_faults)
        
        stats["both_detected"] = len(static_keys & dynamic_keys)
        
        return stats
