#!/usr/bin/env python3
"""
穷举测试用例生成器 - 全排列生成所有可能的测试用例组合
"""

import itertools
import json
import yaml
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from path_calculator import get_total_possible_paths, calculate_cumulative_coverage


@dataclass
class TestDimension:
    """测试维度定义"""
    name: str
    values: List[Any]
    description: str = ""


@dataclass
class TestCase:
    """测试用例定义"""
    case_id: str
    dimensions: Dict[str, Any]
    expected_paths: List[str]
    description: str = ""


class ExhaustiveGenerator:
    """穷举测试用例生成器"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化生成器"""
        self.config_data = config_data
        self.dimensions = self._extract_dimensions()
        self.test_cases = []
    
    def _extract_dimensions(self) -> List[TestDimension]:
        """从配置中提取测试维度"""
        dimensions = []
        
        # 1. 从VirtualService中提取匹配条件
        match_conditions = self._extract_match_conditions_from_vs()
        if match_conditions:
            dimensions.append(TestDimension(
                name="match_conditions",
                values=match_conditions,
                description="HTTP匹配条件组合"
            ))
        
        # 2. 从VirtualService中提取路由目标
        route_destinations = self._extract_route_destinations_from_vs()
        if route_destinations:
            dimensions.append(TestDimension(
                name="route_destinations", 
                values=route_destinations,
                description="路由目标服务组合"
            ))
        
        # 3. 从VirtualService中提取权重分配
        weight_combinations = self._extract_weight_combinations_from_vs()
        if weight_combinations:
            dimensions.append(TestDimension(
                name="weight_combinations",
                values=weight_combinations,
                description="流量权重分配组合"
            ))
        
        # 4. 从DestinationRule中提取策略类型
        policy_types = self._extract_policy_types_from_dr()
        if policy_types:
            dimensions.append(TestDimension(
                name="policy_types",
                values=policy_types,
                description="流量管理策略类型"
            ))
        
        return dimensions
    
    def _extract_match_conditions_from_vs(self) -> List[Dict[str, Any]]:
        """从VirtualService中提取HTTP匹配条件"""
        conditions = []
        
        # 从配置数据中提取匹配条件
        if isinstance(self.config_data, list):
            # 如果是YAML文档列表
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        matches = route.get("match", [])
                        for match in matches:
                            # 提取header匹配
                            headers = match.get("headers", {})
                            for key, rule in headers.items():
                                if "exact" in rule:
                                    conditions.append({"type": "headers", "key": key, "value": rule["exact"]})
                                elif "prefix" in rule:
                                    conditions.append({"type": "headers", "key": key, "value": rule["prefix"]})
                                elif "regex" in rule:
                                    conditions.append({"type": "headers", "key": key, "value": rule["regex"]})
                            
                            # 提取URI匹配
                            uri = match.get("uri", {})
                            for uri_type, uri_value in uri.items():
                                conditions.append({"type": "uri", "match_type": uri_type, "value": uri_value})
        else:
            # 如果是字典格式（兼容旧格式）
            virtual_services = self.config_data.get("virtual_services", [])
            for vs in virtual_services:
                http_routes = vs.get("spec", {}).get("http", [])
                for route in http_routes:
                    matches = route.get("match", [])
                    for match in matches:
                        # 提取header匹配
                        headers = match.get("headers", {})
                        for key, rule in headers.items():
                            if "exact" in rule:
                                conditions.append({"type": "headers", "key": key, "value": rule["exact"]})
                            elif "prefix" in rule:
                                conditions.append({"type": "headers", "key": key, "value": rule["prefix"]})
                            elif "regex" in rule:
                                conditions.append({"type": "headers", "key": key, "value": rule["regex"]})
                        
                        # 提取URI匹配
                        uri = match.get("uri", {})
                        for uri_type, uri_value in uri.items():
                            conditions.append({"type": "uri", "match_type": uri_type, "value": uri_value})
        
        # 如果没有找到匹配条件，添加一些默认的
        if not conditions:
            conditions = [
                {"type": "headers", "key": "end-user", "value": "jason"},
                {"type": "uri", "match_type": "prefix", "value": "/api/v1"}
            ]
        
        return conditions
    
    def _extract_route_destinations_from_vs(self) -> List[Dict[str, Any]]:
        """从VirtualService中提取路由目标"""
        destinations = []
        
        if isinstance(self.config_data, list):
            # 处理YAML文档列表
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        route_destinations = route.get("route", [])
                        for dest in route_destinations:
                            dest_info = dest.get("destination", {})
                            host = dest_info.get("host", "")
                            subset = dest_info.get("subset", "")
                            port = dest_info.get("port", {}).get("number", 8080)
                            
                            if host:
                                destinations.append({
                                    "host": host,
                                    "port": port,
                                    "subset": subset if subset else None
                                })
        else:
            # 处理字典格式
            virtual_services = self.config_data.get("virtual_services", [])
            for vs in virtual_services:
                http_routes = vs.get("spec", {}).get("http", [])
                for route in http_routes:
                    route_destinations = route.get("route", [])
                    for dest in route_destinations:
                        dest_info = dest.get("destination", {})
                        host = dest_info.get("host", "")
                        subset = dest_info.get("subset", "")
                        port = dest_info.get("port", {}).get("number", 8080)
                        
                        if host:
                            destinations.append({
                                "host": host,
                                "port": port,
                                "subset": subset if subset else None
                            })
        
        # 如果没有找到路由目标，添加一些默认的
        if not destinations:
            destinations = [
                {"host": "productpage", "port": 8080, "subset": None},
                {"host": "reviews", "port": 8080, "subset": "v1"},
                {"host": "reviews", "port": 8080, "subset": "v2"}
            ]
        
        return destinations
    
    def _extract_weight_combinations_from_vs(self) -> List[Dict[str, Any]]:
        """从VirtualService中提取权重分配组合"""
        weight_combinations = []
        
        if isinstance(self.config_data, list):
            # 处理YAML文档列表
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    spec = doc.get("spec", {})
                    http_routes = spec.get("http", [])
                    for route in http_routes:
                        routes = route.get("route", [])
                        if len(routes) > 1:  # 有多个路由目标，表示流量分割
                            weights = []
                            destinations = []
                            for r in routes:
                                weight = r.get("weight", 0)
                                dest = r.get("destination", {})
                                weights.append(weight)
                                destinations.append({
                                    "host": dest.get("host", ""),
                                    "subset": dest.get("subset", "")
                                })
                            weight_combinations.append({
                                "weights": weights,
                                "destinations": destinations
                            })
        else:
            # 处理字典格式
            virtual_services = self.config_data.get("virtual_services", [])
            for vs in virtual_services:
                http_routes = vs.get("spec", {}).get("http", [])
                for route in http_routes:
                    route_destinations = route.get("route", [])
                    if len(route_destinations) > 1:  # 多目标分流
                        weights = [dest.get("weight", 0) for dest in route_destinations]
                        if sum(weights) > 0:
                            weight_combinations.append({
                                "weights": weights,
                                "destinations": [dest.get("destination", {}) for dest in route_destinations]
                            })
        
        # 如果没有找到权重组合，添加一些默认的
        if not weight_combinations:
            weight_combinations = [
                {"weights": [100], "destinations": [{"host": "productpage", "subset": "v1"}]},
                {"weights": [90, 10], "destinations": [{"host": "reviews", "subset": "v1"}, {"host": "reviews", "subset": "v2"}]},
                {"weights": [50, 50], "destinations": [{"host": "reviews", "subset": "v1"}, {"host": "reviews", "subset": "v2"}]}
            ]
        
        return weight_combinations
    
    def _extract_policy_types_from_dr(self) -> List[Dict[str, Any]]:
        """从DestinationRule中提取策略类型"""
        policy_types = []
        
        if isinstance(self.config_data, list):
            # 处理YAML文档列表
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "DestinationRule":
                    spec = doc.get("spec", {})
                    # 提取负载均衡策略
                    if "trafficPolicy" in spec:
                        traffic_policy = spec["trafficPolicy"]
                        if "loadBalancer" in traffic_policy:
                            lb = traffic_policy["loadBalancer"]
                            policy_types.append({
                                "type": "load_balancer",
                                "algorithm": lb.get("simple", "ROUND_ROBIN")
                            })
                        if "connectionPool" in traffic_policy:
                            cp = traffic_policy["connectionPool"]
                            policy_types.append({
                                "type": "connection_pool",
                                "max_connections": cp.get("tcp", {}).get("maxConnections", 100)
                            })
                        if "outlierDetection" in traffic_policy:
                            od = traffic_policy["outlierDetection"]
                            policy_types.append({
                                "type": "outlier_detection",
                                "consecutive_errors": od.get("consecutiveErrors", 3)
                            })
        else:
            # 处理字典格式
            destination_rules = self.config_data.get("destination_rules", [])
            for dr in destination_rules:
                spec = dr.get("spec", {})
                traffic_policy = spec.get("trafficPolicy", {})
                
                # 负载均衡策略
                load_balancer = traffic_policy.get("loadBalancer", {})
                if load_balancer:
                    algorithm = load_balancer.get("simple", "")
                    policy_types.append({"type": "load_balancer", "algorithm": algorithm})
                
                # 连接池策略
                connection_pool = traffic_policy.get("connectionPool", {})
                if connection_pool:
                    tcp = connection_pool.get("tcp", {})
                    http = connection_pool.get("http", {})
                    max_connections = tcp.get("maxConnections", 0)
                    max_pending = http.get("http1MaxPendingRequests", 0)
                    policy_types.append({
                        "type": "connection_pool", 
                        "max_connections": max_connections,
                        "max_pending_requests": max_pending
                    })
                
                # 异常检测策略
                outlier_detection = traffic_policy.get("outlierDetection", {})
                if outlier_detection:
                    consecutive_errors = outlier_detection.get("consecutiveErrors", 
                                                            outlier_detection.get("consecutive5xxErrors", 0))
                    policy_types.append({
                        "type": "outlier_detection", 
                        "consecutive_errors": consecutive_errors
                    })
        
        # 如果没有找到策略，添加一些默认的
        if not policy_types:
            policy_types = [
                {"type": "load_balancer", "algorithm": "ROUND_ROBIN"},
                {"type": "connection_pool", "max_connections": 100},
                {"type": "outlier_detection", "consecutive_errors": 3}
            ]
        
        return policy_types
    
    def _get_subsets_for_service(self, service_name: str) -> List[str]:
        """获取服务的子集"""
        subsets = []
        
        # 从DestinationRule中查找子集
        destination_rules = self.config_data.get("destination_rules", [])
        for dr in destination_rules:
            if dr.get("spec", {}).get("host") == service_name:
                dr_subsets = dr.get("spec", {}).get("subsets", [])
                for subset in dr_subsets:
                    subset_name = subset.get("name", "")
                    if subset_name:
                        subsets.append(subset_name)
        
        # 添加默认子集
        if not subsets:
            subsets = ["v1", "v2", "v3"]
        
        return subsets
    
    def generate_test_cases(self) -> List[TestCase]:
        """生成穷举测试用例"""
        print("生成穷举测试用例...")
        
        # 获取所有维度的值
        dimension_values = [dim.values for dim in self.dimensions]
        
        # 生成笛卡尔积
        cartesian_product = list(itertools.product(*dimension_values))
        
        print(f"总共生成 {len(cartesian_product)} 个测试用例")
        
        test_cases = []
        for i, combination in enumerate(cartesian_product):
            # 构建测试用例
            case_id = f"exhaustive_{i+1:06d}"
            dimensions = {}
            
            for j, dim in enumerate(self.dimensions):
                dimensions[dim.name] = combination[j]
            
            # 计算期望覆盖的路径
            expected_paths = self._calculate_expected_paths(dimensions)
            
            test_case = TestCase(
                case_id=case_id,
                dimensions=dimensions,
                expected_paths=expected_paths,
                description=f"穷举测试用例 {i+1}"
            )
            
            test_cases.append(test_case)
        
        self.test_cases = test_cases
        return test_cases
    
    def _calculate_expected_paths(self, dimensions: Dict[str, Any]) -> List[str]:
        """计算测试用例期望覆盖的配置路径"""
        paths = []
        
        # 根据维度组合计算应该触发的路径
        match_conditions = dimensions.get("match_conditions", {})
        route_destinations = dimensions.get("route_destinations", {})
        weight_combinations = dimensions.get("weight_combinations", {})
        policy_types = dimensions.get("policy_types", {})
        
        # 生成路径标识符
        if match_conditions:
            condition_type = match_conditions.get("type", "")
            condition_value = match_conditions.get("value") or match_conditions.get("prefix") or match_conditions.get("regex", "")
            paths.append(f"match_{condition_type}_{condition_value}")
        
        if route_destinations:
            host = route_destinations.get("host", "")
            subset = route_destinations.get("subset", "")
            if subset:
                paths.append(f"route_{host}_{subset}")
            else:
                paths.append(f"route_{host}")
        
        if weight_combinations:
            primary_weight = weight_combinations.get("primary", 0)
            secondary_weight = weight_combinations.get("secondary", 0)
            paths.append(f"weight_{primary_weight}_{secondary_weight}")
        
        if policy_types:
            policy_type = policy_types.get("type", "")
            policy_value = policy_types.get("algorithm") or policy_types.get("max_connections") or policy_types.get("consecutive_errors")
            paths.append(f"policy_{policy_type}_{policy_value}")
        
        return paths
    
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        if not self.test_cases:
            return {}
        
        total_cases = len(self.test_cases)
        total_paths = set()
        
        for case in self.test_cases:
            total_paths.update(case.expected_paths)
        
        # 计算累积覆盖率
        total_possible_paths = get_total_possible_paths(self.config_data)
        cumulative_coverage_score = calculate_cumulative_coverage(self.test_cases, total_possible_paths)
        
        dimension_counts = {}
        for dim in self.dimensions:
            dimension_counts[dim.name] = len(dim.values)
        
        return {
            "method": "exhaustive",
            "total_cases": total_cases,
            "total_unique_paths": len(total_paths),
            "cumulative_coverage_score": cumulative_coverage_score,
            "dimension_counts": dimension_counts,
            "cartesian_product_size": total_cases,
            "average_paths_per_case": sum(len(case.expected_paths) for case in self.test_cases) / total_cases
        }
    
    def export_test_cases(self, output_file: str):
        """导出测试用例到文件"""
        export_data = {
            "method": "exhaustive",
            "statistics": self.get_statistics(),
            "test_cases": [
                {
                    "case_id": case.case_id,
                    "dimensions": case.dimensions,
                    "expected_paths": case.expected_paths,
                    "description": case.description
                }
                for case in self.test_cases
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"穷举测试用例已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="穷举测试用例生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    # 加载配置文件
    with open(args.config, 'r', encoding='utf-8') as f:
        config_docs = list(yaml.safe_load_all(f))
    
    generator = ExhaustiveGenerator(config_docs)
    test_cases = generator.generate_test_cases()
    
    # 打印统计信息
    stats = generator.get_statistics()
    print(f"\n生成统计:")
    print(f"  总用例数: {stats['total_cases']}")
    print(f"  唯一路径数: {stats['total_unique_paths']}")
    print(f"  累积覆盖率: {stats['cumulative_coverage_score']:.3f}")
    print(f"  平均每用例路径数: {stats['average_paths_per_case']:.2f}")
    
    # 导出结果
    if args.output:
        generator.export_test_cases(args.output)
    else:
        print(f"\n前5个测试用例示例:")
        for i, case in enumerate(test_cases[:5]):
            print(f"  {case.case_id}: {case.dimensions}")


if __name__ == "__main__":
    main()
