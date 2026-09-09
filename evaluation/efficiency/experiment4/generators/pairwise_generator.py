#!/usr/bin/env python3
"""
Pairwise测试用例生成器 - 基于配对覆盖生成测试用例
"""

import json
import itertools
import random
from typing import Dict, List, Any, Tuple, Set
from dataclasses import dataclass
from path_calculator import get_total_possible_paths, calculate_cumulative_coverage


@dataclass
class PairwiseTestCase:
    """Pairwise测试用例定义"""
    case_id: str
    dimensions: Dict[str, Any]
    pairwise_combinations: List[Tuple[str, Any, str, Any]]
    expected_paths: List[str]
    coverage_value: int
    description: str = ""


class PairwiseGenerator:
    """Pairwise测试用例生成器"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化生成器"""
        self.config_data = config_data
        self.dimensions = self._extract_dimensions()
        self.test_cases = []
    
    def _extract_dimensions(self) -> Dict[str, List[Any]]:
        """从配置文件中提取测试维度"""
        dimensions = {
            "headers": self._extract_headers(),
            "uri_patterns": self._extract_uri_patterns(),
            "destinations": self._extract_destinations(),
            "load_balancing": self._extract_load_balancing(),
            "weights": self._extract_weights(),
            "policies": self._extract_policies()
        }
        
        return dimensions
    
    def _extract_headers(self) -> List[Dict[str, Any]]:
        """从配置中提取header匹配条件"""
        headers = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        matches = route.get("match", [])
                        for match in matches:
                            match_headers = match.get("headers", {})
                            for key, rule in match_headers.items():
                                if "exact" in rule:
                                    headers.append({"key": key, "value": rule["exact"]})
                                elif "prefix" in rule:
                                    headers.append({"key": key, "value": rule["prefix"]})
        
        # 如果没有找到headers，添加一些默认的
        if not headers:
            headers = [
                {"key": "end-user", "value": "jason"},
                {"key": "end-user", "value": "admin"}
            ]
        
        return headers
    
    def _extract_uri_patterns(self) -> List[Dict[str, Any]]:
        """从配置中提取URI匹配模式"""
        uri_patterns = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        matches = route.get("match", [])
                        for match in matches:
                            uri = match.get("uri", {})
                            if "prefix" in uri:
                                uri_patterns.append({"type": "prefix", "value": uri["prefix"]})
                            elif "exact" in uri:
                                uri_patterns.append({"type": "exact", "value": uri["exact"]})
                            elif "regex" in uri:
                                uri_patterns.append({"type": "regex", "value": uri["regex"]})
        
        # 如果没有找到URI模式，添加默认的
        if not uri_patterns:
            uri_patterns = [
                {"type": "prefix", "value": "/"},
                {"type": "exact", "value": "/"}
            ]
        
        return uri_patterns
    
    def _extract_destinations(self) -> List[Dict[str, Any]]:
        """从配置中提取目标服务"""
        destinations = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        routes = route.get("route", [])
                        for r in routes:
                            dest = r.get("destination", {})
                            host = dest.get("host", "")
                            subset = dest.get("subset", "")
                            if host:
                                destinations.append({"host": host, "subset": subset if subset else None})
        
        # 如果没有找到目标，添加默认的
        if not destinations:
            destinations = [
                {"host": "productpage", "subset": None},
                {"host": "reviews", "subset": "v1"}
            ]
        
        return destinations
    
    def _extract_load_balancing(self) -> List[Dict[str, Any]]:
        """从配置中提取负载均衡策略"""
        load_balancing = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "DestinationRule":
                    spec = doc.get("spec", {})
                    traffic_policy = spec.get("trafficPolicy", {})
                    lb = traffic_policy.get("loadBalancer", {})
                    if lb and "simple" in lb:
                        load_balancing.append({"algorithm": lb["simple"]})
        
        # 如果没有找到负载均衡策略，添加默认的
        if not load_balancing:
            load_balancing = [
                {"algorithm": "ROUND_ROBIN"},
                {"algorithm": "LEAST_CONN"}
            ]
        
        return load_balancing
    
    def _extract_weights(self) -> List[Dict[str, Any]]:
        """从配置中提取权重分配"""
        weights = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        routes = route.get("route", [])
                        if len(routes) > 1:  # 有多个路由目标
                            weight_values = [r.get("weight", 0) for r in routes]
                            if len(weight_values) >= 2:
                                weights.append({
                                    "primary": weight_values[0],
                                    "secondary": weight_values[1] if len(weight_values) > 1 else 0
                                })
        
        # 如果没有找到权重分配，添加默认的
        if not weights:
            weights = [
                {"primary": 100, "secondary": 0},
                {"primary": 90, "secondary": 10}
            ]
        
        return weights
    
    def _extract_policies(self) -> List[Dict[str, Any]]:
        """从配置中提取策略"""
        policies = []
        
        if isinstance(self.config_data, list):
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "DestinationRule":
                    spec = doc.get("spec", {})
                    traffic_policy = spec.get("trafficPolicy", {})
                    
                    if "connectionPool" in traffic_policy:
                        policies.append({"type": "connection_pool", "enabled": True})
                    if "outlierDetection" in traffic_policy:
                        policies.append({"type": "outlier_detection", "enabled": True})
        
        # 如果没有找到策略，添加默认的
        if not policies:
            policies = [
                {"type": "connection_pool", "enabled": True},
                {"type": "outlier_detection", "enabled": False}
            ]
        
        return policies
    
    def generate_pairwise_test_cases(self, max_cases: int = 50) -> List[PairwiseTestCase]:
        """生成Pairwise测试用例"""
        print("生成Pairwise测试用例...")
        
        # 生成所有可能的配对组合
        pairwise_combinations = self._generate_all_pairwise_combinations()
        
        # 使用贪心算法选择最优的测试用例集合
        selected_cases = self._greedy_pairwise_selection(pairwise_combinations, max_cases)
        
        # 生成测试用例
        test_cases = []
        for i, case_data in enumerate(selected_cases):
            case_id = f"pairwise_{i+1:04d}"
            dimensions = case_data["dimensions"]
            pairwise_combinations = case_data["pairwise_combinations"]
            coverage_value = case_data["coverage_value"]
            
            # 计算期望路径
            expected_paths = self._calculate_expected_paths(dimensions)
            
            test_case = PairwiseTestCase(
                case_id=case_id,
                dimensions=dimensions,
                pairwise_combinations=pairwise_combinations,
                expected_paths=expected_paths,
                coverage_value=coverage_value,
                description=f"Pairwise测试用例 {i+1}"
            )
            
            test_cases.append(test_case)
        
        self.test_cases = test_cases
        print(f"生成了 {len(test_cases)} 个Pairwise测试用例")
        
        return test_cases
    
    def _generate_all_pairwise_combinations(self) -> List[Dict[str, Any]]:
        """生成所有可能的配对组合"""
        combinations = []
        dimension_names = list(self.dimensions.keys())
        
        # 生成所有两两配对
        for i in range(len(dimension_names)):
            for j in range(i + 1, len(dimension_names)):
                dim1_name = dimension_names[i]
                dim2_name = dimension_names[j]
                
                dim1_values = self.dimensions[dim1_name]
                dim2_values = self.dimensions[dim2_name]
                
                # 生成两个维度的笛卡尔积
                for val1 in dim1_values:
                    for val2 in dim2_values:
                        combination = {
                            "dimensions": {
                                dim1_name: val1,
                                dim2_name: val2
                            },
                            "pairwise_combinations": [
                                (dim1_name, val1, dim2_name, val2)
                            ],
                            "coverage_value": 1
                        }
                        combinations.append(combination)
        
        return combinations
    
    def _greedy_pairwise_selection(self, all_combinations: List[Dict[str, Any]], 
                                 max_cases: int) -> List[Dict[str, Any]]:
        """使用贪心算法选择最优的测试用例集合"""
        selected_cases = []
        covered_pairs = set()
        
        # 计算每个组合能覆盖的新配对数量
        while len(selected_cases) < max_cases and len(covered_pairs) < self._get_total_pair_count():
            best_case = None
            best_coverage = 0
            
            for combination in all_combinations:
                # 计算这个组合能覆盖的新配对数量
                new_pairs = 0
                for pair in combination["pairwise_combinations"]:
                    # 将pair转换为可哈希的元组
                    if isinstance(pair, (list, tuple)):
                        # 处理元组中的每个元素
                        converted_elements = []
                        for elem in pair:
                            if isinstance(elem, dict):
                                converted_elements.append(tuple(sorted(elem.items())))
                            else:
                                converted_elements.append(elem)
                        pair_tuple = tuple(converted_elements)
                    elif isinstance(pair, dict):
                        pair_tuple = tuple(sorted(pair.items()))
                    else:
                        pair_tuple = pair
                    if pair_tuple not in covered_pairs:
                        new_pairs += 1
                
                if new_pairs > best_coverage:
                    best_coverage = new_pairs
                    best_case = combination
            
            if best_case is None:
                break
            
            # 添加最佳组合
            selected_cases.append(best_case)
            
            # 更新已覆盖的配对
            for pair in best_case["pairwise_combinations"]:
                # 将pair转换为可哈希的元组
                if isinstance(pair, (list, tuple)):
                    # 处理元组中的每个元素
                    converted_elements = []
                    for elem in pair:
                        if isinstance(elem, dict):
                            converted_elements.append(tuple(sorted(elem.items())))
                        else:
                            converted_elements.append(elem)
                    pair_tuple = tuple(converted_elements)
                elif isinstance(pair, dict):
                    pair_tuple = tuple(sorted(pair.items()))
                else:
                    pair_tuple = pair
                covered_pairs.add(pair_tuple)
            
            # 更新组合的覆盖值
            best_case["coverage_value"] = best_coverage
        
        # 如果还有未覆盖的配对，尝试添加更多组合
        if len(selected_cases) < max_cases:
            remaining_combinations = [c for c in all_combinations if c not in selected_cases]
            random.shuffle(remaining_combinations)
            
            for combination in remaining_combinations[:max_cases - len(selected_cases)]:
                selected_cases.append(combination)
        
        return selected_cases
    
    def _get_total_pair_count(self) -> int:
        """计算总的配对数量"""
        dimension_names = list(self.dimensions.keys())
        total_pairs = 0
        
        for i in range(len(dimension_names)):
            for j in range(i + 1, len(dimension_names)):
                dim1_count = len(self.dimensions[dimension_names[i]])
                dim2_count = len(self.dimensions[dimension_names[j]])
                total_pairs += dim1_count * dim2_count
        
        return total_pairs
    
    
    def _calculate_expected_paths(self, dimensions: Dict[str, Any]) -> List[str]:
        """计算期望路径"""
        paths = []
        
        for dim_name, dim_value in dimensions.items():
            if dim_name == "headers":
                if isinstance(dim_value, dict):
                    paths.append(f"header_{dim_value['key']}_{dim_value['value']}")
            
            elif dim_name == "uri_patterns":
                if isinstance(dim_value, dict):
                    paths.append(f"uri_{dim_value['type']}_{dim_value['value']}")
            
            elif dim_name == "destinations":
                if isinstance(dim_value, dict):
                    host = dim_value.get("host", "")
                    subset = dim_value.get("subset", "")
                    if subset:
                        paths.append(f"route_{host}_{subset}")
                    else:
                        paths.append(f"route_{host}")
            
            elif dim_name == "load_balancing":
                if isinstance(dim_value, dict):
                    paths.append(f"lb_{dim_value['algorithm']}")
            
            elif dim_name == "weights":
                if isinstance(dim_value, dict):
                    primary = dim_value.get("primary", 0)
                    secondary = dim_value.get("secondary", 0)
                    paths.append(f"weight_{primary}_{secondary}")
            
            elif dim_name == "policies":
                if isinstance(dim_value, dict):
                    policy_type = dim_value.get("type", "")
                    if "enabled" in dim_value:
                        paths.append(f"policy_{policy_type}_{dim_value['enabled']}")
                    else:
                        for key, value in dim_value.items():
                            if key != "type":
                                paths.append(f"policy_{policy_type}_{key}_{value}")
        
        return paths
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        if not self.test_cases:
            return {}
        
        total_cases = len(self.test_cases)
        total_paths = set()
        total_pairwise_combinations = set()
        
        for case in self.test_cases:
            total_paths.update(case.expected_paths)
            # 处理pairwise_combinations中的不可哈希类型
            for pair in case.pairwise_combinations:
                if isinstance(pair, (list, tuple)):
                    # 处理元组中的每个元素
                    converted_elements = []
                    for elem in pair:
                        if isinstance(elem, dict):
                            converted_elements.append(tuple(sorted(elem.items())))
                        else:
                            converted_elements.append(elem)
                    pair_tuple = tuple(converted_elements)
                elif isinstance(pair, dict):
                    pair_tuple = tuple(sorted(pair.items()))
                else:
                    pair_tuple = pair
                total_pairwise_combinations.add(pair_tuple)
        
        # 计算配对覆盖率
        total_possible_pairs = self._get_total_pair_count()
        covered_pairs = len(total_pairwise_combinations)
        pairwise_coverage = covered_pairs / total_possible_pairs if total_possible_pairs > 0 else 0
        
        # 计算累积覆盖率
        total_possible_paths = get_total_possible_paths(self.config_data)
        cumulative_coverage_score = calculate_cumulative_coverage(self.test_cases, total_possible_paths)
        
        avg_coverage_value = sum(case.coverage_value for case in self.test_cases) / total_cases
        
        return {
            "method": "pairwise",
            "total_cases": total_cases,
            "total_unique_paths": len(total_paths),
            "cumulative_coverage_score": cumulative_coverage_score,
            "pairwise_coverage": pairwise_coverage,
            "covered_pairs": covered_pairs,
            "total_possible_pairs": total_possible_pairs,
            "average_coverage_value": avg_coverage_value
        }
    
    def export_test_cases(self, output_file: str):
        """导出测试用例到文件"""
        export_data = {
            "method": "pairwise",
            "statistics": self.get_statistics(),
            "test_cases": [
                {
                    "case_id": case.case_id,
                    "dimensions": case.dimensions,
                    "pairwise_combinations": case.pairwise_combinations,
                    "expected_paths": case.expected_paths,
                    "coverage_value": case.coverage_value,
                    "description": case.description
                }
                for case in self.test_cases
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"Pairwise测试用例已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Pairwise测试用例生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--max-cases", type=int, default=50, help="最大测试用例数")
    
    args = parser.parse_args()
    
    # 加载配置文件
    import yaml
    with open(args.config, 'r', encoding='utf-8') as f:
        config_docs = list(yaml.safe_load_all(f))
    
    generator = PairwiseGenerator(config_docs)
    test_cases = generator.generate_pairwise_test_cases(args.max_cases)
    
    # 打印统计信息
    stats = generator.get_statistics()
    print(f"\n生成统计:")
    print(f"  总用例数: {stats['total_cases']}")
    print(f"  唯一路径数: {stats['total_unique_paths']}")
    print(f"  累积覆盖率: {stats['cumulative_coverage_score']:.3f}")
    print(f"  配对覆盖率: {stats['pairwise_coverage']:.3f}")
    print(f"  覆盖配对数: {stats['covered_pairs']}/{stats['total_possible_pairs']}")
    print(f"  平均覆盖值: {stats['average_coverage_value']:.2f}")
    
    # 导出结果
    if args.output:
        generator.export_test_cases(args.output)
    else:
        print(f"\n前5个测试用例示例:")
        for i, case in enumerate(test_cases[:5]):
            print(f"  {case.case_id}: 覆盖值={case.coverage_value}, 配对数={len(case.pairwise_combinations)}")


if __name__ == "__main__":
    main()
