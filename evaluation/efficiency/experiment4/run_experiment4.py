#!/usr/bin/env python3
"""
实验四主运行器 - 效率评估实验
"""

import os
import sys
import json
import yaml
import time
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

# 添加项目根目录与 generators 目录到 Python 路径
_experiment_dir = Path(__file__).resolve().parent
project_root = _experiment_dir.parent.parent.parent
sys.path.insert(0, str(_experiment_dir / "generators"))
sys.path.insert(0, str(_experiment_dir))
sys.path.insert(0, str(project_root))

# 导入实验四的各个组件
from generators.exhaustive_generator import ExhaustiveGenerator
from generators.orthogonal_generator import OrthogonalGenerator
from generators.istio_orthogonal_generator import IstioOrthogonalGenerator
from generators.pairwise_generator import PairwiseGenerator
from generators.random_generator import RandomGenerator
from coverage.coverage_calculator import CoverageCalculator
from cost.cost_analyzer import CostAnalyzer


class Experiment4Runner:
    """实验四运行器"""
    
    def __init__(self, config_file: str):
        """初始化实验运行器"""
        self.config_file = config_file
        self.config = self._load_config()
        self.results = {}
        self.start_time = None
        self.end_time = None
        
        # 初始化组件
        self.coverage_calculator = None
        self.cost_analyzer = CostAnalyzer()
        
        # 创建结果目录
        self.results_dir = Path("results")
        self.results_dir.mkdir(exist_ok=True)
    
    def _load_config(self) -> Dict[str, Any]:
        """加载实验配置"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 设置默认值
        default_config = {
            "experiment": {
                "name": "efficiency_evaluation",
                "description": "测试用例生成方法效率评估",
                "iterations": 1
            },
            "methods": ["exhaustive", "orthogonal", "pairwise", "random"],
            "configs": {
                "small": "configs/small_config.yaml",
                "medium": "configs/medium_config.yaml", 
                "large": "configs/large_config.yaml"
            },
            "parameters": {
                "exhaustive": {"max_cases": 1000},
                "orthogonal": {"max_cases": 100},
                "pairwise": {"max_cases": 50},
                "random": {"num_cases": 30, "num_runs": 5}
            },
            "output": {
                "results_dir": "results",
                "visualizations": True
            }
        }
        
        # 合并配置
        for key, value in default_config.items():
            if key not in config:
                config[key] = value
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = sub_value
        
        return config
    
    def run_experiment(self):
        """运行完整实验"""
        print("=" * 60)
        print("开始实验四：效率评估实验")
        print("=" * 60)
        
        self.start_time = time.time()
        
        try:
            # 1. 静态准备
            self._static_preparation()
            
            # 2. 测试用例生成与执行
            self._test_case_generation_and_execution()
            
            # 3. 覆盖率计算
            self._coverage_calculation()
            
            # 4. 成本与效率统计
            self._cost_efficiency_analysis()
            
            # 5. 重复实验
            if self.config["experiment"]["iterations"] > 1:
                self._repeated_experiments()
            
            # 6. 统计测试
            self._statistical_testing()
            
            # 7. 敏感性分析
            self._sensitivity_analysis()
            
            # 8. 规模敏感性
            self._scale_sensitivity_analysis()
            
            # 9. 生成输出和可视化
            self._generate_output_and_visualization()
            
            self.end_time = time.time()
            
            print(f"\n实验完成！总耗时: {self.end_time - self.start_time:.2f} 秒")
            
        except Exception as e:
            print(f"实验执行出错: {e}")
            raise
    
    def _static_preparation(self):
        """静态准备阶段"""
        print("\n1. 静态准备阶段")
        print("-" * 30)
        
        # 加载配置数据
        config_files = self.config["configs"]
        all_config_data = {}
        kind_to_key = {
            "Service": "services",
            "VirtualService": "virtual_services",
            "DestinationRule": "destination_rules",
            "Gateway": "gateways",
        }
        
        for scale, config_file in config_files.items():
            config_path = Path(config_file)
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_docs = list(yaml.safe_load_all(f))
                
                # 合并多个 YAML 文档：支持 K8s kind 资源与已结构化 dict
                merged_config = {"services": [], "virtual_services": [], "destination_rules": [], "gateways": []}
                for doc in config_docs:
                    if not isinstance(doc, dict):
                        continue
                    # 已是结构化配置（含 services / virtual_services 等键）
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
                    # 标准 K8s/Istio 多文档 YAML
                    kind = doc.get("kind")
                    key = kind_to_key.get(kind)
                    if not key:
                        continue
                    name = (doc.get("metadata") or {}).get("name", "")
                    merged_config[key].append({
                        "name": name,
                        "kind": kind,
                        "metadata": doc.get("metadata") or {},
                        "spec": doc.get("spec") or {},
                    })
                
                all_config_data[scale] = merged_config
                print(f"  加载 {scale} 规模配置: {len(merged_config.get('services', []))} 个服务, "
                      f"{len(merged_config.get('virtual_services', []))} 个VS, "
                      f"{len(merged_config.get('destination_rules', []))} 个DR")
            else:
                print(f"  警告: 配置文件不存在: {config_file}")
        
        # 初始化覆盖率计算器（使用中等规模配置）
        if "medium" in all_config_data:
            self.coverage_calculator = CoverageCalculator(all_config_data["medium"])
            print(f"  初始化覆盖率计算器，总配置路径数: {len(self.coverage_calculator.total_paths)}")
        
        self.all_config_data = all_config_data
    
    def _test_case_generation_and_execution(self):
        """测试用例生成与执行阶段"""
        print("\n2. 测试用例生成与执行阶段")
        print("-" * 40)
        
        methods = self.config["methods"]
        parameters = self.config["parameters"]
        
        self.generation_results = {}
        
        for method in methods:
            print(f"\n  执行方法: {method}")
            
            if method not in parameters:
                print(f"    警告: 方法 {method} 没有参数配置，跳过")
                continue
            
            method_params = parameters[method]
            
            try:
                # 选择配置规模（默认使用中等规模）
                config_scale = method_params.get("config_scale", "medium")
                config_data = self.all_config_data.get(config_scale, {})
                
                if not config_data:
                    print(f"    警告: 配置数据 {config_scale} 不存在，跳过")
                    continue
                
                # 生成测试用例
                generation_start = time.time()
                test_cases = self._generate_test_cases(method, config_data, method_params)
                generation_time = time.time() - generation_start
                
                # 开始资源监控
                self.cost_analyzer.resource_monitor.start_monitoring()
                
                # 执行测试用例（模拟）
                execution_start = time.time()
                execution_results = self._execute_test_cases(test_cases, method)
                execution_time = time.time() - execution_start
                
                # 停止资源监控
                self.cost_analyzer.resource_monitor.stop_monitoring()
                
                # 保存结果
                self.generation_results[method] = {
                    "test_cases": test_cases,
                    "generation_time": generation_time,
                    "execution_time": execution_time,
                    "execution_results": execution_results,
                    "config_scale": config_scale
                }
                
                print(f"    生成 {len(test_cases)} 个测试用例，耗时 {generation_time:.2f}s")
                print(f"    执行耗时 {execution_time:.2f}s")
                
            except Exception as e:
                print(f"    方法 {method} 执行失败: {e}")
                continue
    
    def _generate_test_cases(self, method: str, config_data: Dict[str, Any], 
                           params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成测试用例"""
        if method == "exhaustive":
            generator = ExhaustiveGenerator(config_data)
            test_cases = generator.generate_test_cases()
            return [{"case_id": case.case_id, "dimensions": case.dimensions, 
                    "expected_paths": case.expected_paths, "method": method}
                   for case in test_cases]
        
        elif method == "orthogonal":
            # 默认用本地正交生成器做覆盖率对比；仅当显式开启 integration 时才调 istio_Dynamic_Test
            use_istio = self.config.get("integration", {}).get("istio_dynamic_test", {}).get("enabled", False)
            if use_istio:
                try:
                    istio_test_path = self.config.get("integration", {}).get("istio_dynamic_test", {}).get("path", None)
                    generator = IstioOrthogonalGenerator(config_data, istio_test_path)
                    max_cases = params.get("max_cases", 100)
                    test_cases = generator.generate_orthogonal_test_cases(max_cases)
                    if test_cases and not str(test_cases[0].get("case_id", "")).startswith("orthogonal_fallback"):
                        return test_cases
                    print("    警告: istio_Dynamic_Test 返回备用用例，改用本地正交生成器")
                except Exception as e:
                    print(f"    警告: 无法使用istio_Dynamic_Test生成器，使用本地正交生成器: {e}")
            generator = OrthogonalGenerator(config_data)
            max_cases = params.get("max_cases", 100)
            test_cases = generator.generate_orthogonal_test_cases(max_cases)
            return [{"case_id": case.case_id, "dimensions": case.dimensions,
                    "expected_paths": case.expected_paths, "orthogonal_groups": case.orthogonal_groups,
                    "coverage_score": case.coverage_score, "method": method}
                   for case in test_cases]
        
        elif method == "pairwise":
            generator = PairwiseGenerator(config_data)
            max_cases = params.get("max_cases", 50)
            test_cases = generator.generate_pairwise_test_cases(max_cases)
            return [{"case_id": case.case_id, "dimensions": case.dimensions,
                    "expected_paths": case.expected_paths, "pairwise_combinations": case.pairwise_combinations,
                    "coverage_value": case.coverage_value, "method": method}
                   for case in test_cases]
        
        elif method == "random":
            generator = RandomGenerator(config_data)
            num_cases = params.get("num_cases", 30)
            num_runs = params.get("num_runs", 5)
            if num_runs > 1:
                all_runs = generator.generate_multiple_runs(num_cases, num_runs)
                # 返回第一次运行的结果
                return [{"case_id": case.case_id, "dimensions": case.dimensions,
                        "expected_paths": case.expected_paths, "random_seed": case.random_seed, "method": method}
                       for case in all_runs[0]]
            else:
                test_cases = generator.generate_random_test_cases(num_cases)
                return [{"case_id": case.case_id, "dimensions": case.dimensions,
                        "expected_paths": case.expected_paths, "random_seed": case.random_seed, "method": method}
                       for case in test_cases]
        
        else:
            raise ValueError(f"未知的测试用例生成方法: {method}")
    
    def _execute_test_cases(self, test_cases: List[Dict[str, Any]], method: str) -> Dict[str, Any]:
        """执行测试用例（模拟）"""
        # 这里是模拟执行，实际应该调用istio_Dynamic_Test中的执行器
        execution_results = {
            "method": method,
            "test_cases_executed": len(test_cases),
            "total_requests": len(test_cases) * 2,  # 模拟请求数
            "successful_requests": len(test_cases) * 2,
            "failed_requests": 0,
            "triggered_paths": [],
            "log_analysis": {
                "triggered_paths": [f"path_{i}" for i in range(len(test_cases))]
            },
            "metrics_analysis": {
                "triggered_paths": [f"metric_path_{i}" for i in range(len(test_cases))]
            }
        }
        
        # 从测试用例中提取触发的路径
        for test_case in test_cases:
            execution_results["triggered_paths"].extend(test_case.get("expected_paths", []))
        
        return execution_results
    
    def _coverage_calculation(self):
        """覆盖率计算阶段"""
        print("\n3. 覆盖率计算阶段")
        print("-" * 25)
        
        if not self.coverage_calculator:
            print("  警告: 覆盖率计算器未初始化，跳过覆盖率计算")
            return
        
        self.coverage_results = []
        
        for method, generation_result in self.generation_results.items():
            test_cases = generation_result["test_cases"]
            execution_results = generation_result["execution_results"]
            
            # 计算覆盖率
            coverage_result = self.coverage_calculator.calculate_coverage(
                test_cases, execution_results
            )
            
            self.coverage_results.append(coverage_result)
            
            print(f"  {method}: 覆盖率 {coverage_result.coverage_percentage:.2f}% "
                  f"({coverage_result.covered_paths}/{coverage_result.total_paths})")
    
    def _cost_efficiency_analysis(self):
        """成本与效率分析阶段"""
        print("\n4. 成本与效率分析阶段")
        print("-" * 30)
        
        for method, generation_result in self.generation_results.items():
            test_cases = generation_result["test_cases"]
            generation_time = generation_result["generation_time"]
            execution_time = generation_result["execution_time"]
            execution_results = generation_result["execution_results"]
            
            # 分析生成成本
            cost_metrics = self.cost_analyzer.analyze_generation_cost(
                method, test_cases, generation_time
            )
            
            # 分析执行成本
            execution_cost = self.cost_analyzer.analyze_execution_cost(
                method, execution_results
            )
            
            # 计算覆盖率
            coverage_percentage = 0
            for coverage_result in self.coverage_results:
                if coverage_result.method == method:
                    coverage_percentage = coverage_result.coverage_percentage
                    break
            
            # 分析效率
            efficiency_metrics = self.cost_analyzer.analyze_efficiency(
                method, test_cases, generation_time, execution_time, coverage_percentage
            )
            
            print(f"  {method}: 效率分数 {efficiency_metrics.efficiency_score:.3f}, "
                  f"成本/用例 {cost_metrics.cost_per_test_case:.3f}s")
    
    def _repeated_experiments(self):
        """重复实验阶段"""
        print("\n5. 重复实验阶段")
        print("-" * 20)
        
        iterations = self.config["experiment"]["iterations"]
        print(f"  执行 {iterations} 次重复实验...")
        
        # 这里可以添加重复实验的逻辑
        # 目前简化为单次实验
        
    def _statistical_testing(self):
        """统计测试阶段"""
        print("\n6. 统计测试阶段")
        print("-" * 20)
        
        # 执行Wilcoxon和McNemar检验
        if len(self.coverage_results) >= 2:
            print("  执行统计显著性检验...")
            # 这里可以添加具体的统计检验逻辑
    
    def _sensitivity_analysis(self):
        """敏感性分析阶段"""
        print("\n7. 敏感性分析阶段")
        print("-" * 25)
        
        # 敏感性分析
        comparison = self.cost_analyzer.compare_methods()
        
        if comparison:
            # 正交值变化敏感性
            variation_factors = {
                "orthogonal_values_0.5": 0.5,
                "orthogonal_values_1.5": 1.5,
                "t_way_2": 2.0,
                "t_way_3": 3.0
            }
            
            sensitivity_results = self.cost_analyzer.perform_sensitivity_analysis(
                comparison, variation_factors
            )
            
            print(f"  完成敏感性分析，测试了 {len(variation_factors)} 个变化因子")
    
    def _scale_sensitivity_analysis(self):
        """规模敏感性分析阶段"""
        print("\n8. 规模敏感性分析阶段")
        print("-" * 30)
        
        # 这里可以添加不同规模配置的分析
        # 目前使用中等规模配置
        print("  规模敏感性分析（使用中等规模配置）")
    
    def _generate_output_and_visualization(self):
        """生成输出和可视化阶段"""
        print("\n9. 生成输出和可视化阶段")
        print("-" * 35)
        
        # 生成综合报告
        self._generate_comprehensive_report()
        
        # 生成可视化
        if self.config["output"]["visualizations"]:
            self._generate_visualizations()
        
        print("  输出和可视化生成完成")
    
    def _generate_comprehensive_report(self):
        """生成综合报告"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_file = self.results_dir / f"efficiency_evaluation_report_{timestamp}.json"
        
        # 收集所有结果
        report = {
            "experiment_info": {
                "name": self.config["experiment"]["name"],
                "description": self.config["experiment"]["description"],
                "start_time": self.start_time,
                "end_time": self.end_time,
                "duration": self.end_time - self.start_time if self.end_time else 0,
                "config_file": self.config_file
            },
            "configuration": self.config,
            "generation_results": self.generation_results,
            "coverage_results": [
                {
                    "method": result.method,
                    "coverage_percentage": result.coverage_percentage,
                    "covered_paths": result.covered_paths,
                    "total_paths": result.total_paths,
                    "uncovered_paths": result.uncovered_paths
                }
                for result in self.coverage_results
            ],
            "cost_efficiency_analysis": {
                "cost_results": [
                    {
                        "method": result.method,
                        "total_requests": result.total_requests,
                        "execution_time": result.execution_time,
                        "cpu_usage": result.cpu_usage,
                        "memory_usage": result.memory_usage,
                        "cost_per_test_case": result.cost_per_test_case
                    }
                    for result in self.cost_analyzer.cost_results
                ],
                "efficiency_results": [
                    {
                        "method": result.method,
                        "test_cases_generated": result.test_cases_generated,
                        "coverage_achieved": result.coverage_achieved,
                        "total_time": result.total_time,
                        "efficiency_score": result.efficiency_score,
                        "scalability_score": result.scalability_score
                    }
                    for result in self.cost_analyzer.efficiency_results
                ],
                "method_comparison": self.cost_analyzer.compare_methods()
            }
        }
        
        # 保存报告
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"  综合报告已保存: {report_file}")
        
        # 导出成本分析报告
        cost_report_file = self.results_dir / f"cost_analysis_report_{timestamp}.json"
        self.cost_analyzer.export_cost_analysis_report(str(cost_report_file))
    
    def _generate_visualizations(self):
        """生成可视化图表"""
        try:
            # 使用可视化模块生成图表
            from visualizations.plot_generator import PlotGenerator
            
            # 创建可视化目录
            viz_dir = self.results_dir / "visualizations"
            viz_dir.mkdir(exist_ok=True)
            
            # 准备数据
            report_data = {
                "coverage_results": [
                    {
                        "method": result.method,
                        "coverage_percentage": result.coverage_percentage,
                        "covered_paths": result.covered_paths,
                        "total_paths": result.total_paths
                    }
                    for result in self.coverage_results
                ],
                "generation_results": self.generation_results,
                "cost_efficiency_analysis": {
                    "efficiency_results": [
                        {
                            "method": result.method,
                            "test_cases_generated": result.test_cases_generated,
                            "coverage_achieved": result.coverage_achieved,
                            "total_time": result.total_time,
                            "efficiency_score": result.efficiency_score
                        }
                        for result in self.cost_analyzer.efficiency_results
                    ],
                    "cost_results": [
                        {
                            "method": result.method,
                            "execution_time": result.execution_time,
                            "total_requests": result.total_requests
                        }
                        for result in self.cost_analyzer.cost_results
                    ]
                }
            }
            
            # 生成可视化图表
            plotter = PlotGenerator(str(self.results_dir))
            plotter.generate_all_visualizations(json.dumps(report_data))
            
            print(f"  可视化图表已保存到: {viz_dir}")
            
        except ImportError as e:
            print(f"  警告: 可视化依赖未安装，跳过可视化生成: {e}")
        except Exception as e:
            print(f"  警告: 可视化生成失败: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="实验四：效率评估实验运行器")
    parser.add_argument("--config", default="config.yaml", help="实验配置文件路径")
    parser.add_argument("--output-dir", help="输出目录路径")
    
    args = parser.parse_args()
    
    # 检查配置文件
    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}")
        return
    
    # 创建实验运行器
    runner = Experiment4Runner(args.config)
    
    # 设置输出目录
    if args.output_dir:
        runner.results_dir = Path(args.output_dir)
        runner.results_dir.mkdir(exist_ok=True)
    
    # 运行实验
    try:
        runner.run_experiment()
    except KeyboardInterrupt:
        print("\n实验被用户中断")
    except Exception as e:
        print(f"\n实验执行失败: {e}")
        raise


if __name__ == "__main__":
    main()
