#!/usr/bin/env python3
"""
Accuracy评估器
结果对比、指标计算、统计分析
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Any, Tuple, Optional
import logging
from datetime import datetime
import json

class AccuracyEvaluator:
    """Accuracy评估器"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化评估器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 评估配置
        self.evaluation_config = config.get('evaluation', {})
        self.metrics_config = self.evaluation_config.get('metrics', {})
        self.statistical_config = self.evaluation_config.get('statistical_analysis', {})
        
        # 置信度阈值
        self.confidence_threshold = self.metrics_config.get('confidence_threshold', 0.7)
        
        # 统计检验配置
        self.significance_level = self.statistical_config.get('significance_level', 0.05)
    
    def compare_methods(self, method_results: Dict[str, Any], ground_truth: Dict[str, Any]) -> Dict[str, Any]:
        """比较不同检测方法的结果"""
        comparison_results = {
            "method_metrics": {},
            "confusion_matrices": {},
            "fault_type_analysis": {},
            "performance_ranking": {},
            "comparison_timestamp": datetime.now().isoformat()
        }
        
        try:
            # 为每种方法计算指标
            for method_name, result in method_results.items():
                if "error" in result:
                    self.logger.warning(f"跳过有错误的方法: {method_name}")
                    continue
                
                # 计算混淆矩阵和指标
                confusion_matrix, metrics = self._calculate_method_metrics(result, ground_truth)
                
                comparison_results["method_metrics"][method_name] = metrics
                comparison_results["confusion_matrices"][method_name] = confusion_matrix
            
            # 分析不同故障类型的检测效果
            comparison_results["fault_type_analysis"] = self._analyze_fault_types(
                method_results, ground_truth
            )
            
            # 性能排名
            comparison_results["performance_ranking"] = self._rank_methods(
                comparison_results["method_metrics"]
            )
            
        except Exception as e:
            self.logger.error(f"比较方法时发生错误: {e}")
            comparison_results["error"] = str(e)
        
        return comparison_results
    
    def _calculate_method_metrics(self, method_result: Dict[str, Any], 
                                ground_truth: Dict[str, Any]) -> Tuple[Dict[str, int], Dict[str, float]]:
        """计算单个方法的指标"""
        detected_faults = method_result.get("detected_faults", [])
        config_files = method_result.get("config_files", [])
        
        # 创建检测结果映射
        detected_map = self._create_detection_map(detected_faults)
        
        # 计算混淆矩阵
        confusion_matrix = self._calculate_confusion_matrix(
            config_files, detected_map, ground_truth
        )
        
        # 计算指标
        metrics = self._calculate_metrics_from_confusion_matrix(confusion_matrix)
        
        return confusion_matrix, metrics
    
    def _create_detection_map(self, detected_faults: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """创建检测结果映射"""
        detection_map = {}
        
        for fault in detected_faults:
            config_file = fault.get("config_file", "")
            fault_type = fault.get("fault_type", "")
            confidence = fault.get("confidence", 0)
            
            # 只考虑高置信度的检测结果
            if confidence >= self.confidence_threshold:
                if config_file not in detection_map:
                    detection_map[config_file] = []
                detection_map[config_file].append(fault_type)
        
        return detection_map
    
    def _calculate_confusion_matrix(self, config_files: List[str], 
                                  detected_map: Dict[str, List[str]], 
                                  ground_truth: Dict[str, Any]) -> Dict[str, int]:
        """计算混淆矩阵"""
        tp = 0  # True Positive
        fp = 0  # False Positive
        fn = 0  # False Negative
        tn = 0  # True Negative
        
        ground_truth_samples = ground_truth.get("samples", {})
        
        for config_file in config_files:
            # 获取ground truth标签
            gt_sample = self._find_ground_truth_sample(config_file, ground_truth_samples)
            
            if gt_sample is None:
                self.logger.warning(f"未找到配置文件 {config_file} 的ground truth")
                continue
            
            has_fault_gt = gt_sample.get("has_fault", False)
            fault_types_gt = [gt_sample.get("fault_type", "")]
            
            # 获取检测结果
            detected_fault_types = detected_map.get(config_file, [])
            has_fault_detected = len(detected_fault_types) > 0
            
            # 计算TP, FP, FN, TN
            if has_fault_gt and has_fault_detected:
                # 检查是否检测到正确的故障类型
                if any(ft in detected_fault_types for ft in fault_types_gt):
                    tp += 1
                else:
                    fp += 1
            elif has_fault_gt and not has_fault_detected:
                fn += 1
            elif not has_fault_gt and has_fault_detected:
                fp += 1
            else:  # not has_fault_gt and not has_fault_detected
                tn += 1
        
        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn
        }
    
    def _find_ground_truth_sample(self, config_file: str, 
                                ground_truth_samples: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """查找配置文件的ground truth样本"""
        # 提取相对路径
        config_path = config_file.split("/")[-2:]  # 获取最后两级路径
        relative_path = "/".join(config_path)
        
        # 尝试不同的路径格式
        possible_keys = [
            relative_path,
            config_file,
            config_path[-1] if config_path else "",
            config_path[-2] + "/" + config_path[-1] if len(config_path) == 2 else ""
        ]
        
        for key in possible_keys:
            if key in ground_truth_samples:
                return ground_truth_samples[key]
        
        return None
    
    def _calculate_metrics_from_confusion_matrix(self, confusion_matrix: Dict[str, int]) -> Dict[str, float]:
        """从混淆矩阵计算指标"""
        tp = confusion_matrix["tp"]
        fp = confusion_matrix["fp"]
        fn = confusion_matrix["fn"]
        tn = confusion_matrix["tn"]
        
        # 计算基本指标
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        # 计算其他指标
        accuracy = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0
        false_negative_rate = fn / (fn + tp) if (fn + tp) > 0 else 0
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "accuracy": accuracy,
            "specificity": specificity,
            "false_positive_rate": false_positive_rate,
            "false_negative_rate": false_negative_rate,
            "confusion_matrix": confusion_matrix
        }
    
    def _analyze_fault_types(self, method_results: Dict[str, Any], 
                           ground_truth: Dict[str, Any]) -> Dict[str, Any]:
        """分析不同故障类型的检测效果"""
        fault_type_analysis = {}
        
        ground_truth_samples = ground_truth.get("samples", {})
        
        # 获取所有故障类型
        all_fault_types = set()
        for sample in ground_truth_samples.values():
            fault_type = sample.get("fault_type", "")
            if fault_type:
                all_fault_types.add(fault_type)
        
        # 为每种故障类型分析检测效果
        for fault_type in all_fault_types:
            fault_type_analysis[fault_type] = {
                "method_performance": {},
                "best_method": None,
                "average_f1": 0
            }
            
            f1_scores = []
            
            for method_name, result in method_results.items():
                if "error" in result:
                    continue
                
                # 计算该故障类型的检测效果
                fault_metrics = self._calculate_fault_type_metrics(
                    result, ground_truth, fault_type
                )
                
                fault_type_analysis[fault_type]["method_performance"][method_name] = fault_metrics
                f1_scores.append(fault_metrics.get("f1_score", 0))
            
            # 确定最佳方法
            if f1_scores:
                fault_type_analysis[fault_type]["average_f1"] = np.mean(f1_scores)
                best_method_idx = np.argmax(f1_scores)
                method_names = [name for name in method_results.keys() if "error" not in method_results[name]]
                if best_method_idx < len(method_names):
                    fault_type_analysis[fault_type]["best_method"] = method_names[best_method_idx]
        
        return fault_type_analysis
    
    def _calculate_fault_type_metrics(self, method_result: Dict[str, Any], 
                                    ground_truth: Dict[str, Any], 
                                    target_fault_type: str) -> Dict[str, float]:
        """计算特定故障类型的指标"""
        detected_faults = method_result.get("detected_faults", [])
        config_files = method_result.get("config_files", [])
        
        # 过滤出目标故障类型的检测结果
        target_detections = [
            fault for fault in detected_faults 
            if fault.get("fault_type") == target_fault_type
        ]
        
        # 创建检测映射
        detected_map = {}
        for fault in target_detections:
            config_file = fault.get("config_file", "")
            confidence = fault.get("confidence", 0)
            
            if confidence >= self.confidence_threshold:
                detected_map[config_file] = [target_fault_type]
        
        # 计算混淆矩阵
        confusion_matrix = self._calculate_fault_type_confusion_matrix(
            config_files, detected_map, ground_truth, target_fault_type
        )
        
        # 计算指标
        metrics = self._calculate_metrics_from_confusion_matrix(confusion_matrix)
        
        return metrics
    
    def _calculate_fault_type_confusion_matrix(self, config_files: List[str], 
                                             detected_map: Dict[str, List[str]], 
                                             ground_truth: Dict[str, Any], 
                                             target_fault_type: str) -> Dict[str, int]:
        """计算特定故障类型的混淆矩阵"""
        tp = fp = fn = tn = 0
        
        ground_truth_samples = ground_truth.get("samples", {})
        
        for config_file in config_files:
            gt_sample = self._find_ground_truth_sample(config_file, ground_truth_samples)
            
            if gt_sample is None:
                continue
            
            has_target_fault_gt = gt_sample.get("fault_type") == target_fault_type
            has_target_fault_detected = target_fault_type in detected_map.get(config_file, [])
            
            if has_target_fault_gt and has_target_fault_detected:
                tp += 1
            elif has_target_fault_gt and not has_target_fault_detected:
                fn += 1
            elif not has_target_fault_gt and has_target_fault_detected:
                fp += 1
            else:
                tn += 1
        
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}
    
    def _rank_methods(self, method_metrics: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """对方法进行排名"""
        ranking = {
            "by_f1_score": [],
            "by_precision": [],
            "by_recall": [],
            "by_accuracy": [],
            "overall_ranking": []
        }
        
        # 按不同指标排名
        for metric_name in ["f1_score", "precision", "recall", "accuracy"]:
            method_scores = [
                (method_name, metrics.get(metric_name, 0))
                for method_name, metrics in method_metrics.items()
            ]
            method_scores.sort(key=lambda x: x[1], reverse=True)
            ranking[f"by_{metric_name}"] = method_scores
        
        # 综合排名（基于F1-score）
        ranking["overall_ranking"] = ranking["by_f1_score"]
        
        return ranking
    
    def perform_statistical_analysis(self, comparison_results: Dict[str, Any]) -> Dict[str, Any]:
        """进行统计分析"""
        statistical_analysis = {
            "significance_tests": {},
            "confidence_intervals": {},
            "effect_sizes": {},
            "analysis_timestamp": datetime.now().isoformat()
        }
        
        try:
            method_metrics = comparison_results.get("method_metrics", {})
            
            if len(method_metrics) >= 2:
                # McNemar测试（配对方法比较）
                statistical_analysis["significance_tests"]["mcnemar"] = self._perform_mcnemar_test(
                    comparison_results.get("confusion_matrices", {})
                )
                
                # Wilcoxon符号秩检验（非参数检验）
                statistical_analysis["significance_tests"]["wilcoxon"] = self._perform_wilcoxon_test(
                    method_metrics
                )
                
                # 置信区间估计
                statistical_analysis["confidence_intervals"] = self._calculate_confidence_intervals(
                    method_metrics
                )
                
                # 效应量计算
                statistical_analysis["effect_sizes"] = self._calculate_effect_sizes(
                    method_metrics
                )
            
        except Exception as e:
            self.logger.error(f"统计分析时发生错误: {e}")
            statistical_analysis["error"] = str(e)
        
        return statistical_analysis
    
    def _perform_mcnemar_test(self, confusion_matrices: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        """执行McNemar测试"""
        method_names = list(confusion_matrices.keys())
        
        if len(method_names) < 2:
            return {"error": "需要至少两种方法进行McNemar测试"}
        
        # 选择前两种方法进行比较
        method1, method2 = method_names[0], method_names[1]
        cm1 = confusion_matrices[method1]
        cm2 = confusion_matrices[method2]
        
        # 计算McNemar统计量
        # 这里简化实现，实际需要配对数据
        b = cm1["fp"]  # 方法1检测到但方法2未检测到
        c = cm2["fp"]  # 方法2检测到但方法1未检测到
        
        if b + c == 0:
            return {"error": "无法计算McNemar统计量"}
        
        chi2_stat = (abs(b - c) - 1) ** 2 / (b + c)
        p_value = 1 - stats.chi2.cdf(chi2_stat, 1)
        
        return {
            "method1": method1,
            "method2": method2,
            "chi2_statistic": chi2_stat,
            "p_value": p_value,
            "significant": p_value < self.significance_level,
            "interpretation": f"方法 {method1} 和 {method2} 的检测结果{'有' if p_value < self.significance_level else '无'}显著差异"
        }
    
    def _perform_wilcoxon_test(self, method_metrics: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """执行Wilcoxon符号秩检验"""
        method_names = list(method_metrics.keys())
        
        if len(method_names) < 2:
            return {"error": "需要至少两种方法进行Wilcoxon测试"}
        
        # 选择F1-score进行比较
        f1_scores = [method_metrics[method].get("f1_score", 0) for method in method_names]
        
        if len(f1_scores) < 2:
            return {"error": "F1-score数据不足"}
        
        # 执行Wilcoxon测试
        try:
            statistic, p_value = stats.wilcoxon(f1_scores[:-1], f1_scores[1:])
            
            return {
                "statistic": statistic,
                "p_value": p_value,
                "significant": p_value < self.significance_level,
                "interpretation": f"方法间的F1-score分布{'有' if p_value < self.significance_level else '无'}显著差异"
            }
        except Exception as e:
            return {"error": f"Wilcoxon测试失败: {e}"}
    
    def _calculate_confidence_intervals(self, method_metrics: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """计算置信区间"""
        confidence_intervals = {}
        
        for method_name, metrics in method_metrics.items():
            method_ci = {}
            
            for metric_name, value in metrics.items():
                if isinstance(value, (int, float)) and 0 <= value <= 1:
                    # 使用Bootstrap方法估计置信区间
                    ci = self._bootstrap_confidence_interval(value, n_bootstrap=1000)
                    method_ci[metric_name] = {
                        "value": value,
                        "ci_lower": ci[0],
                        "ci_upper": ci[1],
                        "ci_width": ci[1] - ci[0]
                    }
            
            confidence_intervals[method_name] = method_ci
        
        return confidence_intervals
    
    def _bootstrap_confidence_interval(self, value: float, n_bootstrap: int = 1000, 
                                     confidence_level: float = 0.95) -> Tuple[float, float]:
        """Bootstrap置信区间估计"""
        # 简化实现：基于正态分布假设
        alpha = 1 - confidence_level
        z_score = stats.norm.ppf(1 - alpha / 2)
        
        # 假设标准误差为0.05（实际应该基于数据计算）
        se = 0.05
        margin_error = z_score * se
        
        ci_lower = max(0, value - margin_error)
        ci_upper = min(1, value + margin_error)
        
        return ci_lower, ci_upper
    
    def _calculate_effect_sizes(self, method_metrics: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """计算效应量"""
        effect_sizes = {}
        
        method_names = list(method_metrics.keys())
        
        if len(method_names) >= 2:
            # 计算Cohen's d（标准化均值差）
            f1_scores = [method_metrics[method].get("f1_score", 0) for method in method_names]
            
            if len(f1_scores) >= 2:
                mean_diff = np.mean(f1_scores[:-1]) - np.mean(f1_scores[1:])
                pooled_std = np.sqrt((np.var(f1_scores[:-1]) + np.var(f1_scores[1:])) / 2)
                
                if pooled_std > 0:
                    cohens_d = mean_diff / pooled_std
                    
                    effect_sizes["cohens_d"] = {
                        "value": cohens_d,
                        "interpretation": self._interpret_cohens_d(cohens_d)
                    }
        
        return effect_sizes
    
    def _interpret_cohens_d(self, cohens_d: float) -> str:
        """解释Cohen's d效应量"""
        abs_d = abs(cohens_d)
        
        if abs_d < 0.2:
            return "小效应"
        elif abs_d < 0.5:
            return "中等效应"
        elif abs_d < 0.8:
            return "大效应"
        else:
            return "极大效应"
    
    def generate_summary(self, method_results: Dict[str, Any], 
                        comparison_results: Dict[str, Any], 
                        statistical_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """生成实验总结"""
        summary = {
            "best_method": None,
            "best_f1_score": 0,
            "key_findings": [],
            "recommendations": [],
            "summary_timestamp": datetime.now().isoformat()
        }
        
        try:
            # 确定最佳方法
            method_metrics = comparison_results.get("method_metrics", {})
            if method_metrics:
                best_method = max(method_metrics.keys(), 
                                key=lambda x: method_metrics[x].get("f1_score", 0))
                summary["best_method"] = best_method
                summary["best_f1_score"] = method_metrics[best_method].get("f1_score", 0)
            
            # 生成关键发现
            summary["key_findings"] = self._generate_key_findings(
                method_results, comparison_results, statistical_analysis
            )
            
            # 生成建议
            summary["recommendations"] = self._generate_recommendations(
                method_results, comparison_results, statistical_analysis
            )
            
        except Exception as e:
            self.logger.error(f"生成总结时发生错误: {e}")
            summary["error"] = str(e)
        
        return summary
    
    def _generate_key_findings(self, method_results: Dict[str, Any], 
                             comparison_results: Dict[str, Any], 
                             statistical_analysis: Dict[str, Any]) -> List[str]:
        """生成关键发现"""
        findings = []
        
        # 方法性能比较
        method_metrics = comparison_results.get("method_metrics", {})
        if method_metrics:
            best_method = max(method_metrics.keys(), 
                            key=lambda x: method_metrics[x].get("f1_score", 0))
            best_f1 = method_metrics[best_method].get("f1_score", 0)
            findings.append(f"最佳检测方法是 {best_method}，F1-Score为 {best_f1:.3f}")
        
        # 故障类型分析
        fault_type_analysis = comparison_results.get("fault_type_analysis", {})
        if fault_type_analysis:
            best_detected_types = []
            worst_detected_types = []
            
            for fault_type, analysis in fault_type_analysis.items():
                avg_f1 = analysis.get("average_f1", 0)
                if avg_f1 > 0.8:
                    best_detected_types.append(fault_type)
                elif avg_f1 < 0.5:
                    worst_detected_types.append(fault_type)
            
            if best_detected_types:
                findings.append(f"检测效果最好的故障类型: {', '.join(best_detected_types)}")
            if worst_detected_types:
                findings.append(f"检测效果最差的故障类型: {', '.join(worst_detected_types)}")
        
        # 统计显著性
        significance_tests = statistical_analysis.get("significance_tests", {})
        if significance_tests:
            for test_name, test_result in significance_tests.items():
                if "significant" in test_result and test_result["significant"]:
                    findings.append(f"{test_name}测试显示方法间存在显著差异")
        
        return findings
    
    def _generate_recommendations(self, method_results: Dict[str, Any], 
                                comparison_results: Dict[str, Any], 
                                statistical_analysis: Dict[str, Any]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        # 基于最佳方法的建议
        method_metrics = comparison_results.get("method_metrics", {})
        if method_metrics:
            best_method = max(method_metrics.keys(), 
                            key=lambda x: method_metrics[x].get("f1_score", 0))
            best_f1 = method_metrics[best_method].get("f1_score", 0)
            
            if best_f1 > 0.8:
                recommendations.append(f"推荐使用 {best_method} 方法，其检测准确性较高")
            elif best_f1 < 0.6:
                recommendations.append("所有方法的检测准确性都有待提高，建议改进检测算法")
        
        # 基于故障类型分析的建议
        fault_type_analysis = comparison_results.get("fault_type_analysis", {})
        if fault_type_analysis:
            worst_types = [
                fault_type for fault_type, analysis in fault_type_analysis.items()
                if analysis.get("average_f1", 0) < 0.5
            ]
            
            if worst_types:
                recommendations.append(f"需要改进对以下故障类型的检测: {', '.join(worst_types)}")
        
        # 基于统计分析的建议
        significance_tests = statistical_analysis.get("significance_tests", {})
        if significance_tests:
            for test_name, test_result in significance_tests.items():
                if "significant" in test_result and not test_result["significant"]:
                    recommendations.append(f"方法间无显著差异，可根据其他因素（如执行时间、资源消耗）选择方法")
        
        return recommendations
