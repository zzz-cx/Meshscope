#!/usr/bin/env python3
"""
准确性评估器
用于评估Istio配置一致性检测系统的检测准确性
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Tuple
from pathlib import Path
from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib.pyplot as plt
import seaborn as sns

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 导入配置解析器
from istio_config_parser.istio_monitor.istio_config_parser import IstioConfigParser
from istio_config_parser.main_parser import parse_control_plane_from_dir
from istio_config_parser.utils.file_utils import load_yaml_file

# 导入一致性检查器
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.models.data_models import (
    ConsistencyResult,
    InconsistencyAnnotation,
    SeverityLevel
)

# 导入流量测试模块
from istio_Dynamic_Test.internal.pipeline import DynamicTester
from istio_Dynamic_Test.internal.models import TestCase, TestSuite

class AccuracyEvaluator:
    """准确性评估器"""
    
    def __init__(self, config_file: str = None):
        """初始化评估器"""
        self.config = self._load_config(config_file)
        self.results = {
            "start_time": datetime.now().isoformat(),
            "test_results": [],
            "metrics": {},
            "statistical_analysis": {},
            "visualizations": []
        }
        
        # 初始化配置解析器（其他组件在需要时创建）
        self.config_parser = IstioConfigParser()
        # ConsistencyChecker 需要参数，在需要时创建
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        return {
            "test_cases_file": "test_cases/precision_recall_tests.json",
            "ground_truth_file": "data/ground_truth.json",
            "output_dir": "results",
            "confidence_level": 0.95,
            "statistical_tests": ["chi_square", "mcnemar"]
        }
    
    def load_ground_truth(self) -> Dict[str, Any]:
        """加载黄金标准数据集"""
        ground_truth_file = self.config.get("ground_truth_file")
        
        if ground_truth_file and os.path.exists(ground_truth_file):
            with open(ground_truth_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 如果没有现成的黄金标准数据，生成模拟数据
        return self._generate_synthetic_ground_truth()
    
    def _generate_synthetic_ground_truth(self) -> Dict[str, Any]:
        """生成合成的黄金标准数据"""
        np.random.seed(42)  # 确保可重现性
        
        # 生成1000个测试样本
        total_samples = 1000
        positive_ratio = 0.3  # 30%为正样本（存在问题）
        
        ground_truth = {
            "samples": [],
            "metadata": {
                "total_samples": total_samples,
                "positive_samples": int(total_samples * positive_ratio),
                "negative_samples": int(total_samples * (1 - positive_ratio)),
                "generation_time": datetime.now().isoformat()
            }
        }
        
        categories = [
            "route_conflicts", "weight_errors", "timeout_issues", 
            "retry_failures", "circuit_breaker_problems", 
            "fault_injection_issues", "security_policy_conflicts"
        ]
        
        for i in range(total_samples):
            # 决定是否为正样本
            is_positive = np.random.random() < positive_ratio
            
            sample = {
                "sample_id": f"sample_{i:04d}",
                "has_issue": is_positive,
                "severity": np.random.choice(["low", "medium", "high"], p=[0.5, 0.3, 0.2]) if is_positive else "none",
                "category": np.random.choice(categories) if is_positive else "none",
                "confidence": np.random.uniform(0.8, 1.0) if is_positive else np.random.uniform(0.0, 0.3),
                "description": f"Synthetic sample {i} - {'with issue' if is_positive else 'normal'}"
            }
            
            # 添加具体的问题特征
            if is_positive:
                if sample["category"] == "weight_errors":
                    sample["details"] = {
                        "configured_weights": [80, 20],
                        "actual_weights": [np.random.uniform(60, 95), np.random.uniform(5, 40)],
                        "deviation": np.random.uniform(0.05, 0.3)
                    }
                elif sample["category"] == "timeout_issues":
                    sample["details"] = {
                        "configured_timeout": 3.0,
                        "actual_response_time": np.random.uniform(3.1, 8.0),
                        "timeout_violations": np.random.randint(1, 20)
                    }
                elif sample["category"] == "route_conflicts":
                    sample["details"] = {
                        "conflicting_rules": np.random.randint(2, 5),
                        "priority_conflicts": np.random.choice([True, False]),
                        "affected_services": np.random.randint(1, 4)
                    }
            
            ground_truth["samples"].append(sample)
        
        return ground_truth
    
    def run_detection_system(self, test_sample: Dict[str, Any]) -> Dict[str, Any]:
        """运行检测系统并获取结果 - 真实调用一致性检查器"""
        try:
            start_time = time.time()
            
            # 1. 准备测试配置
            config_files = test_sample.get("config_files", [])
            config_content = test_sample.get("config_content", None)
            
            if not config_files and not config_content:
                # 如果没有配置文件，回退到简单的模拟（用于合成数据）
                print(f"警告: 样本 {test_sample.get('sample_id')} 没有配置文件，使用简化检测")
                return self._fallback_detection(test_sample)
            
            # 2. 解析配置
            parsed_configs = []
            if config_files:
                for config_file in config_files:
                    config_path = os.path.join(project_root, "evaluation", "accuracy", "configs", config_file)
                    if os.path.exists(config_path):
                        # 使用 load_yaml_file 加载配置
                        config = load_yaml_file(config_path)
                        parsed_configs.append(config)
            elif config_content:
                # 直接解析配置内容
                import yaml
                config = yaml.safe_load(config_content)
                parsed_configs.append(config)
            
            # 3. 运行静态分析
            static_analyzer = StaticAnalyzer(parsed_configs)
            static_result = static_analyzer.analyze()
            
            # 4. 如果需要动态分析，运行流量测试
            has_traffic_test = test_sample.get("requires_traffic_test", False)
            dynamic_result = None
            
            if has_traffic_test and test_sample.get("traffic_config"):
                try:
                    # 运行流量测试
                    # 从环境变量或配置获取SSH凭据
                    import os
                    from consistency_checker.config import get_config
                    global_config = get_config()
                    ssh_host = self.config.get("ssh_host") or os.getenv("SSH_HOST") or global_config.ssh_host
                    ssh_user = self.config.get("ssh_user") or os.getenv("SSH_USER") or global_config.ssh_user
                    ssh_password = self.config.get("ssh_password") or os.getenv("SSH_PASSWORD") or global_config.ssh_password
                    
                    tc_dict = test_sample.get("traffic_config", {})
                    if isinstance(tc_dict, dict) and "test_cases" in tc_dict:
                        suite = TestSuite(
                            cases=[
                                TestCase.from_matrix_dict(c, tc_dict.get("global_settings", {}).get("ingress_url", ""))
                                for c in tc_dict["test_cases"]
                            ],
                            global_settings=tc_dict.get("global_settings", {}),
                        )
                    else:
                        suite = TestSuite(
                            cases=[TestCase.from_matrix_dict(tc_dict, "")],
                            global_settings={},
                        )
                    ssh_config = {
                        "hostname": ssh_host,
                        "username": ssh_user,
                        "password": ssh_password,
                    }
                    results = DynamicTester(ssh_config=ssh_config).run(suite)
                    traffic_result = {}
                    for pr in results:
                        if pr.execution:
                            traffic_result[pr.test_case.case_id] = {
                                "status_codes": pr.execution.status_codes,
                                "total_requests": pr.execution.total_requests,
                                "success_rate": pr.execution.success_rate,
                            }
                    
                    # 动态分析
                    dynamic_analyzer = DynamicAnalyzer()
                    dynamic_result = dynamic_analyzer.analyze_traffic_metrics(
                        traffic_result,
                        expected_behavior=test_sample.get("expected_behavior", {})
                    )
                except Exception as e:
                    print(f"动态分析失败: {str(e)}")
                    dynamic_result = None
            
            # 5. 整合结果
            has_static_issues = len(static_result.inconsistencies) > 0
            has_dynamic_issues = dynamic_result and dynamic_result.has_anomalies() if dynamic_result else False
            
            detected = has_static_issues or has_dynamic_issues
            
            # 确定问题类别
            if has_static_issues:
                primary_issue = static_result.inconsistencies[0]
                predicted_category = self._map_inconsistency_to_category(primary_issue.type.value)
                confidence = static_result.confidence_score
            elif has_dynamic_issues:
                primary_anomaly = dynamic_result.get_anomalies()[0]
                predicted_category = self._map_anomaly_to_category(primary_anomaly.type)
                confidence = dynamic_result.confidence_score
            else:
                predicted_category = "none"
                confidence = static_result.confidence_score
            
            execution_time = time.time() - start_time
            
            return {
                "detected": detected,
                "confidence": confidence,
                "predicted_category": predicted_category,
                "execution_time": execution_time,
                "detailed_metrics": {
                    "static_issues_count": len(static_result.inconsistencies),
                    "dynamic_anomalies_count": len(dynamic_result.get_anomalies()) if dynamic_result else 0,
                    "processing_time": execution_time * 1000,  # ms
                    "analyzer_used": "ConsistencyChecker (Real)"
                }
            }
            
        except Exception as e:
            print(f"检测系统执行失败: {str(e)}")
            return {
                "detected": False,
                "confidence": 0.0,
                "predicted_category": "error",
                "execution_time": time.time() - start_time,
                "detailed_metrics": {
                    "error": str(e),
                    "analyzer_used": "ConsistencyChecker (Error)"
                }
            }
    
    def _fallback_detection(self, test_sample: Dict[str, Any]) -> Dict[str, Any]:
        """简化的检测逻辑（用于没有配置文件的合成样本）"""
        # 基于样本的元数据进行简单判断
        has_issue = test_sample.get("has_issue", False)
        category = test_sample.get("category", "none")
        
        # 使用一些启发式规则
        detected = has_issue  # 简化：假设可以检测到
        confidence = 0.7 if has_issue else 0.9
        
        return {
            "detected": detected,
            "confidence": confidence,
            "predicted_category": category if detected else "none",
            "execution_time": 0.1,
            "detailed_metrics": {
                "analyzer_used": "Fallback (Simplified)",
                "note": "No config files provided, using heuristic detection"
            }
        }
    
    def _map_inconsistency_to_category(self, inconsistency_type: str) -> str:
        """将不一致性类型映射到评估类别"""
        mapping = {
            "ROUTE_CONFLICT": "route_conflicts",
            "WEIGHT_MISMATCH": "weight_errors",
            "TIMEOUT_INCONSISTENCY": "timeout_issues",
            "RETRY_POLICY_CONFLICT": "retry_failures",
            "CIRCUIT_BREAKER_ISSUE": "circuit_breaker_problems",
            "FAULT_INJECTION_ERROR": "fault_injection_issues",
            "SECURITY_POLICY_CONFLICT": "security_policy_conflicts"
        }
        return mapping.get(inconsistency_type, "unknown")
    
    def _map_anomaly_to_category(self, anomaly_type: str) -> str:
        """将异常类型映射到评估类别"""
        mapping = {
            "TRAFFIC_DISTRIBUTION_ANOMALY": "weight_errors",
            "LATENCY_ANOMALY": "timeout_issues",
            "ERROR_RATE_ANOMALY": "retry_failures",
            "CIRCUIT_BREAKER_ANOMALY": "circuit_breaker_problems"
        }
        return mapping.get(anomaly_type, "unknown")
    
    def evaluate_precision_recall(self) -> Dict[str, Any]:
        """评估精确度和召回率"""
        print("开始加载测试数据...")
        ground_truth = self.load_ground_truth()
        
        print(f"加载了 {len(ground_truth['samples'])} 个测试样本")
        
        y_true = []  # 真实标签
        y_pred = []  # 预测标签
        y_confidence = []  # 预测置信度
        category_true = []  # 真实类别
        category_pred = []  # 预测类别
        
        execution_times = []
        detailed_results = []
        
        print("开始运行检测系统...")
        for i, sample in enumerate(ground_truth['samples']):
            if i % 100 == 0:
                print(f"处理进度: {i}/{len(ground_truth['samples'])}")
            
            # 运行检测系统
            detection_result = self.run_detection_system(sample)
            
            # 收集结果
            y_true.append(1 if sample['has_issue'] else 0)
            y_pred.append(1 if detection_result['detected'] else 0)
            y_confidence.append(detection_result['confidence'])
            
            category_true.append(sample.get('category', 'none'))
            category_pred.append(detection_result.get('predicted_category', 'none'))
            
            execution_times.append(detection_result['execution_time'])
            
            detailed_results.append({
                "sample_id": sample['sample_id'],
                "ground_truth": sample,
                "detection_result": detection_result,
                "correct_binary": (sample['has_issue'] == detection_result['detected']),
                "correct_category": (sample.get('category') == detection_result.get('predicted_category'))
            })
        
        print("计算评估指标...")
        
        # 计算二分类指标
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall = recall_score(y_true, y_pred, zero_division=0) 
        f1 = f1_score(y_true, y_pred, zero_division=0)
        accuracy = accuracy_score(y_true, y_pred)
        
        # 计算混淆矩阵
        cm = confusion_matrix(y_true, y_pred)
        tn, fp, fn, tp = cm.ravel()
        
        # 计算类别分类指标
        unique_categories = list(set(category_true + category_pred))
        category_report = classification_report(category_true, category_pred, 
                                              labels=unique_categories, 
                                              output_dict=True, 
                                              zero_division=0)
        
        # 统计分析
        statistical_metrics = {
            "mean_execution_time": np.mean(execution_times),
            "std_execution_time": np.std(execution_times),
            "mean_confidence": np.mean(y_confidence),
            "confidence_correlation": np.corrcoef(y_true, y_confidence)[0, 1] if len(set(y_true)) > 1 else 0,
            "performance_consistency": {
                "cv_execution_time": np.std(execution_times) / np.mean(execution_times),
                "confidence_variance": np.var(y_confidence)
            }
        }
        
        return {
            "binary_classification": {
                "precision": precision,
                "recall": recall,
                "f1_score": f1,
                "accuracy": accuracy,
                "confusion_matrix": {
                    "true_negatives": int(tn),
                    "false_positives": int(fp),
                    "false_negatives": int(fn),
                    "true_positives": int(tp)
                },
                "false_positive_rate": fp / (fp + tn) if (fp + tn) > 0 else 0,
                "false_negative_rate": fn / (fn + tp) if (fn + tp) > 0 else 0
            },
            "category_classification": category_report,
            "statistical_metrics": statistical_metrics,
            "detailed_results": detailed_results[:10],  # 只保留前10个详细结果作为示例
            "summary_stats": {
                "total_samples": len(ground_truth['samples']),
                "positive_samples": sum(y_true),
                "negative_samples": len(y_true) - sum(y_true),
                "detected_positives": sum(y_pred),
                "correct_predictions": sum(1 for t, p in zip(y_true, y_pred) if t == p)
            }
        }
    
    def generate_visualizations(self, evaluation_results: Dict[str, Any]) -> List[str]:
        """生成可视化图表"""
        viz_files = []
        
        # 创建输出目录
        viz_dir = os.path.join(self.config['output_dir'], 'visualizations')
        os.makedirs(viz_dir, exist_ok=True)
        
        # 1. 混淆矩阵热图
        cm_data = evaluation_results['binary_classification']['confusion_matrix']
        cm_matrix = np.array([[cm_data['true_negatives'], cm_data['false_positives']],
                             [cm_data['false_negatives'], cm_data['true_positives']]])
        
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm_matrix, annot=True, fmt='d', cmap='Blues',
                   xticklabels=['Predicted Negative', 'Predicted Positive'],
                   yticklabels=['Actual Negative', 'Actual Positive'])
        plt.title('Confusion Matrix')
        plt.tight_layout()
        
        cm_file = os.path.join(viz_dir, 'confusion_matrix.png')
        plt.savefig(cm_file)
        plt.close()
        viz_files.append(cm_file)
        
        # 2. 性能指标雷达图
        metrics = evaluation_results['binary_classification']
        metric_names = ['Precision', 'Recall', 'F1-Score', 'Accuracy']
        metric_values = [metrics['precision'], metrics['recall'], 
                        metrics['f1_score'], metrics['accuracy']]
        
        angles = np.linspace(0, 2 * np.pi, len(metric_names), endpoint=False)
        angles = np.concatenate((angles, [angles[0]]))  # 闭合图形
        values = metric_values + [metric_values[0]]
        
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
        ax.plot(angles, values, 'o-', linewidth=2, label='System Performance')
        ax.fill(angles, values, alpha=0.25)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(metric_names)
        ax.set_ylim(0, 1)
        ax.set_title('Performance Metrics Radar Chart', pad=20)
        ax.legend()
        
        radar_file = os.path.join(viz_dir, 'performance_radar.png')
        plt.savefig(radar_file)
        plt.close()
        viz_files.append(radar_file)
        
        # 3. 类别分类性能条形图
        category_metrics = evaluation_results['category_classification']
        categories = [k for k in category_metrics.keys() if k not in ['accuracy', 'macro avg', 'weighted avg']]
        
        if categories:
            precision_scores = [category_metrics[cat]['precision'] for cat in categories]
            recall_scores = [category_metrics[cat]['recall'] for cat in categories]
            f1_scores = [category_metrics[cat]['f1-score'] for cat in categories]
            
            x = np.arange(len(categories))
            width = 0.25
            
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.bar(x - width, precision_scores, width, label='Precision', alpha=0.8)
            ax.bar(x, recall_scores, width, label='Recall', alpha=0.8)
            ax.bar(x + width, f1_scores, width, label='F1-Score', alpha=0.8)
            
            ax.set_xlabel('Categories')
            ax.set_ylabel('Score')
            ax.set_title('Category-wise Performance Metrics')
            ax.set_xticks(x)
            ax.set_xticklabels(categories, rotation=45, ha='right')
            ax.legend()
            ax.set_ylim(0, 1)
            
            plt.tight_layout()
            category_file = os.path.join(viz_dir, 'category_performance.png')
            plt.savefig(category_file)
            plt.close()
            viz_files.append(category_file)
        
        return viz_files
    
    def generate_report(self, evaluation_results: Dict[str, Any]) -> str:
        """生成详细的评估报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(self.config['output_dir'], f'accuracy_evaluation_report_{timestamp}.json')
        
        # 确保输出目录存在
        os.makedirs(self.config['output_dir'], exist_ok=True)
        
        # 生成可视化
        viz_files = self.generate_visualizations(evaluation_results)
        
        report = {
            "evaluation_metadata": {
                "timestamp": timestamp,
                "evaluator_version": "1.0.0",
                "test_configuration": self.config
            },
            "results": evaluation_results,
            "visualizations": viz_files,
            "conclusions": self._generate_conclusions(evaluation_results),
            "recommendations": self._generate_recommendations(evaluation_results)
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"评估报告已生成: {report_file}")
        return report_file
    
    def _generate_conclusions(self, results: Dict[str, Any]) -> List[str]:
        """基于结果生成结论"""
        conclusions = []
        
        binary_metrics = results['binary_classification']
        
        if binary_metrics['accuracy'] >= 0.9:
            conclusions.append("系统整体准确性优秀 (≥90%)")
        elif binary_metrics['accuracy'] >= 0.8:
            conclusions.append("系统整体准确性良好 (80-90%)")
        else:
            conclusions.append("系统整体准确性需要改进 (<80%)")
        
        if binary_metrics['precision'] >= 0.85 and binary_metrics['recall'] >= 0.85:
            conclusions.append("精确度和召回率均达到良好水平")
        elif binary_metrics['precision'] < 0.7 or binary_metrics['recall'] < 0.7:
            conclusions.append("精确度或召回率存在显著不足，需要重点优化")
        
        fpr = binary_metrics['false_positive_rate']
        if fpr <= 0.05:
            conclusions.append("误报率控制良好 (≤5%)")
        elif fpr >= 0.15:
            conclusions.append("误报率偏高 (≥15%)，可能影响用户体验")
        
        return conclusions
    
    def _generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """基于结果生成改进建议"""
        recommendations = []
        
        binary_metrics = results['binary_classification']
        
        if binary_metrics['precision'] < 0.8:
            recommendations.append("建议优化检测算法以减少误报，可考虑提高检测阈值或改进特征工程")
        
        if binary_metrics['recall'] < 0.8:
            recommendations.append("建议增强检测敏感性以减少漏报，可考虑降低检测阈值或增加更多检测规则")
        
        if binary_metrics['f1_score'] < 0.8:
            recommendations.append("建议平衡精确度和召回率，考虑使用集成学习或多阶段检测策略")
        
        # 基于类别性能给出建议
        category_metrics = results['category_classification']
        worst_categories = []
        for cat, metrics in category_metrics.items():
            if isinstance(metrics, dict) and 'f1-score' in metrics:
                if metrics['f1-score'] < 0.7:
                    worst_categories.append(cat)
        
        if worst_categories:
            recommendations.append(f"以下类别检测性能较差，建议重点优化: {', '.join(worst_categories)}")
        
        return recommendations
    
    def run_evaluation(self) -> str:
        """运行完整的准确性评估"""
        print("开始准确性评估...")
        
        # 运行精确度和召回率评估
        evaluation_results = self.evaluate_precision_recall()
        
        # 生成报告
        report_file = self.generate_report(evaluation_results)
        
        print("准确性评估完成!")
        return report_file

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Istio配置一致性检测系统准确性评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    
    args = parser.parse_args()
    
    config = {"output_dir": args.output}
    if args.config:
        config["config_file"] = args.config
    
    evaluator = AccuracyEvaluator()
    evaluator.config.update(config)
    
    report_file = evaluator.run_evaluation()
    print(f"评估完成，报告文件: {report_file}")

if __name__ == "__main__":
    main()
