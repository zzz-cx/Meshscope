#!/usr/bin/env python3
"""
指标计算工具 - Precision/Recall/F1 计算
"""

import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
import json


@dataclass
class AccuracyMetrics:
    """准确性指标"""
    precision: float
    recall: float
    f1_score: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives
        }


@dataclass
class PerformanceMetrics:
    """性能指标"""
    average_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    throughput_per_second: float
    success_rate: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "average_latency_ms": self.average_latency_ms,
            "median_latency_ms": self.median_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "throughput_per_second": self.throughput_per_second,
            "success_rate": self.success_rate
        }


@dataclass
class ResourceMetrics:
    """资源使用指标"""
    cpu_usage_percent: float
    memory_usage_mb: float
    network_bandwidth_mbps: float
    disk_io_ops_per_second: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_usage_percent": self.cpu_usage_percent,
            "memory_usage_mb": self.memory_usage_mb,
            "network_bandwidth_mbps": self.network_bandwidth_mbps,
            "disk_io_ops_per_second": self.disk_io_ops_per_second
        }


class MetricsCalculator:
    """指标计算器"""
    
    @staticmethod
    def calculate_accuracy_metrics(predictions: List[bool], 
                                 ground_truth: List[bool]) -> AccuracyMetrics:
        """计算准确性指标"""
        if len(predictions) != len(ground_truth):
            raise ValueError("Predictions and ground truth must have the same length")
        
        # 转换为numpy数组
        pred = np.array(predictions)
        truth = np.array(ground_truth)
        
        # 计算混淆矩阵
        true_positives = np.sum((pred == True) & (truth == True))
        false_positives = np.sum((pred == True) & (truth == False))
        true_negatives = np.sum((pred == False) & (truth == False))
        false_negatives = np.sum((pred == False) & (truth == True))
        
        # 计算指标
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return AccuracyMetrics(
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            true_positives=int(true_positives),
            false_positives=int(false_positives),
            true_negatives=int(true_negatives),
            false_negatives=int(false_negatives)
        )
    
    @staticmethod
    def calculate_accuracy_from_issues(actual_issues: List[Dict[str, Any]], 
                                     expected_issues: int) -> AccuracyMetrics:
        """从问题列表计算准确性指标"""
        # 假设每个问题都是错误检测
        actual_count = len(actual_issues)
        
        # 简化计算：假设所有检测到的问题都是true positive
        # 实际应用中需要更复杂的匹配逻辑
        true_positives = min(actual_count, expected_issues)
        false_positives = max(0, actual_count - expected_issues)
        false_negatives = max(0, expected_issues - actual_count)
        true_negatives = max(0, 1 - actual_count)  # 简化假设
        
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return AccuracyMetrics(
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            true_positives=true_positives,
            false_positives=false_positives,
            true_negatives=true_negatives,
            false_negatives=false_negatives
        )
    
    @staticmethod
    def calculate_performance_metrics(latencies: List[float], 
                                    total_requests: int,
                                    duration_seconds: float) -> PerformanceMetrics:
        """计算性能指标"""
        if not latencies:
            return PerformanceMetrics(
                average_latency_ms=0.0,
                median_latency_ms=0.0,
                p95_latency_ms=0.0,
                p99_latency_ms=0.0,
                min_latency_ms=0.0,
                max_latency_ms=0.0,
                throughput_per_second=0.0,
                success_rate=0.0
            )
        
        latencies_ms = np.array(latencies) * 1000  # 转换为毫秒
        
        # 基本统计
        average_latency = np.mean(latencies_ms)
        median_latency = np.median(latencies_ms)
        min_latency = np.min(latencies_ms)
        max_latency = np.max(latencies_ms)
        
        # 百分位数
        p95_latency = np.percentile(latencies_ms, 95)
        p99_latency = np.percentile(latencies_ms, 99)
        
        # 吞吐量和成功率
        throughput = total_requests / duration_seconds if duration_seconds > 0 else 0.0
        success_rate = len(latencies) / total_requests if total_requests > 0 else 0.0
        
        return PerformanceMetrics(
            average_latency_ms=average_latency,
            median_latency_ms=median_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            min_latency_ms=min_latency,
            max_latency_ms=max_latency,
            throughput_per_second=throughput,
            success_rate=success_rate
        )
    
    @staticmethod
    def calculate_bootstrap_confidence_interval(data: List[float], 
                                              confidence: float = 0.95,
                                              n_bootstrap: int = 1000) -> Tuple[float, float]:
        """计算bootstrap置信区间"""
        if not data:
            return 0.0, 0.0
        
        data_array = np.array(data)
        bootstrap_means = []
        
        for _ in range(n_bootstrap):
            # 有放回抽样
            bootstrap_sample = np.random.choice(data_array, size=len(data_array), replace=True)
            bootstrap_means.append(np.mean(bootstrap_sample))
        
        bootstrap_means = np.array(bootstrap_means)
        
        # 计算置信区间
        alpha = 1 - confidence
        lower_percentile = (alpha / 2) * 100
        upper_percentile = (1 - alpha / 2) * 100
        
        lower_bound = np.percentile(bootstrap_means, lower_percentile)
        upper_bound = np.percentile(bootstrap_means, upper_percentile)
        
        return lower_bound, upper_bound
    
    @staticmethod
    def calculate_aggregate_metrics(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算聚合指标"""
        if not metrics_list:
            return {}
        
        # 提取各种指标
        precisions = [m.get("precision", 0.0) for m in metrics_list]
        recalls = [m.get("recall", 0.0) for m in metrics_list]
        f1_scores = [m.get("f1_score", 0.0) for m in metrics_list]
        latencies = [m.get("total_time", 0.0) for m in metrics_list]
        
        # 计算统计信息
        aggregate = {
            "count": len(metrics_list),
            "precision": {
                "mean": np.mean(precisions),
                "std": np.std(precisions),
                "min": np.min(precisions),
                "max": np.max(precisions),
                "median": np.median(precisions)
            },
            "recall": {
                "mean": np.mean(recalls),
                "std": np.std(recalls),
                "min": np.min(recalls),
                "max": np.max(recalls),
                "median": np.median(recalls)
            },
            "f1_score": {
                "mean": np.mean(f1_scores),
                "std": np.std(f1_scores),
                "min": np.min(f1_scores),
                "max": np.max(f1_scores),
                "median": np.median(f1_scores)
            },
            "latency": {
                "mean": np.mean(latencies),
                "std": np.std(latencies),
                "min": np.min(latencies),
                "max": np.max(latencies),
                "median": np.median(latencies)
            }
        }
        
        # 计算置信区间
        if len(metrics_list) >= 10:  # 至少10个样本才计算置信区间
            precision_ci = MetricsCalculator.calculate_bootstrap_confidence_interval(precisions)
            recall_ci = MetricsCalculator.calculate_bootstrap_confidence_interval(recalls)
            f1_ci = MetricsCalculator.calculate_bootstrap_confidence_interval(f1_scores)
            latency_ci = MetricsCalculator.calculate_bootstrap_confidence_interval(latencies)
            
            aggregate["precision"]["ci_95"] = precision_ci
            aggregate["recall"]["ci_95"] = recall_ci
            aggregate["f1_score"]["ci_95"] = f1_ci
            aggregate["latency"]["ci_95"] = latency_ci
        
        return aggregate


class StatisticalTests:
    """统计检验工具"""
    
    @staticmethod
    def wilcoxon_signed_rank_test(data1: List[float], data2: List[float]) -> Dict[str, Any]:
        """Wilcoxon符号秩检验 - 用于比较延迟差异"""
        try:
            from scipy import stats
            
            if len(data1) != len(data2):
                raise ValueError("Data sets must have the same length")
            
            statistic, p_value = stats.wilcoxon(data1, data2)
            
            return {
                "test_name": "Wilcoxon Signed Rank Test",
                "statistic": statistic,
                "p_value": p_value,
                "significant": p_value < 0.05,
                "interpretation": "Significant difference" if p_value < 0.05 else "No significant difference"
            }
        
        except ImportError:
            # 如果没有scipy，使用简化的实现
            return {
                "test_name": "Wilcoxon Signed Rank Test (simplified)",
                "error": "scipy not available, using simplified test",
                "mean_diff": np.mean(data2) - np.mean(data1),
                "significant": abs(np.mean(data2) - np.mean(data1)) > np.std(data1 + data2)
            }
    
    @staticmethod
    def mcnemar_test(actual1: List[bool], actual2: List[bool]) -> Dict[str, Any]:
        """McNemar检验 - 用于比较检测率差异"""
        try:
            from scipy import stats
            
            if len(actual1) != len(actual2):
                raise ValueError("Data sets must have the same length")
            
            # 构建2x2列联表
            both_detected = sum(a1 and a2 for a1, a2 in zip(actual1, actual2))
            only_1 = sum(a1 and not a2 for a1, a2 in zip(actual1, actual2))
            only_2 = sum(not a1 and a2 for a1, a2 in zip(actual1, actual2))
            neither = sum(not a1 and not a2 for a1, a2 in zip(actual1, actual2))
            
            # McNemar检验
            statistic, p_value = stats.mcnemar([[both_detected, only_1], [only_2, neither]])
            
            return {
                "test_name": "McNemar Test",
                "statistic": statistic,
                "p_value": p_value,
                "significant": p_value < 0.05,
                "contingency_table": {
                    "both_detected": both_detected,
                    "only_method_1": only_1,
                    "only_method_2": only_2,
                    "neither": neither
                },
                "interpretation": "Significant difference" if p_value < 0.05 else "No significant difference"
            }
        
        except ImportError:
            # 如果没有scipy，使用简化的实现
            detection_rate_1 = sum(actual1) / len(actual1) if actual1 else 0
            detection_rate_2 = sum(actual2) / len(actual2) if actual2 else 0
            
            return {
                "test_name": "McNemar Test (simplified)",
                "error": "scipy not available, using simplified test",
                "detection_rate_1": detection_rate_1,
                "detection_rate_2": detection_rate_2,
                "difference": detection_rate_2 - detection_rate_1,
                "significant": abs(detection_rate_2 - detection_rate_1) > 0.1  # 10%阈值
            }


class MetricsAnalyzer:
    """指标分析器"""
    
    def __init__(self):
        self.calculator = MetricsCalculator()
        self.statistical_tests = StatisticalTests()
    
    def analyze_experiment_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析实验结果"""
        analysis = {
            "summary": {},
            "accuracy_analysis": {},
            "performance_analysis": {},
            "statistical_tests": {},
            "recommendations": []
        }
        
        if not results:
            return analysis
        
        # 基本统计
        analysis["summary"] = {
            "total_experiments": len(results),
            "successful_experiments": len([r for r in results if not r.get("error")]),
            "failed_experiments": len([r for r in results if r.get("error")])
        }
        
        # 准确性分析
        accuracy_metrics = [r.get("accuracy_metrics", {}) for r in results if "accuracy_metrics" in r]
        if accuracy_metrics:
            analysis["accuracy_analysis"] = self.calculator.calculate_aggregate_metrics(accuracy_metrics)
        
        # 性能分析
        performance_data = []
        for result in results:
            if "total_time" in result:
                performance_data.append({
                    "total_time": result["total_time"],
                    "method": result.get("method", "unknown")
                })
        
        if performance_data:
            analysis["performance_analysis"] = self._analyze_performance(performance_data)
        
        # 统计检验
        if len(results) >= 2:
            analysis["statistical_tests"] = self._perform_statistical_tests(results)
        
        # 生成建议
        analysis["recommendations"] = self._generate_recommendations(analysis)
        
        return analysis
    
    def _analyze_performance(self, performance_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析性能数据"""
        methods = {}
        
        for data in performance_data:
            method = data.get("method", "unknown")
            if method not in methods:
                methods[method] = []
            methods[method].append(data["total_time"])
        
        analysis = {}
        for method, latencies in methods.items():
            analysis[method] = self.calculator.calculate_performance_metrics(
                latencies, len(latencies), max(latencies) if latencies else 1
            ).to_dict()
        
        return analysis
    
    def _perform_statistical_tests(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行统计检验"""
        tests = {}
        
        # 按方法分组
        method_results = {}
        for result in results:
            method = result.get("method", "unknown")
            if method not in method_results:
                method_results[method] = []
            method_results[method].append(result)
        
        methods = list(method_results.keys())
        
        if len(methods) >= 2:
            # 比较前两种方法
            method1, method2 = methods[0], methods[1]
            
            latencies1 = [r.get("total_time", 0) for r in method_results[method1]]
            latencies2 = [r.get("total_time", 0) for r in method_results[method2]]
            
            if latencies1 and latencies2:
                # Wilcoxon检验
                tests["latency_comparison"] = self.statistical_tests.wilcoxon_signed_rank_test(
                    latencies1, latencies2
                )
            
            # McNemar检验（如果有检测结果）
            detections1 = [1 if r.get("accuracy_metrics", {}).get("actual_issues", 0) > 0 else 0 
                          for r in method_results[method1]]
            detections2 = [1 if r.get("accuracy_metrics", {}).get("actual_issues", 0) > 0 else 0 
                          for r in method_results[method2]]
            
            if detections1 and detections2 and len(detections1) == len(detections2):
                tests["detection_rate_comparison"] = self.statistical_tests.mcnemar_test(
                    detections1, detections2
                )
        
        return tests
    
    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        # 基于准确性分析
        accuracy = analysis.get("accuracy_analysis", {})
        if accuracy:
            f1_mean = accuracy.get("f1_score", {}).get("mean", 0)
            if f1_mean < 0.8:
                recommendations.append("考虑优化检测算法以提高准确性")
            
            precision_mean = accuracy.get("precision", {}).get("mean", 0)
            if precision_mean < 0.9:
                recommendations.append("存在较多误报，建议调整检测阈值")
        
        # 基于性能分析
        performance = analysis.get("performance_analysis", {})
        if performance:
            for method, metrics in performance.items():
                avg_latency = metrics.get("average_latency_ms", 0)
                if avg_latency > 5000:  # 5秒
                    recommendations.append(f"{method}方法的平均延迟较高，建议优化")
        
        # 基于统计检验
        tests = analysis.get("statistical_tests", {})
        if tests.get("latency_comparison", {}).get("significant"):
            recommendations.append("不同方法间存在显著的性能差异")
        
        return recommendations


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="指标计算工具测试")
    parser.add_argument("--input", help="输入结果文件")
    parser.add_argument("--output", help="输出分析文件")
    
    args = parser.parse_args()
    
    # 示例数据
    sample_results = [
        {
            "method": "static_only",
            "total_time": 1.2,
            "accuracy_metrics": {"precision": 0.85, "recall": 0.90, "f1_score": 0.87, "actual_issues": 1},
            "success": True
        },
        {
            "method": "dynamic_only", 
            "total_time": 45.6,
            "accuracy_metrics": {"precision": 0.95, "recall": 0.85, "f1_score": 0.90, "actual_issues": 1},
            "success": True
        },
        {
            "method": "hybrid",
            "total_time": 12.3,
            "accuracy_metrics": {"precision": 0.92, "recall": 0.95, "f1_score": 0.93, "actual_issues": 1},
            "success": True
        }
    ]
    
    # 分析结果
    analyzer = MetricsAnalyzer()
    analysis = analyzer.analyze_experiment_results(sample_results)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        print(f"Analysis saved to {args.output}")
    else:
        print(json.dumps(analysis, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
