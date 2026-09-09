#!/usr/bin/env python3
"""
统一的路径计算模块 - 为所有生成器提供一致的路径计算逻辑
"""

from typing import Dict, List, Any


def get_total_possible_paths(config_data: Any) -> int:
    """获取配置中所有可能的路径数量 - 统一的计算逻辑"""
    total_paths = 0
    
    # 从配置数据中计算总路径数
    if isinstance(config_data, list):
        # 如果是YAML文档列表
        for doc in config_data:
            if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                spec = doc.get("spec", {})
                http_rules = spec.get("http", [])
                host = spec.get("hosts", [""])[0] if spec.get("hosts") else "unknown"
                
                for rule in http_rules:
                    # 匹配条件路径
                    if "match" in rule:
                        total_paths += 1  # 匹配条件路径
                    else:
                        total_paths += 1  # 默认路径
                    
                    # 路由目标路径
                    routes = rule.get("route", [])
                    if len(routes) > 1:
                        # 流量分割路径
                        total_paths += 1
                        for route in routes:
                            if "weight" in route:
                                total_paths += 1  # 权重路径
                    else:
                        # 普通路由路径
                        total_paths += 1
                
                # 负载均衡策略路径（DestinationRule中定义）
                # 目前正交代码还没实现，所以不计入
    else:
        # 如果是字典格式
        virtual_services = config_data.get("virtual_services", [])
        for vs in virtual_services:
            spec = vs.get("spec", {})
            http_rules = spec.get("http", [])
            for rule in http_rules:
                routes = rule.get("route", [])
                if routes:
                    total_paths += len(routes)
                else:
                    total_paths += 1
    
    return max(total_paths, 1)  # 至少返回1，避免除零错误


def calculate_cumulative_coverage(test_cases: List[Any], total_possible_paths: int) -> float:
    """计算累积覆盖率"""
    all_covered_paths = set()
    
    for case in test_cases:
        if hasattr(case, 'expected_paths'):
            # 如果是TestCase对象
            all_covered_paths.update(case.expected_paths)
        elif isinstance(case, dict) and 'expected_paths' in case:
            # 如果是字典格式
            all_covered_paths.update(case['expected_paths'])
    
    return len(all_covered_paths) / total_possible_paths if total_possible_paths > 0 else 0.0
