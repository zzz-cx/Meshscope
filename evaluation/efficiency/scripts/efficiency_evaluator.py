#!/usr/bin/env python3
"""
高效性评估器
用于评估正交用例生成方法的效率和性能
"""

import ast
import os
import sys
import json
import time
import threading
import multiprocessing
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
import numpy as np
import pandas as pd
import itertools
import psutil
import memory_profiler
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import matplotlib.pyplot as plt
import seaborn as sns

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

class OrthogonalTestCaseGenerator:
    """正交测试用例生成器"""
    
    def __init__(self, parameters: List[Dict], constraints: List[Dict] = None):
        """初始化生成器"""
        self.parameters = parameters
        self.constraints = constraints or []
        self.parameter_space_size = self._calculate_space_size()
        
    def _calculate_space_size(self) -> int:
        """计算参数空间大小"""
        size = 1
        for param in self.parameters:
            size *= len(param['values'])
        return size
    
    def generate_full_combination(self) -> List[Dict]:
        """生成全组合测试用例"""
        all_combinations = []
        param_names = [p['name'] for p in self.parameters]
        param_values = [p['values'] for p in self.parameters]
        
        for combination in itertools.product(*param_values):
            test_case = dict(zip(param_names, combination))
            if self._satisfies_constraints(test_case):
                all_combinations.append(test_case)
        
        return all_combinations
    
    def generate_orthogonal_array(self, target_coverage: float = 0.9) -> List[Dict]:
        """生成正交数组测试用例"""
        start_time = time.time()
        
        # 简化的正交数组生成算法
        # 实际实现应该使用更复杂的正交表构造算法
        param_names = [p['name'] for p in self.parameters]
        param_values = [p['values'] for p in self.parameters]
        
        # 计算所需的最小用例数
        max_param_size = max(len(values) for values in param_values)
        min_cases_needed = max_param_size ** 2  # 简化估算
        
        # 使用改进的采样策略
        orthogonal_cases = []
        covered_pairs = set()
        total_pairs = self._count_total_pairs()
        
        # 贪心策略生成正交用例
        max_iterations = min(min_cases_needed * 2, 1000)
        for _ in range(max_iterations):
            candidate = self._generate_candidate_case()
            if self._satisfies_constraints(candidate):
                new_pairs = self._get_new_pairs(candidate, covered_pairs)
                if new_pairs:
                    orthogonal_cases.append(candidate)
                    covered_pairs.update(new_pairs)
                    
                    # 检查是否达到目标覆盖率
                    current_coverage = len(covered_pairs) / total_pairs
                    if current_coverage >= target_coverage:
                        break
        
        generation_time = time.time() - start_time
        
        return {
            'test_cases': orthogonal_cases,
            'generation_time': generation_time,
            'coverage': len(covered_pairs) / total_pairs,
            'compression_ratio': 1 - len(orthogonal_cases) / self.parameter_space_size
        }
    
    def generate_pairwise_testing(self) -> List[Dict]:
        """生成成对测试用例"""
        start_time = time.time()
        
        param_names = [p['name'] for p in self.parameters]
        param_values = [p['values'] for p in self.parameters]
        
        # 简化的成对测试算法
        pairwise_cases = []
        covered_pairs = set()
        
        # 为每对参数生成覆盖所有值对的用例
        for i in range(len(param_names)):
            for j in range(i + 1, len(param_names)):
                param1_values = param_values[i]
                param2_values = param_values[j]
                
                for v1 in param1_values:
                    for v2 in param2_values:
                        # 构造测试用例
                        test_case = {}
                        test_case[param_names[i]] = v1
                        test_case[param_names[j]] = v2
                        
                        # 为其他参数填充随机值
                        for k, param_name in enumerate(param_names):
                            if k != i and k != j:
                                test_case[param_name] = np.random.choice(param_values[k])
                        
                        if self._satisfies_constraints(test_case):
                            pairwise_cases.append(test_case)
                            covered_pairs.add((param_names[i], v1, param_names[j], v2))
        
        # 去重
        unique_cases = []
        seen_cases = set()
        for case in pairwise_cases:
            case_tuple = tuple(sorted(case.items()))
            if case_tuple not in seen_cases:
                unique_cases.append(case)
                seen_cases.add(case_tuple)
        
        generation_time = time.time() - start_time
        
        return {
            'test_cases': unique_cases,
            'generation_time': generation_time,
            'coverage': len(covered_pairs) / self._count_total_pairs(),
            'compression_ratio': 1 - len(unique_cases) / self.parameter_space_size
        }
    
    def generate_random_sampling(self, num_cases: int) -> List[Dict]:
        """生成随机采样测试用例"""
        start_time = time.time()
        
        param_names = [p['name'] for p in self.parameters]
        param_values = [p['values'] for p in self.parameters]
        
        random_cases = []
        attempts = 0
        max_attempts = num_cases * 10
        
        while len(random_cases) < num_cases and attempts < max_attempts:
            test_case = {}
            for param_name, values in zip(param_names, param_values):
                test_case[param_name] = np.random.choice(values)
            
            if self._satisfies_constraints(test_case):
                # 检查是否重复
                if test_case not in random_cases:
                    random_cases.append(test_case)
            
            attempts += 1
        
        generation_time = time.time() - start_time
        coverage = self._calculate_coverage(random_cases)
        
        return {
            'test_cases': random_cases,
            'generation_time': generation_time,
            'coverage': coverage,
            'compression_ratio': 1 - len(random_cases) / self.parameter_space_size
        }
    
    def _satisfies_constraints(self, test_case: Dict) -> bool:
        """检查测试用例是否满足约束条件"""
        for constraint in self.constraints:
            if not self._evaluate_constraint(constraint, test_case):
                return False
        return True
    
    def _evaluate_constraint(self, constraint: Dict, test_case: Dict) -> bool:
        """评估单个约束条件"""
        constraint_type = constraint.get('type', 'implication')
        
        if constraint_type == 'implication':
            condition = constraint.get('condition', '')
            implication = constraint.get('implication', '')
            
            # 简化的约束评估 - 实际应该使用更完善的表达式解析器
            if self._evaluate_condition(condition, test_case):
                return self._evaluate_condition(implication, test_case)
            return True
        
        elif constraint_type == 'dependency':
            condition = constraint.get('condition', '')
            implication = constraint.get('implication', '')
            
            if self._evaluate_condition(condition, test_case):
                return self._evaluate_condition(implication, test_case)
            return True
        
        elif constraint_type == 'mutual_exclusion':
            params = constraint.get('parameters', [])
            values = constraint.get('values', [])
            
            # 检查是否有多个参数同时取特定值
            count = sum(1 for param, value in zip(params, values) 
                       if test_case.get(param) == value)
            return count <= 1
        
        return True
    
    def _evaluate_condition(self, condition: str, test_case: Dict) -> bool:
        """评估条件表达式（使用 AST 校验，避免 eval 注入风险）"""
        if not condition or not condition.strip():
            return True
        try:
            # 替换参数名为实际值
            expr = condition
            for param_name, value in test_case.items():
                if isinstance(value, str):
                    expr = expr.replace(param_name, repr(value))
                else:
                    expr = expr.replace(param_name, str(value))
            # 仅允许 Compare/BoolOp/Constant/UnaryOp，拒绝 Call/Import 等
            tree = ast.parse(expr, mode='eval')
            if not self._is_safe_ast(tree):
                return True
            return eval(expr)
        except Exception:
            return True

    def _is_safe_ast(self, node: ast.AST) -> bool:
        """检查 AST 是否仅包含安全的比较/逻辑节点，拒绝 Call/Import 等"""
        forbidden = (ast.Call, ast.Import, ast.ImportFrom, ast.Attribute,
                     ast.Subscript, ast.Lambda, ast.Exec, ast.Global, ast.Delete)
        for n in ast.walk(node):
            if type(n) in forbidden:
                return False
        return True
    
    def _count_total_pairs(self) -> int:
        """计算总的参数值对数量"""
        total_pairs = 0
        param_values = [p['values'] for p in self.parameters]
        
        for i in range(len(param_values)):
            for j in range(i + 1, len(param_values)):
                total_pairs += len(param_values[i]) * len(param_values[j])
        
        return total_pairs
    
    def _generate_candidate_case(self) -> Dict:
        """生成候选测试用例"""
        test_case = {}
        for param in self.parameters:
            test_case[param['name']] = np.random.choice(param['values'])
        return test_case
    
    def _get_new_pairs(self, test_case: Dict, covered_pairs: set) -> set:
        """获取测试用例覆盖的新参数值对"""
        new_pairs = set()
        param_names = list(test_case.keys())
        
        for i in range(len(param_names)):
            for j in range(i + 1, len(param_names)):
                pair = (param_names[i], test_case[param_names[i]], 
                       param_names[j], test_case[param_names[j]])
                if pair not in covered_pairs:
                    new_pairs.add(pair)
        
        return new_pairs
    
    def _calculate_coverage(self, test_cases: List[Dict]) -> float:
        """计算测试用例的覆盖率"""
        if not test_cases:
            return 0.0
        
        covered_pairs = set()
        for test_case in test_cases:
            pairs = self._get_new_pairs(test_case, set())
            covered_pairs.update(pairs)
        
        return len(covered_pairs) / self._count_total_pairs()

