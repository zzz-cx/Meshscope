#!/usr/bin/env python3
"""
覆盖率计算器 - 计算测试用例集合对配置路径的覆盖率
"""

import json
import yaml
from typing import Dict, List, Any, Set, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConfigPath:
    """配置路径定义"""
    path_id: str
    path_type: str  # match_condition, route_destination, policy_config, etc.
    service_name: str
    resource_name: str
    path_description: str
    dependencies: List[str]  # 依赖的其他路径
    importance: float  # 路径重要性权重


@dataclass
class CoverageResult:
    """覆盖率计算结果"""
    method: str
    total_paths: int
    covered_paths: int
    coverage_percentage: float
    uncovered_paths: List[str]
    path_coverage_details: Dict[str, Any]
    execution_results: Dict[str, Any]


class CoverageCalculator:
    """覆盖率计算器"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化覆盖率计算器"""
        self.config_data = config_data
        self.total_paths = self._extract_total_paths()
        self.path_dependencies = self._build_dependency_graph()
    
    def _extract_total_paths(self) -> List[ConfigPath]:
        """从配置中提取所有可能的路径"""
        paths = []
        
        # 1. 提取VirtualService中的匹配条件和路由路径
        virtual_services = self.config_data.get("virtual_services", [])
        for vs in virtual_services:
            vs_name = vs.get("name", "")
            spec = vs.get("spec", {})
            
            # 提取HTTP路由
            http_routes = spec.get("http", [])
            for i, route in enumerate(http_routes):
                # 匹配条件路径
                matches = route.get("match", [])
                for j, match in enumerate(matches):
                    # Header匹配
                    headers = match.get("headers", {})
                    for header_key, header_value in headers.items():
                        path_id = f"vs_{vs_name}_route_{i}_match_{j}_header_{header_key}"
                        paths.append(ConfigPath(
                            path_id=path_id,
                            path_type="header_match",
                            service_name=vs_name,
                            resource_name="VirtualService",
                            path_description=f"Header匹配: {header_key}={header_value.get('exact', '')}",
                            dependencies=[],
                            importance=1.0
                        ))
                    
                    # URI匹配
                    uri = match.get("uri", {})
                    if uri:
                        uri_type = list(uri.keys())[0]
                        uri_value = uri[uri_type]
                        path_id = f"vs_{vs_name}_route_{i}_match_{j}_uri_{uri_type}"
                        paths.append(ConfigPath(
                            path_id=path_id,
                            path_type="uri_match",
                            service_name=vs_name,
                            resource_name="VirtualService",
                            path_description=f"URI匹配: {uri_type}={uri_value}",
                            dependencies=[],
                            importance=1.0
                        ))
                
                # 路由目标路径
                route_destinations = route.get("route", [])
                for k, dest in enumerate(route_destinations):
                    host = dest.get("destination", {}).get("host", "")
                    subset = dest.get("destination", {}).get("subset", "")
                    weight = dest.get("weight", 0)
                    
                    path_id = f"vs_{vs_name}_route_{i}_dest_{k}"
                    paths.append(ConfigPath(
                        path_id=path_id,
                        path_type="route_destination",
                        service_name=vs_name,
                        resource_name="VirtualService",
                        path_description=f"路由到: {host}" + (f"/{subset}" if subset else "") + f" (权重: {weight})",
                        dependencies=[],
                        importance=1.0
                    ))
        
        # 2. 提取DestinationRule中的策略路径
        destination_rules = self.config_data.get("destination_rules", [])
        for dr in destination_rules:
            dr_name = dr.get("name", "")
            spec = dr.get("spec", {})
            host = spec.get("host", "")
            
            # 负载均衡策略
            traffic_policy = spec.get("trafficPolicy", {})
            load_balancer = traffic_policy.get("loadBalancer", {})
            if load_balancer:
                algorithm = load_balancer.get("simple", "")
                path_id = f"dr_{dr_name}_lb_{algorithm}"
                paths.append(ConfigPath(
                    path_id=path_id,
                    path_type="load_balancing",
                    service_name=host,
                    resource_name="DestinationRule",
                    path_description=f"负载均衡算法: {algorithm}",
                    dependencies=[],
                    importance=0.8
                ))
            
            # 连接池策略
            connection_pool = traffic_policy.get("connectionPool", {})
            if connection_pool:
                tcp = connection_pool.get("tcp", {})
                http = connection_pool.get("http", {})
                if tcp or http:
                    path_id = f"dr_{dr_name}_connection_pool"
                    paths.append(ConfigPath(
                        path_id=path_id,
                        path_type="connection_pool",
                        service_name=host,
                        resource_name="DestinationRule",
                        path_description="连接池配置",
                        dependencies=[],
                        importance=0.7
                    ))
            
            # 异常检测策略
            outlier_detection = traffic_policy.get("outlierDetection", {})
            if outlier_detection:
                consecutive_errors = outlier_detection.get("consecutiveErrors", 0)
                path_id = f"dr_{dr_name}_outlier_detection"
                paths.append(ConfigPath(
                    path_id=path_id,
                    path_type="outlier_detection",
                    service_name=host,
                    resource_name="DestinationRule",
                    path_description=f"异常检测: {consecutive_errors}次连续错误",
                    dependencies=[],
                    importance=0.9
                ))
            
            # 子集配置
            subsets = spec.get("subsets", [])
            for subset in subsets:
                subset_name = subset.get("name", "")
                labels = subset.get("labels", {})
                path_id = f"dr_{dr_name}_subset_{subset_name}"
                paths.append(ConfigPath(
                    path_id=path_id,
                    path_type="subset_config",
                    service_name=host,
                    resource_name="DestinationRule",
                    path_description=f"子集配置: {subset_name}",
                    dependencies=[],
                    importance=0.6
                ))
        
        # 3. 提取Gateway配置路径
        gateways = self.config_data.get("gateways", [])
        for gw in gateways:
            gw_name = gw.get("name", "")
            spec = gw.get("spec", {})
            
            servers = spec.get("servers", [])
            for i, server in enumerate(servers):
                port = server.get("port", {})
                hosts = server.get("hosts", [])
                
                for host in hosts:
                    path_id = f"gw_{gw_name}_server_{i}_host_{host}"
                    paths.append(ConfigPath(
                        path_id=path_id,
                        path_type="gateway_host",
                        service_name="gateway",
                        resource_name="Gateway",
                        path_description=f"Gateway主机配置: {host}",
                        dependencies=[],
                        importance=0.8
                    ))
        
        return paths
    
    def _build_dependency_graph(self) -> Dict[str, List[str]]:
        """构建路径依赖图"""
        dependencies = {}
        
        for path in self.total_paths:
            path_deps = []
            
            # 根据路径类型确定依赖关系
            if path.path_type == "route_destination":
                # 路由目标依赖匹配条件
                service_name = path.service_name
                for other_path in self.total_paths:
                    if (other_path.service_name == service_name and 
                        other_path.path_type in ["header_match", "uri_match"]):
                        path_deps.append(other_path.path_id)
            
            elif path.path_type == "subset_config":
                # 子集配置依赖DestinationRule
                for other_path in self.total_paths:
                    if (other_path.service_name == path.service_name and
                        other_path.resource_name == "DestinationRule" and
                        other_path.path_type in ["load_balancing", "connection_pool", "outlier_detection"]):
                        path_deps.append(other_path.path_id)
            
            dependencies[path.path_id] = path_deps
        
        return dependencies
    
    def calculate_coverage(self, test_cases: List[Dict[str, Any]], 
                         execution_results: Dict[str, Any] = None) -> CoverageResult:
        """计算测试用例的覆盖率"""
        method = test_cases[0].get("method", "unknown") if test_cases else "unknown"
        
        # 从测试用例中提取期望覆盖的路径
        expected_paths = set()
        for test_case in test_cases:
            case_paths = test_case.get("expected_paths", [])
            expected_paths.update(case_paths)
        
        # 如果有执行结果，使用实际触发的路径
        if execution_results:
            actual_paths = self._extract_actual_paths_from_results(execution_results)
        else:
            # 否则使用期望路径
            actual_paths = expected_paths
        
        # 计算覆盖率
        total_paths = len(self.total_paths)
        total_path_ids = {path.path_id for path in self.total_paths}
        
        # 将实际路径映射到配置路径ID
        covered_path_ids = self._map_paths_to_config_ids(actual_paths, total_path_ids)
        
        # 计算未覆盖的路径
        uncovered_path_ids = total_path_ids - covered_path_ids
        uncovered_paths = [path.path_id for path in self.total_paths 
                          if path.path_id in uncovered_path_ids]
        
        # 计算覆盖率百分比
        coverage_percentage = (len(covered_path_ids) / total_paths * 100) if total_paths > 0 else 0
        
        # 计算路径覆盖详情
        path_coverage_details = self._calculate_path_coverage_details(
            covered_path_ids, uncovered_path_ids
        )
        
        return CoverageResult(
            method=method,
            total_paths=total_paths,
            covered_paths=len(covered_path_ids),
            coverage_percentage=coverage_percentage,
            uncovered_paths=uncovered_paths,
            path_coverage_details=path_coverage_details,
            execution_results=execution_results or {}
        )
    
    def _extract_actual_paths_from_results(self, execution_results: Dict[str, Any]) -> Set[str]:
        """从执行结果中提取实际触发的路径"""
        actual_paths = set()
        
        # 从日志、指标、追踪中提取触发的路径
        if "triggered_paths" in execution_results:
            actual_paths.update(execution_results["triggered_paths"])
        
        if "log_analysis" in execution_results:
            log_paths = execution_results["log_analysis"].get("triggered_paths", [])
            actual_paths.update(log_paths)
        
        if "metrics_analysis" in execution_results:
            metrics_paths = execution_results["metrics_analysis"].get("triggered_paths", [])
            actual_paths.update(metrics_paths)
        
        return actual_paths
    
    def _map_paths_to_config_ids(self, paths: Set[str], config_path_ids: Set[str]) -> Set[str]:
        """将路径映射到配置路径ID"""
        covered_ids = set()
        
        for path in paths:
            # 尝试直接匹配
            if path in config_path_ids:
                covered_ids.add(path)
                continue
            
            # 尝试模糊匹配
            for config_id in config_path_ids:
                if self._is_path_match(path, config_id):
                    covered_ids.add(config_id)
        
        return covered_ids
    
    def _is_path_match(self, path: str, config_id: str) -> bool:
        """判断路径是否匹配配置ID"""
        # 简单的匹配逻辑，可以根据需要扩展
        path_lower = path.lower()
        config_id_lower = config_id.lower()
        
        # 提取关键信息进行匹配
        if "header_" in path_lower and "header" in config_id_lower:
            return True
        if "uri_" in path_lower and "uri" in config_id_lower:
            return True
        if "route_" in path_lower and "dest" in config_id_lower:
            return True
        if "lb_" in path_lower and "lb" in config_id_lower:
            return True
        if "policy_" in path_lower and "policy" in config_id_lower:
            return True
        
        return False
    
    def _calculate_path_coverage_details(self, covered_ids: Set[str], 
                                       uncovered_ids: Set[str]) -> Dict[str, Any]:
        """计算路径覆盖详情"""
        details = {
            "by_type": {},
            "by_service": {},
            "by_importance": {},
            "dependency_analysis": {}
        }
        
        # 按类型统计
        for path in self.total_paths:
            path_type = path.path_type
            if path_type not in details["by_type"]:
                details["by_type"][path_type] = {"total": 0, "covered": 0}
            
            details["by_type"][path_type]["total"] += 1
            if path.path_id in covered_ids:
                details["by_type"][path_type]["covered"] += 1
        
        # 按服务统计
        for path in self.total_paths:
            service_name = path.service_name
            if service_name not in details["by_service"]:
                details["by_service"][service_name] = {"total": 0, "covered": 0}
            
            details["by_service"][service_name]["total"] += 1
            if path.path_id in covered_ids:
                details["by_service"][service_name]["covered"] += 1
        
        # 按重要性统计
        importance_ranges = [(0.0, 0.5), (0.5, 0.8), (0.8, 1.0)]
        for low, high in importance_ranges:
            range_name = f"{low}-{high}"
            details["by_importance"][range_name] = {"total": 0, "covered": 0}
            
            for path in self.total_paths:
                if low <= path.importance < high:
                    details["by_importance"][range_name]["total"] += 1
                    if path.path_id in covered_ids:
                        details["by_importance"][range_name]["covered"] += 1
        
        # 依赖分析
        details["dependency_analysis"] = self._analyze_dependency_coverage(covered_ids)
        
        return details
    
    def _analyze_dependency_coverage(self, covered_ids: Set[str]) -> Dict[str, Any]:
        """分析依赖覆盖情况"""
        dependency_analysis = {
            "fully_covered_dependencies": 0,
            "partially_covered_dependencies": 0,
            "uncovered_dependencies": 0,
            "dependency_chains": []
        }
        
        for path_id, deps in self.path_dependencies.items():
            if not deps:
                continue
            
            covered_deps = [dep for dep in deps if dep in covered_ids]
            coverage_ratio = len(covered_deps) / len(deps)
            
            if coverage_ratio == 1.0:
                dependency_analysis["fully_covered_dependencies"] += 1
            elif coverage_ratio > 0:
                dependency_analysis["partially_covered_dependencies"] += 1
            else:
                dependency_analysis["uncovered_dependencies"] += 1
            
            # 记录依赖链
            if path_id in covered_ids:
                dependency_analysis["dependency_chains"].append({
                    "path_id": path_id,
                    "dependencies": deps,
                    "covered_dependencies": covered_deps,
                    "coverage_ratio": coverage_ratio
                })
        
        return dependency_analysis
    
    def compare_coverage_methods(self, coverage_results: List[CoverageResult]) -> Dict[str, Any]:
        """比较不同方法的覆盖率"""
        if not coverage_results:
            return {}
        
        comparison = {
            "methods": [],
            "coverage_ranking": [],
            "statistical_comparison": {},
            "efficiency_analysis": {}
        }
        
        # 收集各方法的覆盖率数据
        for result in coverage_results:
            comparison["methods"].append({
                "method": result.method,
                "coverage_percentage": result.coverage_percentage,
                "covered_paths": result.covered_paths,
                "total_paths": result.total_paths
            })
        
        # 按覆盖率排序
        comparison["coverage_ranking"] = sorted(
            comparison["methods"], 
            key=lambda x: x["coverage_percentage"], 
            reverse=True
        )
        
        # 统计比较
        coverage_values = [method["coverage_percentage"] for method in comparison["methods"]]
        if coverage_values:
            comparison["statistical_comparison"] = {
                "mean_coverage": sum(coverage_values) / len(coverage_values),
                "max_coverage": max(coverage_values),
                "min_coverage": min(coverage_values),
                "coverage_std": self._calculate_std(coverage_values)
            }
        
        return comparison
    
    def _calculate_std(self, values: List[float]) -> float:
        """计算标准差"""
        if len(values) <= 1:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5
    
    def export_coverage_report(self, coverage_results: List[CoverageResult], 
                             output_file: str):
        """导出覆盖率报告"""
        report = {
            "coverage_analysis": {
                "total_config_paths": len(self.total_paths),
                "path_breakdown": {
                    "by_type": {},
                    "by_service": {},
                    "by_importance": {}
                }
            },
            "method_comparison": self.compare_coverage_methods(coverage_results),
            "detailed_results": []
        }
        
        # 添加详细结果
        for result in coverage_results:
            report["detailed_results"].append({
                "method": result.method,
                "coverage_percentage": result.coverage_percentage,
                "covered_paths": result.covered_paths,
                "total_paths": result.total_paths,
                "uncovered_paths": result.uncovered_paths,
                "path_coverage_details": result.path_coverage_details
            })
        
        # 添加路径分解信息
        for path in self.total_paths:
            path_type = path.path_type
            service_name = path.service_name
            
            if path_type not in report["coverage_analysis"]["path_breakdown"]["by_type"]:
                report["coverage_analysis"]["path_breakdown"]["by_type"][path_type] = 0
            report["coverage_analysis"]["path_breakdown"]["by_type"][path_type] += 1
            
            if service_name not in report["coverage_analysis"]["path_breakdown"]["by_service"]:
                report["coverage_analysis"]["path_breakdown"]["by_service"][service_name] = 0
            report["coverage_analysis"]["path_breakdown"]["by_service"][service_name] += 1
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"覆盖率报告已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="覆盖率计算器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--test-cases", help="测试用例文件路径")
    parser.add_argument("--output", help="输出报告文件路径")
    
    args = parser.parse_args()
    
    # 加载配置数据
    with open(args.config, 'r', encoding='utf-8') as f:
        config_data = list(yaml.safe_load_all(f))
        
        # 如果只有一个文档，直接使用；否则合并多个文档
        if len(config_data) == 1:
            config_data = config_data[0]
        else:
            # 合并多个YAML文档（支持 K8s kind 与结构化配置）
            merged_config = {"services": [], "virtual_services": [], "destination_rules": [], "gateways": []}
            kind_to_key = {
                "Service": "services",
                "VirtualService": "virtual_services",
                "DestinationRule": "destination_rules",
                "Gateway": "gateways",
            }
            for doc in config_data:
                if not isinstance(doc, dict):
                    continue
                structured = False
                for key in merged_config.keys():
                    if key in doc:
                        structured = True
                        if isinstance(doc[key], list):
                            merged_config[key].extend(doc[key])
                        else:
                            merged_config[key].append(doc[key])
                if structured:
                    continue
                kind = doc.get("kind")
                key = kind_to_key.get(kind)
                if key:
                    name = (doc.get("metadata") or {}).get("name", "")
                    merged_config[key].append({
                        "name": name,
                        "kind": kind,
                        "metadata": doc.get("metadata") or {},
                        "spec": doc.get("spec") or {},
                    })
            config_data = merged_config
    
    # 创建覆盖率计算器
    calculator = CoverageCalculator(config_data)
    
    print(f"从配置中提取了 {len(calculator.total_paths)} 个配置路径")
    
    # 如果有测试用例文件，计算覆盖率
    if args.test_cases:
        with open(args.test_cases, 'r', encoding='utf-8') as f:
            test_cases_data = json.load(f)
        
        test_cases = test_cases_data.get("test_cases", [])
        coverage_result = calculator.calculate_coverage(test_cases)
        
        print(f"\n覆盖率计算结果:")
        print(f"  方法: {coverage_result.method}")
        print(f"  覆盖率: {coverage_result.coverage_percentage:.2f}%")
        print(f"  覆盖路径: {coverage_result.covered_paths}/{coverage_result.total_paths}")
        print(f"  未覆盖路径数: {len(coverage_result.uncovered_paths)}")
        
        # 导出报告
        if args.output:
            calculator.export_coverage_report([coverage_result], args.output)
    else:
        # 只显示配置路径信息
        print("\n配置路径详情:")
        for path in calculator.total_paths[:10]:  # 显示前10个
            print(f"  {path.path_id}: {path.path_description}")
        
        if len(calculator.total_paths) > 10:
            print(f"  ... 还有 {len(calculator.total_paths) - 10} 个路径")


if __name__ == "__main__":
    main()
