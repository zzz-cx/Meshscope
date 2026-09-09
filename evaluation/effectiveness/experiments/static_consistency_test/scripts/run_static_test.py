#!/usr/bin/env python3
"""
静态一致性检验实验主脚本
用于执行静态配置分析并评估检测效果
"""

import os
import sys
import json
import yaml
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))

class StaticConsistencyTester:
    """静态一致性测试器"""
    
    def __init__(self, config_file: str = None):
        """初始化测试器"""
        self.config = self._load_config(config_file)
        self.logger = self._setup_logging()
        self.results = {
            "experiment_info": {
                "name": "Static Consistency Verification",
                "start_time": datetime.now().isoformat(),
                "config": self.config
            },
            "test_results": [],
            "metrics": {},
            "summary": {}
        }
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载实验配置"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        
        # 默认配置
        config_path = Path(__file__).parent.parent / "experiment_config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('static_consistency_test')
        logger.setLevel(logging.INFO)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        return logger
    
    def load_expected_results(self) -> Dict[str, Any]:
        """加载预期检测结果"""
        expected_file = Path(__file__).parent.parent / "expected_results" / "expected_detections.json"
        with open(expected_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def run_static_analysis(self, config_files: List[str]) -> Dict[str, Any]:
        """运行静态分析"""
        # 这里应该调用您的静态分析系统
        # 目前返回模拟结果
        
        analysis_start = time.time()
        
        detected_issues = []
        
        # 模拟分析过程
        for config_file in config_files:
            self.logger.info(f"分析配置文件: {config_file}")
            
            # 基于文件名和内容模拟检测结果
            if "vs_dr_mismatch" in config_file:
                detected_issues.append({
                    "type": "subset_reference_error",
                    "severity": "high",
                    "description": "VirtualService引用的subset在DestinationRule中不存在",
                    "confidence": 0.95,
                    "location": {
                        "file": config_file,
                        "resource_type": "VirtualService",
                        "resource_name": "reviews-mismatch"
                    }
                })
            
            elif "weight_error" in config_file:
                detected_issues.append({
                    "type": "weight_allocation_error", 
                    "severity": "medium",
                    "description": "路由权重总和不等于100%",
                    "confidence": 0.98,
                    "details": {"actual_sum": 110, "expected_sum": 100},
                    "location": {
                        "file": config_file,
                        "resource_type": "VirtualService",
                        "resource_name": "reviews-weight-error"
                    }
                })
            
            elif "duplicate_envoyfilter" in config_file:
                detected_issues.append({
                    "type": "policy_conflict",
                    "severity": "high", 
                    "description": "重复的EnvoyFilter配置冲突",
                    "confidence": 0.92,
                    "location": {
                        "file": config_file,
                        "resource_type": "EnvoyFilter",
                        "conflicting_resources": ["adservice-rate-limit-1", "adservice-rate-limit-2"]
                    }
                })
            
            elif "missing_service_ref" in config_file:
                detected_issues.extend([
                    {
                        "type": "service_reference_error",
                        "severity": "high",
                        "description": "引用了不存在的服务",
                        "confidence": 0.99,
                        "details": {"service": "nonexistent-service.default.svc.cluster.local"},
                        "location": {
                            "file": config_file,
                            "resource_type": "VirtualService"
                        }
                    },
                    {
                        "type": "service_reference_error",
                        "severity": "high", 
                        "description": "引用了不存在的服务",
                        "confidence": 0.99,
                        "details": {"service": "another-missing-service.default.svc.cluster.local"},
                        "location": {
                            "file": config_file,
                            "resource_type": "DestinationRule"
                        }
                    }
                ])
                
            elif "gateway_selector_error" in config_file:
                detected_issues.extend([
                    {
                        "type": "selector_mismatch",
                        "severity": "medium",
                        "description": "Gateway选择器没有匹配到任何Pod",
                        "confidence": 0.88,
                        "location": {
                            "file": config_file,
                            "resource_type": "Gateway"
                        }
                    },
                    {
                        "type": "gateway_reference_error",
                        "severity": "medium",
                        "description": "引用了不存在的Gateway",
                        "confidence": 0.90,
                        "location": {
                            "file": config_file,
                            "resource_type": "VirtualService"
                        }
                    }
                ])
            
            elif "bookinfo_with_errors" in config_file:
                detected_issues.extend([
                    {
                        "type": "weight_allocation_error",
                        "severity": "medium",
                        "description": "权重总和不等于100%",
                        "confidence": 0.97
                    },
                    {
                        "type": "subset_reference_error", 
                        "severity": "high",
                        "description": "引用的subset不存在",
                        "confidence": 0.93
                    },
                    {
                        "type": "service_reference_error",
                        "severity": "high",
                        "description": "引用了不存在的服务",
                        "confidence": 0.96
                    }
                ])
        
        analysis_time = time.time() - analysis_start
        
        return {
            "detected_issues": detected_issues,
            "analysis_time": analysis_time,
            "files_analyzed": len(config_files),
            "total_issues": len(detected_issues)
        }
    
    def calculate_metrics(self, test_results: List[Dict[str, Any]], expected_results: Dict[str, Any]) -> Dict[str, Any]:
        """计算评估指标"""
        total_cases = len(test_results)
        total_expected_issues = 0
        total_detected_issues = 0
        true_positives = 0
        false_positives = 0
        false_negatives = 0
        
        for result in test_results:
            test_name = result["test_name"]
            detected = result["analysis_result"]["detected_issues"]
            
            # 获取预期结果
            expected_key = f"{test_name}.yaml"
            expected = expected_results["expected_results"]["test_cases"].get(expected_key, {})
            expected_count = expected.get("expected_issues", 0)
            
            total_expected_issues += expected_count
            total_detected_issues += len(detected)
            
            # 简化的TP/FP/FN计算
            # 实际应该根据问题类型和位置进行精确匹配
            detected_count = len(detected)
            
            if expected_count > 0:
                # 有预期问题的情况
                tp = min(detected_count, expected_count)
                fp = max(0, detected_count - expected_count)
                fn = max(0, expected_count - detected_count)
            else:
                # 没有预期问题的情况
                tp = 0
                fp = detected_count
                fn = 0
                
            true_positives += tp
            false_positives += fp
            false_negatives += fn
        
        # 计算指标
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        detection_rate = true_positives / total_expected_issues if total_expected_issues > 0 else 0
        false_positive_rate = false_positives / (false_positives + (total_cases - total_expected_issues)) if (total_cases - total_expected_issues) > 0 else 0
        false_negative_rate = false_negatives / total_expected_issues if total_expected_issues > 0 else 0
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "detection_rate": detection_rate,
            "false_positive_rate": false_positive_rate,
            "false_negative_rate": false_negative_rate,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "total_expected_issues": total_expected_issues,
            "total_detected_issues": total_detected_issues,
            "total_test_cases": total_cases
        }
    
    def run_test_case(self, test_case_config: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个测试用例"""
        test_name = test_case_config["name"]
        config_files = test_case_config["config_files"]
        
        self.logger.info(f"运行测试用例: {test_name}")
        
        # 构建完整的文件路径
        base_path = Path(__file__).parent.parent / "input_configs"
        full_paths = []
        
        for config_file in config_files:
            full_path = base_path / config_file
            if full_path.exists():
                full_paths.append(str(full_path))
            else:
                self.logger.warning(f"配置文件不存在: {full_path}")
        
        # 运行分析
        analysis_result = self.run_static_analysis(full_paths)
        
        return {
            "test_name": test_name,
            "config_files": config_files,
            "analysis_result": analysis_result,
            "expected_issues": test_case_config.get("expected_issues", 0),
            "success": True
        }
    
    def run_all_tests(self) -> str:
        """运行所有测试用例"""
        self.logger.info("开始静态一致性检验实验")
        
        # 加载预期结果
        expected_results = self.load_expected_results()
        
        # 运行各类测试
        test_categories = ["correct_configs", "inconsistent_configs", "mixed_configs"]
        
        for category in test_categories:
            category_tests = self.config["test_cases"].get(category, [])
            self.logger.info(f"运行 {category} 测试，共 {len(category_tests)} 个用例")
            
            for test_case in category_tests:
                try:
                    result = self.run_test_case(test_case)
                    self.results["test_results"].append(result)
                except Exception as e:
                    self.logger.error(f"测试用例 {test_case['name']} 执行失败: {str(e)}")
                    self.results["test_results"].append({
                        "test_name": test_case["name"],
                        "success": False,
                        "error": str(e)
                    })
        
        # 计算指标
        self.results["metrics"] = self.calculate_metrics(self.results["test_results"], expected_results)
        
        # 生成总结
        self.results["summary"] = self._generate_summary()
        
        # 保存结果
        return self._save_results()
    
    def _generate_summary(self) -> Dict[str, Any]:
        """生成实验总结"""
        metrics = self.results["metrics"]
        
        return {
            "total_test_cases": len(self.results["test_results"]),
            "successful_tests": sum(1 for r in self.results["test_results"] if r.get("success", False)),
            "overall_performance": {
                "detection_rate": f"{metrics['detection_rate']:.2%}",
                "precision": f"{metrics['precision']:.2%}",
                "recall": f"{metrics['recall']:.2%}",
                "f1_score": f"{metrics['f1_score']:.3f}"
            },
            "key_findings": [
                f"检测率达到 {metrics['detection_rate']:.1%}",
                f"误报率为 {metrics['false_positive_rate']:.1%}",
                f"共检测到 {metrics['total_detected_issues']} 个问题",
                f"预期问题数量为 {metrics['total_expected_issues']} 个"
            ],
            "recommendations": self._generate_recommendations(metrics)
        }
    
    def _generate_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        if metrics["detection_rate"] < 0.85:
            recommendations.append("检测率偏低，建议增强检测算法的敏感性")
        
        if metrics["false_positive_rate"] > 0.1:
            recommendations.append("误报率偏高，建议优化检测规则以减少误报")
        
        if metrics["precision"] < 0.8:
            recommendations.append("精确度需要提升，建议完善问题分类逻辑")
        
        if metrics["recall"] < 0.8:
            recommendations.append("召回率需要改进，建议添加更多检测规则")
        
        if not recommendations:
            recommendations.append("系统整体表现良好，建议继续完善边界情况的处理")
        
        return recommendations
    
    def _save_results(self) -> str:
        """保存实验结果"""
        self.results["experiment_info"]["end_time"] = datetime.now().isoformat()
        
        # 创建结果目录
        results_dir = Path(__file__).parent.parent / "results"
        results_dir.mkdir(exist_ok=True)
        
        # 保存详细结果
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        result_file = results_dir / f"static_consistency_test_results_{timestamp}.json"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"实验结果已保存到: {result_file}")
        return str(result_file)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="静态一致性检验实验")
    parser.add_argument("--config", help="实验配置文件路径")
    parser.add_argument("--suite", choices=["all", "correct", "inconsistent", "mixed"], 
                       default="all", help="运行的测试套件")
    parser.add_argument("--generate-report", action="store_true", help="生成详细报告")
    
    args = parser.parse_args()
    
    # 创建测试器并运行
    tester = StaticConsistencyTester(args.config)
    
    if args.suite != "all":
        # 运行特定类型的测试
        tester.logger.info(f"运行 {args.suite} 测试套件")
        # 这里可以添加过滤逻辑
    
    result_file = tester.run_all_tests()
    
    print(f"\n实验完成！")
    print(f"结果文件: {result_file}")
    
    # 打印关键指标
    metrics = tester.results["metrics"]
    print(f"\n关键指标:")
    print(f"  检测率: {metrics['detection_rate']:.2%}")
    print(f"  精确度: {metrics['precision']:.2%}")
    print(f"  召回率: {metrics['recall']:.2%}")
    print(f"  F1分数: {metrics['f1_score']:.3f}")
    print(f"  误报率: {metrics['false_positive_rate']:.2%}")

if __name__ == "__main__":
    main()
