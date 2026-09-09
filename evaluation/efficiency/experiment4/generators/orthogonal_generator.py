#!/usr/bin/env python3
"""
正交测试用例生成器 - 基于四条正交原则生成测试用例
"""

import json
import itertools
from typing import Dict, List, Any, Tuple, Set
from dataclasses import dataclass
import numpy as np


@dataclass
class OrthogonalDimension:
    """正交维度定义"""
    name: str
    values: List[Any]
    category: str  # match_conditions, function_policies, global_local, trigger_mechanisms
    description: str = ""


@dataclass
class OrthogonalTestCase:
    """正交测试用例定义"""
    case_id: str
    dimensions: Dict[str, Any]
    orthogonal_groups: List[str]
    expected_paths: List[str]
    coverage_score: float
    description: str = ""


class OrthogonalGenerator:
    """正交测试用例生成器"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化生成器"""
        self.config_data = config_data
        self.orthogonal_dimensions = self._extract_orthogonal_dimensions()
        self.test_cases = []
        self.coverage_matrix = {}
    
    def _extract_orthogonal_dimensions(self) -> List[OrthogonalDimension]:
        """基于四条正交原则提取维度"""
        dimensions = []
        
        # 1. 匹配条件维度正交
        match_dimensions = self._extract_match_condition_dimensions()
        dimensions.extend(match_dimensions)
        
        # 2. 功能策略间正交
        function_dimensions = self._extract_function_policy_dimensions()
        dimensions.extend(function_dimensions)
        
        # 3. 全局/局部策略正交
        scope_dimensions = self._extract_scope_dimensions()
        dimensions.extend(scope_dimensions)
        
        # 4. 策略触发机制正交
        trigger_dimensions = self._extract_trigger_mechanism_dimensions()
        dimensions.extend(trigger_dimensions)
        
        return dimensions
    
    def _extract_match_condition_dimensions(self) -> List[OrthogonalDimension]:
        """提取匹配条件正交维度"""
        dimensions = []
        
        # Header匹配维度
        dimensions.append(OrthogonalDimension(
            name="header_matching",
            values=[
                {"key": "end-user", "value": "jason"},
                {"key": "end-user", "value": "admin"},
                {"key": "x-user-role", "value": "premium"},
                {"key": "x-user-role", "value": "standard"},
                {"key": "x-device-type", "value": "mobile"},
                {"key": "x-device-type", "value": "desktop"}
            ],
            category="match_conditions",
            description="HTTP Header匹配条件"
        ))
        
        # URI匹配维度
        dimensions.append(OrthogonalDimension(
            name="uri_matching",
            values=[
                {"type": "prefix", "value": "/api/v1"},
                {"type": "prefix", "value": "/admin"},
                {"type": "prefix", "value": "/premium"},
                {"type": "prefix", "value": "/mobile"},
                {"type": "regex", "value": "^/admin/.*"},
                {"type": "exact", "value": "/"}
            ],
            category="match_conditions",
            description="URI路径匹配条件"
        ))
        
        # 地域匹配维度
        dimensions.append(OrthogonalDimension(
            name="region_matching",
            values=[
                {"key": "x-region", "value": "us-east"},
                {"key": "x-region", "value": "us-west"},
                {"key": "x-region", "value": "eu-central"},
                {"key": "x-region", "value": "asia-pacific"}
            ],
            category="match_conditions",
            description="地域匹配条件"
        ))
        
        return dimensions
    
    def _extract_function_policy_dimensions(self) -> List[OrthogonalDimension]:
        """提取功能策略正交维度"""
        dimensions = []
        
        # 负载均衡策略
        dimensions.append(OrthogonalDimension(
            name="load_balancing",
            values=[
                {"algorithm": "ROUND_ROBIN"},
                {"algorithm": "LEAST_CONN"},
                {"algorithm": "RANDOM"},
                {"algorithm": "PASSTHROUGH"}
            ],
            category="function_policies",
            description="负载均衡算法策略"
        ))
        
        # 连接池策略
        dimensions.append(OrthogonalDimension(
            name="connection_pooling",
            values=[
                {"max_connections": 100, "max_pending_requests": 50},
                {"max_connections": 200, "max_pending_requests": 100},
                {"max_connections": 500, "max_pending_requests": 200},
                {"max_connections": 1000, "max_pending_requests": 500}
            ],
            category="function_policies",
            description="连接池管理策略"
        ))
        
        # 异常检测策略
        dimensions.append(OrthogonalDimension(
            name="outlier_detection",
            values=[
                {"consecutive_errors": 3, "interval": "30s"},
                {"consecutive_errors": 5, "interval": "30s"},
                {"consecutive_errors": 10, "interval": "60s"},
                {"consecutive_errors": 20, "interval": "120s"}
            ],
            category="function_policies",
            description="异常检测策略"
        ))
        
        return dimensions
    
    def _extract_scope_dimensions(self) -> List[OrthogonalDimension]:
        """提取全局/局部策略正交维度"""
        dimensions = []
        
        # 全局策略
        dimensions.append(OrthogonalDimension(
            name="global_policies",
            values=[
                {"type": "global_circuit_breaker", "enabled": True},
                {"type": "global_rate_limit", "enabled": True},
                {"type": "global_retry", "enabled": True},
                {"type": "global_timeout", "enabled": True}
            ],
            category="global_local",
            description="全局策略配置"
        ))
        
        # 局部策略
        dimensions.append(OrthogonalDimension(
            name="local_policies",
            values=[
                {"type": "local_circuit_breaker", "enabled": True},
                {"type": "local_rate_limit", "enabled": True},
                {"type": "local_retry", "enabled": True},
                {"type": "local_timeout", "enabled": True}
            ],
            category="global_local",
            description="局部策略配置"
        ))
        
        return dimensions
    
    def _extract_trigger_mechanism_dimensions(self) -> List[OrthogonalDimension]:
        """提取策略触发机制正交维度"""
        dimensions = []
        
        # 请求级触发
        dimensions.append(OrthogonalDimension(
            name="request_triggers",
            values=[
                {"type": "header_based", "trigger": "x-user-tier=vip"},
                {"type": "path_based", "trigger": "/api/v1"},
                {"type": "method_based", "trigger": "POST"},
                {"type": "query_based", "trigger": "debug=true"}
            ],
            category="trigger_mechanisms",
            description="请求级触发机制"
        ))
        
        # 服务级触发
        dimensions.append(OrthogonalDimension(
            name="service_triggers",
            values=[
                {"type": "service_health", "trigger": "health_check"},
                {"type": "service_load", "trigger": "cpu_usage>80"},
                {"type": "service_latency", "trigger": "p99>1000ms"},
                {"type": "service_errors", "trigger": "error_rate>5%"}
            ],
            category="trigger_mechanisms",
            description="服务级触发机制"
        ))
        
        return dimensions
    
    def generate_orthogonal_test_cases(self, max_cases: int = 100) -> List[OrthogonalTestCase]:
        """生成正交测试用例"""
        print("生成正交测试用例...")
        
        # 按类别分组维度
        category_groups = {}
        for dim in self.orthogonal_dimensions:
            category = dim.category
            if category not in category_groups:
                category_groups[category] = []
            category_groups[category].append(dim)
        
        # 为每个类别生成正交组合
        orthogonal_combinations = []
        
        for category, dimensions in category_groups.items():
            category_combinations = self._generate_category_orthogonal_combinations(
                dimensions, category
            )
            orthogonal_combinations.extend(category_combinations)
        
        # 限制测试用例数量
        if len(orthogonal_combinations) > max_cases:
            orthogonal_combinations = self._select_best_combinations(
                orthogonal_combinations, max_cases
            )
        
        # 生成测试用例
        test_cases = []
        for i, combination in enumerate(orthogonal_combinations):
            case_id = f"orthogonal_{i+1:04d}"
            dimensions = {}
            orthogonal_groups = []
            
            for dim_name, dim_value in combination.items():
                dimensions[dim_name] = dim_value
                # 确定正交组
                for dim in self.orthogonal_dimensions:
                    if dim.name == dim_name:
                        orthogonal_groups.append(dim.category)
                        break
            
            # 计算期望路径和覆盖分数
            expected_paths = self._calculate_orthogonal_paths(dimensions)
            coverage_score = self._calculate_coverage_score(dimensions, expected_paths)
            
            test_case = OrthogonalTestCase(
                case_id=case_id,
                dimensions=dimensions,
                orthogonal_groups=orthogonal_groups,
                expected_paths=expected_paths,
                coverage_score=coverage_score,
                description=f"正交测试用例 {i+1}"
            )
            
            test_cases.append(test_case)
        
        self.test_cases = test_cases
        print(f"生成了 {len(test_cases)} 个正交测试用例")
        
        return test_cases
    
    def _generate_category_orthogonal_combinations(self, dimensions: List[OrthogonalDimension], 
                                                 category: str) -> List[Dict[str, Any]]:
        """为特定类别生成正交组合"""
        combinations = []
        
        if len(dimensions) == 1:
            # 单个维度，直接使用所有值
            dim = dimensions[0]
            for value in dim.values:
                combinations.append({dim.name: value})
        else:
            # 多个维度，使用正交数组算法
            orthogonal_combinations = self._generate_orthogonal_array(dimensions)
            combinations.extend(orthogonal_combinations)
        
        return combinations
    
    def _generate_orthogonal_array(self, dimensions: List[OrthogonalDimension]) -> List[Dict[str, Any]]:
        """生成正交数组组合"""
        combinations = []
        
        # 获取所有维度的值
        dim_names = [dim.name for dim in dimensions]
        dim_values = [dim.values for dim in dimensions]
        
        # 计算正交数组大小（取最小公倍数）
        sizes = [len(values) for values in dim_values]
        max_size = max(sizes)
        
        # 生成正交组合
        for i in range(max_size):
            combination = {}
            for j, dim in enumerate(dimensions):
                # 循环使用维度值
                value_index = i % len(dim.values)
                combination[dim.name] = dim.values[value_index]
            combinations.append(combination)
        
        # 添加一些随机组合以增加多样性
        import random
        additional_combinations = []
        for _ in range(min(10, len(combinations) // 2)):
            combination = {}
            for dim in dimensions:
                combination[dim.name] = random.choice(dim.values)
            additional_combinations.append(combination)
        
        combinations.extend(additional_combinations)
        
        return combinations
    
    def _select_best_combinations(self, combinations: List[Dict[str, Any]], 
                                max_cases: int) -> List[Dict[str, Any]]:
        """选择最佳的正交组合"""
        # 计算每个组合的覆盖分数
        scored_combinations = []
        for combination in combinations:
            expected_paths = self._calculate_orthogonal_paths(combination)
            coverage_score = self._calculate_coverage_score(combination, expected_paths)
            scored_combinations.append((combination, coverage_score))
        
        # 按覆盖分数排序
        scored_combinations.sort(key=lambda x: x[1], reverse=True)
        
        # 选择前max_cases个
        selected = [combo for combo, score in scored_combinations[:max_cases]]
        
        return selected
    
    def _calculate_orthogonal_paths(self, dimensions: Dict[str, Any]) -> List[str]:
        """计算正交测试用例的期望路径"""
        paths = []
        
        for dim_name, dim_value in dimensions.items():
            # 根据维度类型生成路径
            if "matching" in dim_name:
                if isinstance(dim_value, dict):
                    if "key" in dim_value:
                        paths.append(f"match_{dim_value['key']}_{dim_value['value']}")
                    elif "type" in dim_value:
                        paths.append(f"match_{dim_value['type']}_{dim_value['value']}")
            
            elif "policy" in dim_name or "balancing" in dim_name or "pooling" in dim_name:
                if isinstance(dim_value, dict):
                    if "algorithm" in dim_value:
                        paths.append(f"policy_{dim_value['algorithm']}")
                    elif "max_connections" in dim_value:
                        paths.append(f"policy_conn_{dim_value['max_connections']}")
                    elif "consecutive_errors" in dim_value:
                        paths.append(f"policy_errors_{dim_value['consecutive_errors']}")
            
            elif "trigger" in dim_name:
                if isinstance(dim_value, dict):
                    paths.append(f"trigger_{dim_value['type']}_{dim_value['trigger']}")
        
        return paths
    
    def _calculate_coverage_score(self, dimensions: Dict[str, Any], 
                                expected_paths: List[str]) -> float:
        """计算覆盖分数"""
        # 基础分数
        base_score = len(expected_paths) * 0.1
        
        # 正交性加分
        orthogonal_bonus = len(set(dimensions.keys())) * 0.05
        
        # 多样性加分
        diversity_bonus = 0
        for dim_name, dim_value in dimensions.items():
            if isinstance(dim_value, dict):
                diversity_bonus += len(dim_value) * 0.01
        
        total_score = base_score + orthogonal_bonus + diversity_bonus
        return min(total_score, 1.0)  # 限制在0-1之间
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        if not self.test_cases:
            return {}
        
        total_cases = len(self.test_cases)
        total_paths = set()
        category_coverage = {}
        
        for case in self.test_cases:
            total_paths.update(case.expected_paths)
            for group in case.orthogonal_groups:
                if group not in category_coverage:
                    category_coverage[group] = set()
                category_coverage[group].update(case.expected_paths)
        
        avg_coverage_score = sum(case.coverage_score for case in self.test_cases) / total_cases
        
        return {
            "method": "orthogonal",
            "total_cases": total_cases,
            "total_unique_paths": len(total_paths),
            "average_coverage_score": avg_coverage_score,
            "category_coverage": {k: len(v) for k, v in category_coverage.items()},
            "orthogonal_principles_applied": [
                "match_conditions",
                "function_policies", 
                "global_local",
                "trigger_mechanisms"
            ]
        }
    
    def export_test_cases(self, output_file: str):
        """导出测试用例到文件"""
        export_data = {
            "method": "orthogonal",
            "statistics": self.get_statistics(),
            "orthogonal_principles": {
                "match_conditions": "匹配条件维度正交",
                "function_policies": "功能策略间正交", 
                "global_local": "全局/局部策略正交",
                "trigger_mechanisms": "策略触发机制正交"
            },
            "test_cases": [
                {
                    "case_id": case.case_id,
                    "dimensions": case.dimensions,
                    "orthogonal_groups": case.orthogonal_groups,
                    "expected_paths": case.expected_paths,
                    "coverage_score": case.coverage_score,
                    "description": case.description
                }
                for case in self.test_cases
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"正交测试用例已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="正交测试用例生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--max-cases", type=int, default=100, help="最大测试用例数")
    
    args = parser.parse_args()
    
    # 加载配置数据（这里简化处理）
    config_data = {
        "services": [
            {"name": "productpage", "namespace": "default"},
            {"name": "reviews", "namespace": "default"},
            {"name": "ratings", "namespace": "default"}
        ],
        "destination_rules": [
            {
                "spec": {
                    "host": "reviews",
                    "subsets": [
                        {"name": "v1"},
                        {"name": "v2"}
                    ]
                }
            }
        ]
    }
    
    generator = OrthogonalGenerator(config_data)
    test_cases = generator.generate_orthogonal_test_cases(args.max_cases)
    
    # 打印统计信息
    stats = generator.get_statistics()
    print(f"\n生成统计:")
    print(f"  总用例数: {stats['total_cases']}")
    print(f"  唯一路径数: {stats['total_unique_paths']}")
    print(f"  平均覆盖分数: {stats['average_coverage_score']:.3f}")
    print(f"  类别覆盖: {stats['category_coverage']}")
    
    # 导出结果
    if args.output:
        generator.export_test_cases(args.output)
    else:
        print(f"\n前5个测试用例示例:")
        for i, case in enumerate(test_cases[:5]):
            print(f"  {case.case_id}: 覆盖分数={case.coverage_score:.3f}, 正交组={case.orthogonal_groups}")


if __name__ == "__main__":
    main()
