#!/usr/bin/env python3
"""
成本与效率分析器 - 分析测试用例生成和执行的成本与效率
"""

import json
import time
import psutil
import threading
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass
class CostMetrics:
    """成本指标定义"""
    method: str
    total_requests: int
    execution_time: float  # 秒
    cpu_usage: float  # 百分比
    memory_usage: float  # MB
    network_traffic: float  # bytes
    storage_usage: float  # MB
    cost_per_test_case: float
    cost_per_coverage_percent: float


@dataclass
class EfficiencyMetrics:
    """效率指标定义"""
    method: str
    test_cases_generated: int
    coverage_achieved: float  # 百分比
    time_to_generate: float  # 秒
    time_to_execute: float  # 秒
    total_time: float  # 秒
    efficiency_score: float  # 综合效率分数
    scalability_score: float  # 可扩展性分数


class ResourceMonitor:
    """资源监控器"""
    
    def __init__(self):
        self.monitoring = False
        self.cpu_samples = []
        self.memory_samples = []
        self.network_samples = []
        self.start_time = None
        self.end_time = None
        self.initial_network = None
    
    def start_monitoring(self):
        """开始监控"""
        self.monitoring = True
        self.start_time = time.time()
        self.initial_network = psutil.net_io_counters()
        
        # 启动监控线程
        self.monitor_thread = threading.Thread(target=self._monitor_resources)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        self.end_time = time.time()
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join()
    
    def _monitor_resources(self):
        """监控资源使用情况"""
        while self.monitoring:
            try:
                # CPU使用率
                cpu_percent = psutil.cpu_percent(interval=0.1)
                self.cpu_samples.append(cpu_percent)
                
                # 内存使用
                memory_info = psutil.virtual_memory()
                memory_mb = memory_info.used / (1024 * 1024)  # 转换为MB
                self.memory_samples.append(memory_mb)
                
                # 网络流量
                network_info = psutil.net_io_counters()
                if self.initial_network:
                    bytes_sent = network_info.bytes_sent - self.initial_network.bytes_sent
                    bytes_recv = network_info.bytes_recv - self.initial_network.bytes_recv
                    total_bytes = bytes_sent + bytes_recv
                    self.network_samples.append(total_bytes)
                
                time.sleep(0.5)  # 每0.5秒采样一次
                
            except Exception as e:
                print(f"监控错误: {e}")
                break
    
    def get_statistics(self) -> Dict[str, float]:
        """获取监控统计信息"""
        if not self.cpu_samples:
            return {}
        
        duration = (self.end_time - self.start_time) if self.end_time and self.start_time else 0
        
        return {
            "duration": duration,
            "avg_cpu_percent": np.mean(self.cpu_samples),
            "max_cpu_percent": np.max(self.cpu_samples),
            "avg_memory_mb": np.mean(self.memory_samples),
            "max_memory_mb": np.max(self.memory_samples),
            "total_network_bytes": self.network_samples[-1] if self.network_samples else 0,
            "avg_network_rate": np.mean(self.network_samples) / duration if duration > 0 else 0
        }


