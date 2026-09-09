#!/usr/bin/env python3
"""
随机测试用例生成器 - 基于随机采样生成测试用例
"""

import json
import random
from typing import Dict, List, Any
from dataclasses import dataclass
import numpy as np


@dataclass
class RandomTestCase:
    """随机测试用例定义"""
    case_id: str
    dimensions: Dict[str, Any]
    expected_paths: List[str]
    random_seed: int
    description: str = ""


class RandomGenerator:
    """随机测试用例生成器"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化生成器"""
        self.config_data = config_data
        self.dimensions = self._extract_dimensions()
        self.test_cases = []
    
    def _extract_dimensions(self) -> Dict[str, List[Any]]:
        """提取测试维度"""
        dimensions = {
            "headers": [
                {"key": "end-user", "value": "jason"},
                {"key": "end-user", "value": "admin"},
                {"key": "x-user-role", "value": "premium"},
                {"key": "x-user-role", "value": "standard"},
                {"key": "x-device-type", "value": "mobile"},
                {"key": "x-device-type", "value": "desktop"},
                {"key": "x-region", "value": "us-east"},
                {"key": "x-region", "value": "us-west"},
                {"key": "x-region", "value": "eu-central"},
                {"key": "x-region", "value": "asia-pacific"}
            ],
            "uri_patterns": [
                {"type": "prefix", "value": "/api/v1"},
                {"type": "prefix", "value": "/api/v2"},
                {"type": "prefix", "value": "/admin"},
                {"type": "prefix", "value": "/premium"},
                {"type": "prefix", "value": "/mobile"},
                {"type": "prefix", "value": "/desktop"},
                {"type": "regex", "value": "^/admin/.*"},
                {"type": "regex", "value": "^/api/v[12]/.*"},
                {"type": "exact", "value": "/"},
                {"type": "exact", "value": "/health"}
            ],
            "destinations": [
                {"host": "productpage", "subset": None},
                {"host": "reviews", "subset": "v1"},
                {"host": "reviews", "subset": "v2"},
                {"host": "reviews", "subset": "v3"},
                {"host": "ratings", "subset": None},
                {"host": "details", "subset": None},
                {"host": "cart", "subset": None},
                {"host": "checkout", "subset": None}
            ],
            "load_balancing": [
                {"algorithm": "ROUND_ROBIN"},
                {"algorithm": "LEAST_CONN"},
                {"algorithm": "RANDOM"},
                {"algorithm": "PASSTHROUGH"}
            ],
            "weights": [
                {"primary": 100, "secondary": 0},
                {"primary": 90, "secondary": 10},
                {"primary": 80, "secondary": 20},
                {"primary": 70, "secondary": 30},
                {"primary": 60, "secondary": 40},
                {"primary": 50, "secondary": 50}
            ],
            "policies": [
                {"type": "circuit_breaker", "enabled": True},
                {"type": "circuit_breaker", "enabled": False},
                {"type": "retry", "attempts": 1},
                {"type": "retry", "attempts": 3},
                {"type": "retry", "attempts": 5},
                {"type": "timeout", "duration": "10s"},
                {"type": "timeout", "duration": "30s"},
                {"type": "timeout", "duration": "60s"}
            ],
            "connection_pool": [
                {"max_connections": 50},
                {"max_connections": 100},
                {"max_connections": 200},
                {"max_connections": 500}
            ],
            "outlier_detection": [
                {"consecutive_errors": 3},
                {"consecutive_errors": 5},
                {"consecutive_errors": 10},
                {"consecutive_errors": 20}
            ]
        }
        
        return dimensions
    
    def generate_random_test_cases(self, num_cases: int, seed: int = None) -> List[RandomTestCase]:
        """生成随机测试用例"""
        print(f"生成 {num_cases} 个随机测试用例...")
        
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        
        test_cases = []
        for i in range(num_cases):
            case_id = f"random_{i+1:04d}"
            
            # 随机选择维度组合
            dimensions = self._generate_random_dimensions()
            
            # 计算期望路径
            expected_paths = self._calculate_expected_paths(dimensions)
            
            # 使用当前随机种子
            random_seed = random.getstate()[1][0] if hasattr(random.getstate()[1], '__getitem__') else i
            
            test_case = RandomTestCase(
                case_id=case_id,
                dimensions=dimensions,
                expected_paths=expected_paths,
                random_seed=random_seed,
                description=f"随机测试用例 {i+1}"
            )
            
            test_cases.append(test_case)
        
        self.test_cases = test_cases
        print(f"生成了 {len(test_cases)} 个随机测试用例")
        
        return test_cases
    
    def _generate_random_dimensions(self) -> Dict[str, Any]:
        """生成随机维度组合"""
        dimensions = {}
        
        # 为每个维度随机选择一个值
        for dim_name, dim_values in self.dimensions.items():
            # 使用不同的随机策略
            if dim_name in ["headers", "uri_patterns"]:
                # 匹配条件：可能为空（表示无匹配）
                if random.random() < 0.7:  # 70%概率有匹配条件
                    dimensions[dim_name] = random.choice(dim_values)
                else:
                    dimensions[dim_name] = None
            elif dim_name == "destinations":
                # 目标服务：必须选择一个
                dimensions[dim_name] = random.choice(dim_values)
            elif dim_name == "load_balancing":
                # 负载均衡：80%概率有，20%概率使用默认
                if random.random() < 0.8:
                    dimensions[dim_name] = random.choice(dim_values)
                else:
                    dimensions[dim_name] = {"algorithm": "DEFAULT"}
            elif dim_name == "weights":
                # 权重：可能为单一路由或多路由
                if random.random() < 0.6:  # 60%概率为单一路由
                    dimensions[dim_name] = random.choice([w for w in dim_values if w["secondary"] == 0])
                else:
                    dimensions[dim_name] = random.choice(dim_values)
            elif dim_name in ["policies", "connection_pool", "outlier_detection"]:
                # 策略：50%概率启用
                if random.random() < 0.5:
                    dimensions[dim_name] = random.choice(dim_values)
                else:
                    dimensions[dim_name] = None
        
        return dimensions
    
    def _calculate_expected_paths(self, dimensions: Dict[str, Any]) -> List[str]:
        """计算期望路径"""
        paths = []
        
        for dim_name, dim_value in dimensions.items():
            if dim_value is None:
                continue
                
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
            
            elif dim_name == "connection_pool":
                if isinstance(dim_value, dict):
                    paths.append(f"pool_maxconn_{dim_value['max_connections']}")
            
            elif dim_name == "outlier_detection":
                if isinstance(dim_value, dict):
                    paths.append(f"outlier_errors_{dim_value['consecutive_errors']}")
        
        return paths
    
    def generate_multiple_runs(self, num_cases: int, num_runs: int = 5) -> List[List[RandomTestCase]]:
        """生成多次随机运行的结果"""
        print(f"生成 {num_runs} 次随机运行，每次 {num_cases} 个用例...")
        
        all_runs = []
        for run_id in range(num_runs):
            # 使用不同的种子
            seed = 42 + run_id * 1000
            run_cases = self.generate_random_test_cases(num_cases, seed)
            all_runs.append(run_cases)
        
        return all_runs
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取生成统计信息"""
        if not self.test_cases:
            return {}
        
        total_cases = len(self.test_cases)
        total_paths = set()
        
        for case in self.test_cases:
            total_paths.update(case.expected_paths)
        
        # 计算路径分布统计
        path_counts = {}
        for case in self.test_cases:
            for path in case.expected_paths:
                path_counts[path] = path_counts.get(path, 0) + 1
        
        # 计算维度使用统计
        dimension_usage = {}
        for case in self.test_cases:
            for dim_name, dim_value in case.dimensions.items():
                if dim_value is not None:
                    if dim_name not in dimension_usage:
                        dimension_usage[dim_name] = 0
                    dimension_usage[dim_name] += 1
        
        avg_paths_per_case = sum(len(case.expected_paths) for case in self.test_cases) / total_cases
        avg_dimensions_per_case = sum(len([d for d in case.dimensions.values() if d is not None]) for case in self.test_cases) / total_cases
        
        return {
            "method": "random",
            "total_cases": total_cases,
            "total_unique_paths": len(total_paths),
            "average_paths_per_case": avg_paths_per_case,
            "average_dimensions_per_case": avg_dimensions_per_case,
            "dimension_usage": dimension_usage,
            "most_common_paths": sorted(path_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        }
    
    def get_multiple_runs_statistics(self, all_runs: List[List[RandomTestCase]]) -> Dict[str, Any]:
        """获取多次运行的统计信息"""
        if not all_runs:
            return {}
        
        num_runs = len(all_runs)
        total_cases_per_run = len(all_runs[0]) if all_runs else 0
        
        # 计算每次运行的统计
        run_stats = []
        all_unique_paths = set()
        
        for run_cases in all_runs:
            run_unique_paths = set()
            for case in run_cases:
                run_unique_paths.update(case.expected_paths)
                all_unique_paths.update(case.expected_paths)
            
            run_stats.append({
                "unique_paths": len(run_unique_paths),
                "avg_paths_per_case": sum(len(case.expected_paths) for case in run_cases) / len(run_cases)
            })
        
        # 计算统计指标
        unique_paths_counts = [stat["unique_paths"] for stat in run_stats]
        avg_paths_counts = [stat["avg_paths_per_case"] for stat in run_stats]
        
        return {
            "method": "random_multiple_runs",
            "num_runs": num_runs,
            "total_cases_per_run": total_cases_per_run,
            "unique_paths": {
                "mean": np.mean(unique_paths_counts),
                "std": np.std(unique_paths_counts),
                "min": np.min(unique_paths_counts),
                "max": np.max(unique_paths_counts)
            },
            "avg_paths_per_case": {
                "mean": np.mean(avg_paths_counts),
                "std": np.std(avg_paths_counts),
                "min": np.min(avg_paths_counts),
                "max": np.max(avg_paths_counts)
            },
            "total_unique_paths_across_runs": len(all_unique_paths)
        }
    
    def export_test_cases(self, output_file: str):
        """导出测试用例到文件"""
        export_data = {
            "method": "random",
            "statistics": self.get_statistics(),
            "test_cases": [
                {
                    "case_id": case.case_id,
                    "dimensions": case.dimensions,
                    "expected_paths": case.expected_paths,
                    "random_seed": case.random_seed,
                    "description": case.description
                }
                for case in self.test_cases
            ]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"随机测试用例已导出到: {output_file}")
    
    def export_multiple_runs(self, all_runs: List[List[RandomTestCase]], output_file: str):
        """导出多次运行结果"""
        export_data = {
            "method": "random_multiple_runs",
            "statistics": self.get_multiple_runs_statistics(all_runs),
            "runs": []
        }
        
        for i, run_cases in enumerate(all_runs):
            run_data = {
                "run_id": i + 1,
                "statistics": {
                    "total_cases": len(run_cases),
                    "unique_paths": len(set(path for case in run_cases for path in case.expected_paths))
                },
                "test_cases": [
                    {
                        "case_id": case.case_id,
                        "dimensions": case.dimensions,
                        "expected_paths": case.expected_paths,
                        "random_seed": case.random_seed
                    }
                    for case in run_cases
                ]
            }
            export_data["runs"].append(run_data)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"多次随机运行结果已导出到: {output_file}")


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="随机测试用例生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--num-cases", type=int, default=30, help="测试用例数量")
    parser.add_argument("--num-runs", type=int, default=5, help="多次运行次数")
    parser.add_argument("--seed", type=int, help="随机种子")
    
    args = parser.parse_args()
    
    # 加载配置文件
    import yaml
    with open(args.config, 'r', encoding='utf-8') as f:
        config_docs = list(yaml.safe_load_all(f))
    
    generator = RandomGenerator(config_docs)
    
    if args.num_runs > 1:
        # 多次运行
        all_runs = generator.generate_multiple_runs(args.num_cases, args.num_runs)
        
        # 打印统计信息
        stats = generator.get_multiple_runs_statistics(all_runs)
        print(f"\n多次运行统计:")
        print(f"  运行次数: {stats['num_runs']}")
        print(f"  每次用例数: {stats['total_cases_per_run']}")
        print(f"  唯一路径数 (均值±标准差): {stats['unique_paths']['mean']:.1f}±{stats['unique_paths']['std']:.1f}")
        print(f"  平均每用例路径数: {stats['avg_paths_per_case']['mean']:.2f}")
        print(f"  跨运行总唯一路径数: {stats['total_unique_paths_across_runs']}")
        
        # 导出结果
        if args.output:
            generator.export_multiple_runs(all_runs, args.output)
    else:
        # 单次运行
        test_cases = generator.generate_random_test_cases(args.num_cases, args.seed)
        
        # 打印统计信息
        stats = generator.get_statistics()
        print(f"\n生成统计:")
        print(f"  总用例数: {stats['total_cases']}")
        print(f"  唯一路径数: {stats['total_unique_paths']}")
        print(f"  平均每用例路径数: {stats['average_paths_per_case']:.2f}")
        print(f"  平均每用例维度数: {stats['average_dimensions_per_case']:.2f}")
        
        # 导出结果
        if args.output:
            generator.export_test_cases(args.output)
        else:
            print(f"\n前5个测试用例示例:")
            for i, case in enumerate(test_cases[:5]):
                print(f"  {case.case_id}: 路径数={len(case.expected_paths)}, 种子={case.random_seed}")


if __name__ == "__main__":
    main()