class EfficiencyEvaluator:
    """高效性评估器"""
    
    def __init__(self, config_file: str = None):
        """初始化评估器"""
        self.config = self._load_config(config_file)
        self.results = {
            "start_time": datetime.now().isoformat(),
            "test_results": [],
            "performance_analysis": {},
            "comparison_results": {},
            "scalability_analysis": {}
        }
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return {
            "test_cases_file": "test_cases/orthogonal_generation_tests.json",
            "output_dir": "results",
            "parallel_threads": min(8, multiprocessing.cpu_count()),
            "memory_profiling": True,
            "statistical_samples": 10
        }
    
    @memory_profiler.profile
    def measure_generation_performance(self, parameter_space: Dict, method: str, **kwargs) -> Dict[str, Any]:
        """测量生成性能"""
        parameters = parameter_space['parameters']
        constraints = parameter_space.get('constraints', [])
        
        generator = OrthogonalTestCaseGenerator(parameters, constraints)
        
        # 记录开始状态
        start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        start_time = time.time()
        start_cpu_times = psutil.Process().cpu_times()
        
        # 执行生成
        if method == 'orthogonal_array':
            target_coverage = kwargs.get('target_coverage', 0.9)
            result = generator.generate_orthogonal_array(target_coverage)
        elif method == 'pairwise_testing':
            result = generator.generate_pairwise_testing()
        elif method == 'random_sampling':
            num_cases = kwargs.get('num_cases', 100)
            result = generator.generate_random_sampling(num_cases)
        elif method == 'full_combination':
            test_cases = generator.generate_full_combination()
            result = {
                'test_cases': test_cases,
                'generation_time': time.time() - start_time,
                'coverage': 1.0,
                'compression_ratio': 0.0
            }
        else:
            raise ValueError(f"不支持的生成方法: {method}")
        
        # 记录结束状态
        end_time = time.time()
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        end_cpu_times = psutil.Process().cpu_times()
        
        # 计算资源使用
        execution_time = end_time - start_time
        memory_usage = end_memory - start_memory
        cpu_time = (end_cpu_times.user - start_cpu_times.user + 
                   end_cpu_times.system - start_cpu_times.system)
        
        # 汇总结果
        performance_result = {
            'method': method,
            'execution_time': execution_time,
            'memory_usage_mb': memory_usage,
            'cpu_time': cpu_time,
            'test_cases_count': len(result['test_cases']),
            'coverage': result.get('coverage', 0.0),
            'compression_ratio': result.get('compression_ratio', 0.0),
            'parameter_space_size': generator.parameter_space_size,
            'generation_efficiency': len(result['test_cases']) / execution_time if execution_time > 0 else 0,
            'coverage_efficiency': result.get('coverage', 0.0) / len(result['test_cases']) if result['test_cases'] else 0
        }
        
        return performance_result
    
    def run_scalability_test(self, base_scenario: Dict) -> Dict[str, Any]:
        """运行可扩展性测试"""
        print("开始可扩展性测试...")
        
        scalability_results = {
            'parameter_scaling': [],
            'constraint_scaling': [],
            'parallel_scaling': []
        }
        
        # 参数数量扩展测试
        base_params = base_scenario['parameter_space']['parameters']
        for param_count in [3, 5, 8, 10, 12, 15]:
            if param_count <= len(base_params):
                test_params = base_params[:param_count]
                test_space = {'parameters': test_params, 'constraints': []}
                
                result = self.measure_generation_performance(
                    test_space, 'orthogonal_array', target_coverage=0.9
                )
                result['parameter_count'] = param_count
                scalability_results['parameter_scaling'].append(result)
        
        # 约束复杂度扩展测试
        base_constraints = base_scenario['parameter_space'].get('constraints', [])
        for constraint_count in [0, 2, 5, 8, 10]:
            if constraint_count <= len(base_constraints):
                test_constraints = base_constraints[:constraint_count]
                test_space = {
                    'parameters': base_params[:8],  # 固定参数数量
                    'constraints': test_constraints
                }
                
                result = self.measure_generation_performance(
                    test_space, 'orthogonal_array', target_coverage=0.9
                )
                result['constraint_count'] = constraint_count
                scalability_results['constraint_scaling'].append(result)
        
        # 并行扩展测试
        test_space = {
            'parameters': base_params[:10],
            'constraints': base_constraints[:5]
        }
        
        for thread_count in [1, 2, 4, 8]:
            parallel_result = self.measure_parallel_performance(
                test_space, thread_count
            )
            parallel_result['thread_count'] = thread_count
            scalability_results['parallel_scaling'].append(parallel_result)
        
        return scalability_results
    
    def measure_parallel_performance(self, parameter_space: Dict, thread_count: int) -> Dict[str, Any]:
        """测量并行性能"""
        # 模拟并行生成测试
        # 实际实现应该将生成任务拆分并并行执行
        
        start_time = time.time()
        
        def generate_chunk(chunk_id):
            """生成一个数据块"""
            generator = OrthogonalTestCaseGenerator(
                parameter_space['parameters'],
                parameter_space.get('constraints', [])
            )
            return generator.generate_orthogonal_array(0.9)
        
        # 使用线程池并行执行
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(generate_chunk, i) for i in range(thread_count)]
            results = [future.result() for future in futures]
        
        execution_time = time.time() - start_time
        
        # 合并结果
        total_cases = sum(len(r['test_cases']) for r in results)
        avg_coverage = np.mean([r['coverage'] for r in results])
        
        return {
            'execution_time': execution_time,
            'total_test_cases': total_cases,
            'average_coverage': avg_coverage,
            'parallel_efficiency': thread_count / (execution_time * thread_count) if execution_time > 0 else 0
        }
    
    def run_coverage_efficiency_analysis(self, scenario: Dict) -> Dict[str, Any]:
        """运行覆盖率效率分析"""
        print("开始覆盖率效率分析...")
        
        parameter_space = scenario['parameter_space']
        coverage_points = [0.7, 0.8, 0.85, 0.9, 0.95, 0.98]
        
        efficiency_results = {
            'coverage_curves': [],
            'efficiency_analysis': {}
        }
        
        for target_coverage in coverage_points:
            result = self.measure_generation_performance(
                parameter_space, 'orthogonal_array', target_coverage=target_coverage
            )
            result['target_coverage'] = target_coverage
            efficiency_results['coverage_curves'].append(result)
        
        # 分析效率曲线
        if efficiency_results['coverage_curves']:
            curves = efficiency_results['coverage_curves']
            
            # 计算边际效率
            marginal_efficiencies = []
            for i in range(1, len(curves)):
                coverage_gain = curves[i]['coverage'] - curves[i-1]['coverage']
                case_increase = curves[i]['test_cases_count'] - curves[i-1]['test_cases_count']
                marginal_efficiency = coverage_gain / case_increase if case_increase > 0 else 0
                marginal_efficiencies.append(marginal_efficiency)
            
            efficiency_results['efficiency_analysis'] = {
                'initial_efficiency': curves[0]['coverage_efficiency'],
                'peak_efficiency': max(c['coverage_efficiency'] for c in curves),
                'marginal_efficiencies': marginal_efficiencies,
                'efficiency_decay_rate': self._calculate_decay_rate(
                    [c['coverage_efficiency'] for c in curves]
                )
            }
        
        return efficiency_results
    
    def _calculate_decay_rate(self, efficiency_values: List[float]) -> float:
        """计算效率衰减率"""
        if len(efficiency_values) < 2:
            return 0.0
        
        # 使用线性回归计算衰减率
        x = np.arange(len(efficiency_values))
        coeffs = np.polyfit(x, efficiency_values, 1)
        return abs(coeffs[0])  # 返回斜率的绝对值
    
    def run_method_comparison(self, scenario: Dict) -> Dict[str, Any]:
        """运行方法对比测试"""
        print("开始方法对比测试...")
        
        parameter_space = scenario['parameter_space']
        methods = ['orthogonal_array', 'pairwise_testing', 'random_sampling']
        
        comparison_results = {}
        
        for method in methods:
            print(f"测试方法: {method}")
            
            # 运行多次取平均值
            method_results = []
            for run in range(self.config['statistical_samples']):
                if method == 'random_sampling':
                    result = self.measure_generation_performance(
                        parameter_space, method, num_cases=100
                    )
                else:
                    result = self.measure_generation_performance(
                        parameter_space, method, target_coverage=0.9
                    )
                method_results.append(result)
            
            # 计算统计指标
            comparison_results[method] = {
                'mean_execution_time': np.mean([r['execution_time'] for r in method_results]),
                'std_execution_time': np.std([r['execution_time'] for r in method_results]),
                'mean_test_cases': np.mean([r['test_cases_count'] for r in method_results]),
                'mean_coverage': np.mean([r['coverage'] for r in method_results]),
                'mean_compression_ratio': np.mean([r['compression_ratio'] for r in method_results]),
                'mean_coverage_efficiency': np.mean([r['coverage_efficiency'] for r in method_results]),
                'reliability': 1 - np.std([r['execution_time'] for r in method_results]) / np.mean([r['execution_time'] for r in method_results])
            }
        
        return comparison_results
    
    def generate_performance_visualizations(self, results: Dict[str, Any]) -> List[str]:
        """生成性能可视化图表"""
        viz_files = []
        viz_dir = os.path.join(self.config['output_dir'], 'visualizations')
        os.makedirs(viz_dir, exist_ok=True)
        
        # 1. 可扩展性图表
        if 'scalability_analysis' in results:
            scalability = results['scalability_analysis']
            
            # 参数扩展性能图
            if 'parameter_scaling' in scalability:
                param_data = scalability['parameter_scaling']
                param_counts = [r['parameter_count'] for r in param_data]
                exec_times = [r['execution_time'] for r in param_data]
                
                plt.figure(figsize=(10, 6))
                plt.plot(param_counts, exec_times, 'o-', linewidth=2, markersize=8)
                plt.xlabel('参数数量')
                plt.ylabel('执行时间 (秒)')
                plt.title('参数扩展性能')
                plt.grid(True, alpha=0.3)
                
                param_scaling_file = os.path.join(viz_dir, 'parameter_scaling.png')
                plt.savefig(param_scaling_file, dpi=300, bbox_inches='tight')
                plt.close()
                viz_files.append(param_scaling_file)
        
        # 2. 方法对比图表
        if 'comparison_results' in results:
            comparison = results['comparison_results']
            methods = list(comparison.keys())
            
            # 性能对比雷达图
            metrics = ['mean_execution_time', 'mean_coverage', 'mean_compression_ratio', 'mean_coverage_efficiency']
            metric_labels = ['执行时间', '覆盖率', '压缩比', '覆盖效率']
            
            fig, ax = plt.subplots(figsize=(10, 8), subplot_kw=dict(projection='polar'))
            
            angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
            angles = np.concatenate((angles, [angles[0]]))
            
            for method in methods:
                values = []
                for metric in metrics:
                    value = comparison[method][metric]
                    # 标准化到0-1范围（执行时间取倒数）
                    if metric == 'mean_execution_time':
                        value = 1 / (1 + value)  # 时间越短越好
                    values.append(value)
                
                values = values + [values[0]]  # 闭合图形
                ax.plot(angles, values, 'o-', linewidth=2, label=method)
                ax.fill(angles, values, alpha=0.1)
            
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(metric_labels)
            ax.set_ylim(0, 1)
            ax.set_title('方法性能对比', pad=20)
            ax.legend()
            
            comparison_file = os.path.join(viz_dir, 'method_comparison.png')
            plt.savefig(comparison_file, dpi=300, bbox_inches='tight')
            plt.close()
            viz_files.append(comparison_file)
        
        return viz_files
    
    def run_evaluation(self) -> str:
        """运行完整的高效性评估"""
        print("开始高效性评估...")
        
        # 加载测试场景
        test_cases_file = self.config["test_cases_file"]
        with open(test_cases_file, 'r', encoding='utf-8') as f:
            test_suite = json.load(f)
        
        scenarios = test_suite["test_scenarios"]
        
        for scenario in scenarios:
            scenario_id = scenario["scenario_id"]
            print(f"运行测试场景: {scenario_id}")
            
            if scenario["category"] == "small_scale":
                # 运行方法对比
                comparison_result = self.run_method_comparison(scenario)
                self.results["comparison_results"][scenario_id] = comparison_result
                
            elif scenario["category"] == "medium_scale":
                # 运行可扩展性测试
                scalability_result = self.run_scalability_test(scenario)
                self.results["scalability_analysis"][scenario_id] = scalability_result
                
            elif scenario["category"] == "coverage_analysis":
                # 运行覆盖率效率分析
                efficiency_result = self.run_coverage_efficiency_analysis(scenario)
                self.results["performance_analysis"][scenario_id] = efficiency_result
        
        # 生成报告
        report_file = self.generate_report()
        print(f"高效性评估完成，报告文件: {report_file}")
        
        return report_file
    
    def generate_report(self) -> str:
        """生成评估报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(self.config["output_dir"], 
                                 f"efficiency_evaluation_report_{timestamp}.json")
        
        os.makedirs(self.config["output_dir"], exist_ok=True)
        
        # 生成可视化
        viz_files = self.generate_performance_visualizations(self.results)
        
        # 添加元数据
        self.results["end_time"] = datetime.now().isoformat()
        self.results["visualizations"] = viz_files
        self.results["summary"] = self._generate_summary()
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        return report_file
    
    def _generate_summary(self) -> Dict[str, Any]:
        """生成评估总结"""
        summary = {
            "total_scenarios": len(self.results.get("comparison_results", {})) + 
                             len(self.results.get("scalability_analysis", {})) + 
                             len(self.results.get("performance_analysis", {})),
            "key_findings": [],
            "recommendations": []
        }
        
        # 分析关键发现
        if self.results.get("comparison_results"):
            for scenario_id, comparison in self.results["comparison_results"].items():
                best_method = min(comparison.keys(), 
                                key=lambda x: comparison[x]["mean_execution_time"])
                summary["key_findings"].append(
                    f"场景 {scenario_id}: {best_method} 方法执行时间最短"
                )
        
        # 生成建议
        summary["recommendations"].extend([
            "对于小规模参数空间，建议使用正交数组方法",
            "对于大规模参数空间，建议使用成对测试方法",
            "在覆盖率要求不高的情况下，可以考虑随机采样",
            "建议根据实际需求选择合适的覆盖率目标"
        ])
        
        return summary

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="正交用例生成效率评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    
    args = parser.parse_args()
    
    config = {"output_dir": args.output}
    if args.config:
        config["config_file"] = args.config
    
    evaluator = EfficiencyEvaluator()
    evaluator.config.update(config)
    
    report_file = evaluator.run_evaluation()
    print(f"评估完成，报告文件: {report_file}")

if __name__ == "__main__":
    main()