class CostAnalyzer:
    """成本与效率分析器"""
    
    def __init__(self):
        self.resource_monitor = ResourceMonitor()
        self.cost_results = []
        self.efficiency_results = []
    
    def analyze_generation_cost(self, method: str, test_cases: List[Dict[str, Any]], 
                              generation_time: float) -> CostMetrics:
        """分析测试用例生成成本"""
        # 估算请求数量（基于测试用例复杂度）
        total_requests = self._estimate_requests_from_test_cases(test_cases)
        
        # 获取资源使用统计
        resource_stats = self.resource_monitor.get_statistics()
        
        # 计算成本指标
        cost_metrics = CostMetrics(
            method=method,
            total_requests=total_requests,
            execution_time=generation_time,
            cpu_usage=resource_stats.get("avg_cpu_percent", 0),
            memory_usage=resource_stats.get("avg_memory_mb", 0),
            network_traffic=resource_stats.get("total_network_bytes", 0),
            storage_usage=self._calculate_storage_usage(test_cases),
            cost_per_test_case=generation_time / len(test_cases) if test_cases else 0,
            cost_per_coverage_percent=0  # 将在执行后更新
        )
        
        self.cost_results.append(cost_metrics)
        return cost_metrics
    
    def analyze_execution_cost(self, method: str, execution_results: Dict[str, Any]) -> CostMetrics:
        """分析测试用例执行成本"""
        # 从执行结果中提取成本信息
        total_requests = execution_results.get("total_requests", 0)
        execution_time = execution_results.get("execution_time", 0)
        
        # 获取资源使用统计
        resource_stats = self.resource_monitor.get_statistics()
        
        # 计算成本指标
        cost_metrics = CostMetrics(
            method=method,
            total_requests=total_requests,
            execution_time=execution_time,
            cpu_usage=resource_stats.get("avg_cpu_percent", 0),
            memory_usage=resource_stats.get("avg_memory_mb", 0),
            network_traffic=resource_stats.get("total_network_bytes", 0),
            storage_usage=execution_results.get("storage_usage", 0),
            cost_per_test_case=execution_time / max(execution_results.get("test_cases_executed", 1), 1),
            cost_per_coverage_percent=0  # 将在计算覆盖率后更新
        )
        
        return cost_metrics
    
    def analyze_efficiency(self, method: str, test_cases: List[Dict[str, Any]], 
                         generation_time: float, execution_time: float, 
                         coverage_percentage: float) -> EfficiencyMetrics:
        """分析效率指标"""
        total_time = generation_time + execution_time
        test_cases_count = len(test_cases)
        
        # 计算效率分数（覆盖率/时间）
        efficiency_score = coverage_percentage / total_time if total_time > 0 else 0
        
        # 计算可扩展性分数（测试用例数/时间）
        scalability_score = test_cases_count / total_time if total_time > 0 else 0
        
        efficiency_metrics = EfficiencyMetrics(
            method=method,
            test_cases_generated=test_cases_count,
            coverage_achieved=coverage_percentage,
            time_to_generate=generation_time,
            time_to_execute=execution_time,
            total_time=total_time,
            efficiency_score=efficiency_score,
            scalability_score=scalability_score
        )
        
        self.efficiency_results.append(efficiency_metrics)
        return efficiency_metrics
    
    def _estimate_requests_from_test_cases(self, test_cases: List[Dict[str, Any]]) -> int:
        """从测试用例估算请求数量"""
        total_requests = 0
        
        for test_case in test_cases:
            # 基础请求数
            base_requests = 1
            
            # 根据维度复杂度增加请求数
            dimensions = test_case.get("dimensions", {})
            complexity_multiplier = 1
            
            for dim_name, dim_value in dimensions.items():
                if dim_value is None:
                    continue
                
                if dim_name in ["headers", "uri_patterns"]:
                    complexity_multiplier += 0.5
                elif dim_name == "destinations":
                    complexity_multiplier += 0.3
                elif dim_name == "weights":
                    # 权重组合可能需要多次验证
                    if isinstance(dim_value, dict):
                        secondary = dim_value.get("secondary", 0)
                        if secondary > 0:
                            complexity_multiplier += 0.5
                elif dim_name in ["policies", "load_balancing", "connection_pool"]:
                    complexity_multiplier += 0.2
            
            total_requests += int(base_requests * complexity_multiplier)
        
        return total_requests
    
    def _calculate_storage_usage(self, test_cases: List[Dict[str, Any]]) -> float:
        """计算存储使用量"""
        # 序列化测试用例以估算大小
        json_str = json.dumps(test_cases)
        size_bytes = len(json_str.encode('utf-8'))
        size_mb = size_bytes / (1024 * 1024)
        
        # 添加日志和结果文件的估算
        estimated_log_size = len(test_cases) * 0.1  # 每个测试用例约0.1MB日志
        estimated_result_size = len(test_cases) * 0.05  # 每个测试用例约0.05MB结果
        
        return size_mb + estimated_log_size + estimated_result_size
    
    def compare_methods(self) -> Dict[str, Any]:
        """比较不同方法的成本和效率"""
        if not self.cost_results or not self.efficiency_results:
            return {}
        
        comparison = {
            "cost_comparison": {},
            "efficiency_comparison": {},
            "ranking": {},
            "statistical_analysis": {}
        }
        
        # 成本比较
        for cost_metric in self.cost_results:
            method = cost_metric.method
            comparison["cost_comparison"][method] = {
                "total_requests": cost_metric.total_requests,
                "execution_time": cost_metric.execution_time,
                "cpu_usage": cost_metric.cpu_usage,
                "memory_usage": cost_metric.memory_usage,
                "cost_per_test_case": cost_metric.cost_per_test_case
            }
        
        # 效率比较
        for efficiency_metric in self.efficiency_results:
            method = efficiency_metric.method
            comparison["efficiency_comparison"][method] = {
                "test_cases_generated": efficiency_metric.test_cases_generated,
                "coverage_achieved": efficiency_metric.coverage_achieved,
                "total_time": efficiency_metric.total_time,
                "efficiency_score": efficiency_metric.efficiency_score,
                "scalability_score": efficiency_metric.scalability_score
            }
        
        # 排名
        methods = list(comparison["efficiency_comparison"].keys())
        
        # 按效率分数排名
        efficiency_ranking = sorted(methods, 
                                  key=lambda m: comparison["efficiency_comparison"][m]["efficiency_score"], 
                                  reverse=True)
        
        # 按成本排名（时间越少越好）
        cost_ranking = sorted(methods, 
                            key=lambda m: comparison["cost_comparison"][m]["execution_time"])
        
        comparison["ranking"] = {
            "efficiency": efficiency_ranking,
            "cost": cost_ranking
        }
        
        # 统计分析
        efficiency_scores = [comparison["efficiency_comparison"][m]["efficiency_score"] for m in methods]
        execution_times = [comparison["cost_comparison"][m]["execution_time"] for m in methods]
        
        comparison["statistical_analysis"] = {
            "efficiency_stats": {
                "mean": np.mean(efficiency_scores),
                "std": np.std(efficiency_scores),
                "max": np.max(efficiency_scores),
                "min": np.min(efficiency_scores)
            },
            "cost_stats": {
                "mean_time": np.mean(execution_times),
                "std_time": np.std(execution_times),
                "max_time": np.max(execution_times),
                "min_time": np.min(execution_times)
            }
        }
        
        return comparison
    
    def calculate_cost_efficiency_ratio(self, cost_metrics: CostMetrics, 
                                      efficiency_metrics: EfficiencyMetrics) -> float:
        """计算成本效率比"""
        if cost_metrics.execution_time == 0 or efficiency_metrics.coverage_achieved == 0:
            return 0
        
        # 成本效率比 = 覆盖率 / (时间 * 资源使用)
        resource_cost = (cost_metrics.cpu_usage + cost_metrics.memory_usage / 100) / 100
        total_cost = cost_metrics.execution_time * (1 + resource_cost)
        
        return efficiency_metrics.coverage_achieved / total_cost
    
    def perform_sensitivity_analysis(self, base_results: Dict[str, Any], 
                                   variation_factors: Dict[str, float]) -> Dict[str, Any]:
        """执行敏感性分析"""
        sensitivity_results = {}
        
        for factor_name, factor_value in variation_factors.items():
            sensitivity_results[factor_name] = {}
            
            for method in base_results.get("methods", []):
                base_metric = base_results["efficiency_comparison"].get(method, {})
                
                # 根据因子调整指标
                adjusted_coverage = base_metric.get("coverage_achieved", 0) * factor_value
                adjusted_time = base_metric.get("total_time", 0) / factor_value
                
                # 重新计算效率分数
                adjusted_efficiency = adjusted_coverage / adjusted_time if adjusted_time > 0 else 0
                
                sensitivity_results[factor_name][method] = {
                    "original_coverage": base_metric.get("coverage_achieved", 0),
                    "adjusted_coverage": adjusted_coverage,
                    "original_time": base_metric.get("total_time", 0),
                    "adjusted_time": adjusted_time,
                    "original_efficiency": base_metric.get("efficiency_score", 0),
                    "adjusted_efficiency": adjusted_efficiency,
                    "efficiency_change": adjusted_efficiency - base_metric.get("efficiency_score", 0)
                }
        
        return sensitivity_results
    
    def analyze_scale_sensitivity(self, small_scale_results: Dict[str, Any],
                                medium_scale_results: Dict[str, Any],
                                large_scale_results: Dict[str, Any]) -> Dict[str, Any]:
        """分析规模敏感性"""
        scale_analysis = {
            "scalability_metrics": {},
            "scale_efficiency": {},
            "bottleneck_analysis": {}
        }
        
        scales = ["small", "medium", "large"]
        scale_results = [small_scale_results, medium_scale_results, large_scale_results]
        
        # 获取所有方法
        all_methods = set()
        for results in scale_results:
            all_methods.update(results.get("efficiency_comparison", {}).keys())
        
        # 分析每个方法的可扩展性
        for method in all_methods:
            method_metrics = {}
            
            for i, (scale, results) in enumerate(zip(scales, scale_results)):
                method_data = results.get("efficiency_comparison", {}).get(method, {})
                if method_data:
                    method_metrics[scale] = {
                        "test_cases": method_data.get("test_cases_generated", 0),
                        "coverage": method_data.get("coverage_achieved", 0),
                        "time": method_data.get("total_time", 0),
                        "efficiency": method_data.get("efficiency_score", 0)
                    }
            
            # 计算可扩展性指标
            if len(method_metrics) >= 2:
                # 从small到large的变化
                small_data = method_metrics.get("small", {})
                large_data = method_metrics.get("large", {})
                
                if small_data and large_data:
                    scale_analysis["scalability_metrics"][method] = {
                        "test_case_growth": (large_data["test_cases"] - small_data["test_cases"]) / small_data["test_cases"] if small_data["test_cases"] > 0 else 0,
                        "time_growth": (large_data["time"] - small_data["time"]) / small_data["time"] if small_data["time"] > 0 else 0,
                        "efficiency_change": large_data["efficiency"] - small_data["efficiency"],
                        "scalability_ratio": large_data["test_cases"] / large_data["time"] if large_data["time"] > 0 else 0
                    }
        
        # 分析规模效率
        for scale, results in zip(scales, scale_results):
            efficiency_data = results.get("efficiency_comparison", {})
            scale_efficiency = {}
            
            for method, data in efficiency_data.items():
                scale_efficiency[method] = {
                    "efficiency_per_scale": data.get("efficiency_score", 0),
                    "time_per_test_case": data.get("total_time", 0) / data.get("test_cases_generated", 1)
                }
            
            scale_analysis["scale_efficiency"][scale] = scale_efficiency
        
        return scale_analysis
    
    def export_cost_analysis_report(self, output_file: str):
        """导出成本分析报告"""
        comparison = self.compare_methods()
        
        report = {
            "cost_analysis": {
                "resource_monitoring": self.resource_monitor.get_statistics(),
                "cost_results": [
                    {
                        "method": result.method,
                        "total_requests": result.total_requests,
                        "execution_time": result.execution_time,
                        "cpu_usage": result.cpu_usage,
                        "memory_usage": result.memory_usage,
                        "network_traffic": result.network_traffic,
                        "storage_usage": result.storage_usage,
                        "cost_per_test_case": result.cost_per_test_case
                    }
                    for result in self.cost_results
                ],
                "efficiency_results": [
                    {
                        "method": result.method,
                        "test_cases_generated": result.test_cases_generated,
                        "coverage_achieved": result.coverage_achieved,
                        "time_to_generate": result.time_to_generate,
                        "time_to_execute": result.time_to_execute,
                        "total_time": result.total_time,
                        "efficiency_score": result.efficiency_score,
                        "scalability_score": result.scalability_score
                    }
                    for result in self.efficiency_results
                ]
            },
            "method_comparison": comparison,
            "recommendations": self._generate_recommendations(comparison)
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"成本分析报告已导出到: {output_file}")
    
    def _generate_recommendations(self, comparison: Dict[str, Any]) -> List[str]:
        """生成推荐建议"""
        recommendations = []
        
        if not comparison:
            return recommendations
        
        # 效率推荐
        efficiency_ranking = comparison.get("ranking", {}).get("efficiency", [])
        if efficiency_ranking:
            best_method = efficiency_ranking[0]
            recommendations.append(f"最佳效率方法: {best_method}")
        
        # 成本推荐
        cost_ranking = comparison.get("ranking", {}).get("cost", [])
        if cost_ranking:
            cheapest_method = cost_ranking[0]
            recommendations.append(f"最低成本方法: {cheapest_method}")
        
        # 统计推荐
        stats = comparison.get("statistical_analysis", {})
        efficiency_stats = stats.get("efficiency_stats", {})
        if efficiency_stats:
            efficiency_std = efficiency_stats.get("std", 0)
            if efficiency_std > efficiency_stats.get("mean", 0) * 0.5:
                recommendations.append("方法间效率差异较大，建议根据具体场景选择")
        
        return recommendations


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="成本与效率分析器")
    parser.add_argument("--results", help="测试结果文件路径")
    parser.add_argument("--output", help="输出报告文件路径")
    
    args = parser.parse_args()
    
    # 创建分析器
    analyzer = CostAnalyzer()
    
    # 模拟一些测试结果
    if not args.results:
        print("创建模拟测试结果...")
        
        # 模拟不同方法的成本数据
        methods = ["exhaustive", "orthogonal", "pairwise", "random"]
        
        for method in methods:
            # 模拟测试用例
            test_cases = [{"case_id": f"{method}_{i}", "dimensions": {}} for i in range(10)]
            
            # 开始监控
            analyzer.resource_monitor.start_monitoring()
            
            # 模拟生成时间
            generation_time = np.random.uniform(1, 10)
            time.sleep(generation_time)
            
            # 停止监控
            analyzer.resource_monitor.stop_monitoring()
            
            # 分析生成成本
            cost_metrics = analyzer.analyze_generation_cost(method, test_cases, generation_time)
            
            # 模拟执行
            execution_time = np.random.uniform(5, 20)
            coverage = np.random.uniform(60, 95)
            
            # 分析效率
            efficiency_metrics = analyzer.analyze_efficiency(
                method, test_cases, generation_time, execution_time, coverage
            )
            
            print(f"{method}: 效率分数={efficiency_metrics.efficiency_score:.3f}, "
                  f"成本/用例={cost_metrics.cost_per_test_case:.3f}s")
    
    # 比较方法
    comparison = analyzer.compare_methods()
    
    if comparison:
        print(f"\n方法比较结果:")
        print(f"效率排名: {comparison['ranking']['efficiency']}")
        print(f"成本排名: {comparison['ranking']['cost']}")
        
        stats = comparison['statistical_analysis']
        print(f"效率统计: 均值={stats['efficiency_stats']['mean']:.3f}, "
              f"标准差={stats['efficiency_stats']['std']:.3f}")
    
    # 导出报告
    if args.output:
        analyzer.export_cost_analysis_report(args.output)
    else:
        print(f"\n成本分析完成，共有 {len(analyzer.cost_results)} 个方法的成本数据")


if __name__ == "__main__":
    main()
