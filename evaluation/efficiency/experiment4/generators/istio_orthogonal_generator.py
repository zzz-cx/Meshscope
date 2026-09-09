#!/usr/bin/env python3
"""
基于istio_Dynamic_Test的正交测试用例生成器
直接调用test_case_generator.py来生成正交测试用例
"""

import json
import yaml
import os
import sys
import subprocess
import tempfile
from typing import Dict, List, Any
from dataclasses import dataclass
from pathlib import Path
from path_calculator import get_total_possible_paths, calculate_cumulative_coverage


@dataclass
class IstioTestCase:
    """Istio测试用例定义"""
    case_id: str
    description: str
    type: str
    request_params: Dict[str, Any]
    expected_outcome: Dict[str, Any]
    test_strategies: List[str]
    source_service: str


class IstioOrthogonalGenerator:
    """基于istio_Dynamic_Test的正交测试用例生成器"""
    
    def __init__(self, config_data: Dict[str, Any], istio_test_path: str = None):
        """初始化生成器"""
        self.config_data = config_data
        self.test_cases = []
        
        # 设置istio_Dynamic_Test路径
        if istio_test_path:
            self.istio_test_path = Path(istio_test_path)
        else:
            # 默认路径
            project_root = Path(__file__).parent.parent.parent.parent.parent
            self.istio_test_path = project_root / "istio_Dynamic_Test"
        
        self.generator_script = (
            self.istio_test_path
            / "internal"
            / "testcase"
            / "generators"
            / "test_case_generator.py"
        )
    
    def generate_orthogonal_test_cases(self, max_cases: int = 100) -> List[Dict[str, Any]]:
        """生成正交测试用例"""
        print("使用istio_Dynamic_Test生成正交测试用例...")
        
        try:
            # 1. 将YAML配置转换为JSON格式（test_case_generator.py需要的格式）
            json_config = self._convert_yaml_to_istio_json()
            
            # 2. 创建临时配置文件（转换为istio_Dynamic_Test需要的格式）
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as config_file:
                json.dump(json_config, config_file, indent=2, ensure_ascii=False)
                config_file_path = config_file.name
            
            # 使用istio_Dynamic_Test中的服务依赖文件
            service_deps_path = str(self.istio_test_path / "service_dependencies.json")
            
            # 检查服务依赖文件是否存在
            if not os.path.exists(service_deps_path):
                print(f"服务依赖文件不存在: {service_deps_path}")
                return self._generate_fallback_cases()
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as output_file:
                output_path = output_file.name
            
            # 3. 调用test_case_generator.py
            cmd = [
                sys.executable,
                str(self.generator_script),
                "--input", config_file_path,
                "--output", output_path,
                "--ingress-url", "http://productpage:9080",  # 默认入口URL
                "--service-deps", service_deps_path
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.istio_test_path), 
                                  encoding='utf-8', errors='ignore')
            
            print(f"返回码: {result.returncode}")
            print(f"标准输出: {result.stdout}")
            if result.stderr:
                print(f"标准错误: {result.stderr}")
            
            if result.returncode != 0:
                print(f"生成器执行失败: {result.stderr}")
                return self._generate_fallback_cases()
            
            # 4. 读取生成的测试用例
            try:
                print(f"尝试读取输出文件: {output_path}")
                print(f"输出文件是否存在: {os.path.exists(output_path)}")
                with open(output_path, 'r', encoding='utf-8') as f:
                    output_data = json.load(f)
                print(f"输出文件内容: {json.dumps(output_data, indent=2, ensure_ascii=False)}")
            except Exception as e:
                print(f"读取输出文件失败: {e}")
                return self._generate_fallback_cases()
            
            test_cases = output_data.get("test_cases", [])
            print(f"从输出文件中提取的测试用例数量: {len(test_cases)}")
            
            # 5. 限制测试用例数量
            if len(test_cases) > max_cases:
                test_cases = test_cases[:max_cases]
            
            # 6. 转换为实验四格式
            formatted_cases = self._format_test_cases(test_cases)
            
            # 7. 保存到self.test_cases用于统计
            self.test_cases = formatted_cases
            
            print(f"生成了 {len(formatted_cases)} 个正交测试用例")
            
            return formatted_cases
            
        except Exception as e:
            print(f"生成正交测试用例时出错: {e}")
            return self._generate_fallback_cases()
        
        finally:
            # 清理临时文件
            for temp_file in ['config_file_path', 'output_path']:
                try:
                    if temp_file in locals() and os.path.exists(locals()[temp_file]):
                        os.unlink(locals()[temp_file])
                except:
                    pass
    
    def _convert_yaml_to_istio_json(self) -> Dict[str, Any]:
        """将YAML配置转换为istio_Dynamic_Test需要的JSON格式"""
        istio_config = {
            "description": "基于实验四配置生成的正交测试用例",
            "enabled_policies": {
                "routing": True,
                "retry": True,
                "circuit_breaker": True,
                "rate_limit": False,
                "fault_injection": True
            },
            "virtualServices": [],
            "destinationRules": []
        }
        
        # 从YAML文档中提取VirtualService和DestinationRule
        if isinstance(self.config_data, list):
            # 如果是YAML文档列表
            for doc in self.config_data:
                if isinstance(doc, dict) and doc.get("kind") == "VirtualService":
                    # 处理VirtualService，确保所有destination都有subset
                    vs_spec = doc.get("spec", {}).copy()
                    if "http" in vs_spec:
                        for http_rule in vs_spec["http"]:
                            if "route" in http_rule:
                                for route in http_rule["route"]:
                                    if "destination" in route and "subset" not in route["destination"]:
                                        # 为没有subset的destination添加默认subset
                                        route["destination"]["subset"] = "v1"
                    
                    istio_vs = {
                        "name": doc.get("metadata", {}).get("name", "vs"),
                        "spec": vs_spec
                    }
                    istio_config["virtualServices"].append(istio_vs)
                elif isinstance(doc, dict) and doc.get("kind") == "DestinationRule":
                    istio_dr = {
                        "name": doc.get("metadata", {}).get("name", "dr"),
                        "spec": doc.get("spec", {})
                    }
                    istio_config["destinationRules"].append(istio_dr)
        else:
            # 如果是字典格式（兼容旧格式）
            virtual_services = self.config_data.get("virtual_services", [])
            for i, vs in enumerate(virtual_services):
                istio_vs = {
                    "name": vs.get("metadata", {}).get("name", f"vs-{i}"),
                    "spec": vs.get("spec", {})
                }
                istio_config["virtualServices"].append(istio_vs)
            
            destination_rules = self.config_data.get("destination_rules", [])
            for i, dr in enumerate(destination_rules):
                istio_dr = {
                    "name": dr.get("metadata", {}).get("name", f"dr-{i}"),
                    "spec": dr.get("spec", {})
                }
                istio_config["destinationRules"].append(istio_dr)
        
        return istio_config
    
    def _create_service_deps(self) -> Dict[str, List[str]]:
        """创建服务依赖关系"""
        service_deps = {}
        
        # 从VirtualService中提取服务依赖
        virtual_services = self.config_data.get("virtual_services", [])
        for vs in virtual_services:
            hosts = vs.get("spec", {}).get("hosts", [])
            for host in hosts:
                if host not in service_deps:
                    service_deps[host] = []
                
                # 从路由中提取依赖服务
                http_routes = vs.get("spec", {}).get("http", [])
                for route in http_routes:
                    route_destinations = route.get("route", [])
                    for dest in route_destinations:
                        dest_host = dest.get("destination", {}).get("host", "")
                        if dest_host and dest_host not in service_deps[host]:
                            service_deps[host].append(dest_host)
        
        # 如果没有依赖，创建默认的
        if not service_deps:
            service_deps = {
                "productpage": ["reviews", "details"],
                "reviews": ["ratings"],
                "details": [],
                "ratings": []
            }
        
        return service_deps
    
    def _format_test_cases(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将istio_Dynamic_Test的测试用例格式转换为实验四格式"""
        formatted_cases = []
        
        for case in test_cases:
            # 提取期望路径
            expected_paths = self._extract_expected_paths(case)
            
            # 构建维度信息
            dimensions = self._build_dimensions(case)
            
            formatted_case = {
                "case_id": case.get("case_id", ""),
                "dimensions": dimensions,
                "expected_paths": expected_paths,
                "method": "orthogonal",
                "description": case.get("description", ""),
                "type": case.get("type", ""),
                "request_params": case.get("request_params", {}),
                "expected_outcome": case.get("expected_outcome", {}),
                "test_strategies": case.get("test_strategies", []),
                "source_service": case.get("source_service", ""),
                "orthogonal_groups": self._extract_orthogonal_groups(case),
                "coverage_score": self._calculate_coverage_score(case)
            }
            
            formatted_cases.append(formatted_case)
        
        return formatted_cases
    
    def _extract_expected_paths(self, case: Dict[str, Any]) -> List[str]:
        """从测试用例中提取期望路径 - 基于实际测试覆盖的路径"""
        paths = []
        
        # 从请求参数中提取路径
        request_params = case.get("request_params", {})
        host = request_params.get("host", "")
        case_id = case.get("case_id", "")
        
        if host == "productpage":
            # productpage相关路径
            headers = request_params.get("headers", {})
            if "end-user" in headers:
                # 匹配路径：当header匹配时
                paths.append(f"match_headers_{headers['end-user']}")
                paths.append("route_productpage_matched")
                # 默认路径：当header不匹配时（通过同一个测试用例的对比可以验证）
                paths.append("route_productpage_default")
            else:
                # 如果没有匹配条件，则是默认路径
                paths.append("route_productpage_default")
            
        elif host == "reviews":
            # reviews相关路径
            expected_outcome = case.get("expected_outcome", {})
            distribution = expected_outcome.get("distribution", {})
            if distribution:
                # 流量分割测试
                paths.append("route_reviews_traffic_split")
                for subset, ratio in distribution.items():
                    paths.append(f"weight_{subset}_{ratio}")
            else:
                # 普通路由测试
                paths.append("route_reviews_normal")
        
        # 检查是否测试了负载均衡（目前正交代码还没实现）
        test_strategies = case.get("test_strategies", [])
        if "load_balancing" in test_strategies:
            paths.append("policy_load_balancer")
        
        print(f"{case_id} 实际覆盖的路径: {paths}")
        return paths
    
    def _build_dimensions(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """构建维度信息"""
        dimensions = {}
        
        request_params = case.get("request_params", {})
        
        # 匹配条件维度
        if "headers" in request_params:
            dimensions["match_conditions"] = request_params["headers"]
        
        if "path" in request_params:
            dimensions["uri_patterns"] = {"type": "prefix", "value": request_params["path"]}
        
        # 路由目标维度
        expected_outcome = case.get("expected_outcome", {})
        if "destination" in expected_outcome:
            dimensions["destinations"] = {
                "host": expected_outcome["destination"].split("/")[0] if "/" in expected_outcome["destination"] else expected_outcome["destination"],
                "subset": expected_outcome["destination"].split("/")[1] if "/" in expected_outcome["destination"] else None
            }
        
        # 策略维度
        test_strategies = case.get("test_strategies", [])
        if test_strategies:
            dimensions["policies"] = {"strategies": test_strategies}
        
        return dimensions
    
    def _extract_orthogonal_groups(self, case: Dict[str, Any]) -> List[str]:
        """提取正交组信息"""
        groups = []
        
        test_strategies = case.get("test_strategies", [])
        
        # 根据策略类型分类正交组
        if "orthogonal_matching" in test_strategies:
            groups.append("match_conditions")
        
        if any(strategy in test_strategies for strategy in ["fault_injection", "retry", "timeout"]):
            groups.append("function_policies")
        
        if any(strategy in test_strategies for strategy in ["circuit_breaker", "connection_pool"]):
            groups.append("global_local")
        
        if any(strategy in test_strategies for strategy in ["traffic_split", "routing"]):
            groups.append("trigger_mechanisms")
        
        return groups
    
    def _calculate_coverage_score(self, case: Dict[str, Any]) -> float:
        """计算覆盖分数 - 基于实际配置路径覆盖率"""
        # 获取配置中的所有可能路径
        total_possible_paths = get_total_possible_paths(self.config_data)
        
        # 获取当前测试用例覆盖的路径
        covered_paths = set(self._extract_expected_paths(case))
        
        # 计算覆盖率
        if total_possible_paths == 0:
            return 0.0
        
        coverage_ratio = len(covered_paths) / total_possible_paths
        
        # 策略数量加分
        test_strategies = case.get("test_strategies", [])
        strategy_bonus = len(test_strategies) * 0.1
        
        # 正交组数量加分
        orthogonal_groups = self._extract_orthogonal_groups(case)
        group_bonus = len(orthogonal_groups) * 0.05
        
        total_score = coverage_ratio + strategy_bonus + group_bonus
        return min(total_score, 1.0)
    
    
    def _generate_fallback_cases(self) -> List[Dict[str, Any]]:
        """生成备用测试用例"""
        print("生成备用正交测试用例...")
        
        fallback_cases = [
            {
                "case_id": "orthogonal_fallback_001",
                "dimensions": {
                    "match_conditions": {"end-user": "jason"},
                    "destinations": {"host": "productpage", "subset": None}
                },
                "expected_paths": ["header_end-user_jason", "route_dest_productpage"],
                "method": "orthogonal",
                "description": "备用正交测试用例1",
                "orthogonal_groups": ["match_conditions"],
                "coverage_score": 0.3
            },
            {
                "case_id": "orthogonal_fallback_002", 
                "dimensions": {
                    "match_conditions": {"x-user-role": "premium"},
                    "destinations": {"host": "reviews", "subset": "v1"},
                    "policies": {"strategies": ["fault_injection", "retry"]}
                },
                "expected_paths": ["header_x-user-role_premium", "route_dest_reviews_v1", "strategy_fault_injection", "strategy_retry"],
                "method": "orthogonal",
                "description": "备用正交测试用例2",
                "orthogonal_groups": ["match_conditions", "function_policies"],
                "coverage_score": 0.5
            }
        ]
        
        return fallback_cases
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        if not self.test_cases:
            return {
                "method": "istio_orthogonal",
                "total_cases": 0,
                "total_unique_paths": 0,
                "average_coverage_score": 0.0,
                "orthogonal_groups_used": [],
                "orthogonal_principles_applied": []
            }
        
        total_cases = len(self.test_cases)
        total_paths = set()
        orthogonal_groups = set()
        
        for case in self.test_cases:
            total_paths.update(case.get("expected_paths", []))
            orthogonal_groups.update(case.get("orthogonal_groups", []))
        
        # 计算累积覆盖率：所有测试用例共同覆盖的唯一路径数 / 总路径数
        total_possible_paths = get_total_possible_paths(self.config_data)
        cumulative_coverage_score = calculate_cumulative_coverage(self.test_cases, total_possible_paths)
        
        # 计算平均覆盖分数（用于显示每个测试用例的贡献）
        avg_coverage_score = sum(case.get("coverage_score", 0) for case in self.test_cases) / total_cases if total_cases > 0 else 0
        
        return {
            "method": "istio_orthogonal",
            "total_cases": total_cases,
            "total_unique_paths": len(total_paths),
            "cumulative_coverage_score": cumulative_coverage_score,
            "average_coverage_score": avg_coverage_score,
            "orthogonal_groups_used": list(orthogonal_groups),
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
            "method": "istio_orthogonal",
            "statistics": self.get_statistics(),
            "test_cases": self.test_cases
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"Istio正交测试用例已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="基于istio_Dynamic_Test的正交测试用例生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--max-cases", type=int, default=100, help="最大测试用例数")
    parser.add_argument("--istio-test-path", help="istio_Dynamic_Test路径")
    
    args = parser.parse_args()
    
    # 加载配置数据
    with open(args.config, 'r', encoding='utf-8') as f:
        config_docs = list(yaml.safe_load_all(f))
    
    # 直接传递YAML文档列表给生成器
    generator = IstioOrthogonalGenerator(config_docs, args.istio_test_path)
    test_cases = generator.generate_orthogonal_test_cases(args.max_cases)
    
    # 打印统计信息
    stats = generator.get_statistics()
    print(f"\n生成统计:")
    print(f"  总用例数: {stats['total_cases']}")
    print(f"  唯一路径数: {stats['total_unique_paths']}")
    print(f"  累积覆盖率: {stats['cumulative_coverage_score']:.3f}")
    print(f"  平均覆盖分数: {stats['average_coverage_score']:.3f}")
    print(f"  使用的正交组: {stats['orthogonal_groups_used']}")
    
    # 导出结果
    if args.output:
        generator.export_test_cases(args.output)
    else:
        print(f"\n前5个测试用例示例:")
        for i, case in enumerate(test_cases[:5]):
            print(f"  {case['case_id']}: 覆盖分数={case['coverage_score']:.3f}, 正交组={case['orthogonal_groups']}")


if __name__ == "__main__":
    main()
