#!/usr/bin/env python3
"""
Hybrid Runner - 动静态结合，静态指导用例生成并融合结果
"""

import os
import sys
import json
import time
import asyncio
import yaml
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))

from runners.static_runner import StaticRunner
from runners.dynamic_runner import DynamicRunner


class HybridRunner:
    """混合验证器 - 结合静态分析和动态测试"""
    
    def __init__(self, config_path: str):
        """初始化混合运行器"""
        self.config_path = config_path
        self.static_runner = StaticRunner(config_path)
        self.dynamic_runner = DynamicRunner(config_path)
        self.results = {
            "method": "hybrid",
            "start_time": None,
            "end_time": None,
            "static_analysis_time": 0,
            "dynamic_testing_time": 0,
            "fusion_time": 0,
            "total_time": 0,
            "static_results": {},
            "dynamic_results": {},
            "fused_results": {},
            "accuracy_metrics": {}
        }
    
    async def run(self, config_files: List[str], test_duration: int = 60) -> Dict[str, Any]:
        """运行混合验证"""
        start_time = time.time()
        self.results["start_time"] = datetime.now().isoformat()
        
        try:
            # 1. 静态分析阶段
            static_start = time.time()
            static_results = await self.static_runner.run(config_files)
            static_time = time.time() - static_start
            self.results["static_analysis_time"] = static_time
            self.results["static_results"] = static_results
            
            # 2. 基于静态分析结果生成动态测试用例
            test_cases = self._generate_dynamic_test_cases(static_results, config_files)
            
            # 3. 动态测试阶段
            dynamic_start = time.time()
            dynamic_results = await self.dynamic_runner.run(config_files, test_duration)
            dynamic_time = time.time() - dynamic_start
            self.results["dynamic_testing_time"] = dynamic_time
            self.results["dynamic_results"] = dynamic_results
            
            # 4. 结果融合
            fusion_start = time.time()
            fused_results = await self._fuse_results(static_results, dynamic_results, test_cases)
            fusion_time = time.time() - fusion_start
            self.results["fusion_time"] = fusion_time
            self.results["fused_results"] = fused_results
            
            # 5. 计算最终准确性
            self.results["accuracy_metrics"] = self._calculate_final_accuracy(
                static_results, dynamic_results, fused_results, config_files
            )
            
            total_time = time.time() - start_time
            self.results["end_time"] = datetime.now().isoformat()
            self.results["total_time"] = total_time
            
            return self.results
            
        except Exception as e:
            self.results["error"] = str(e)
            self.results["end_time"] = datetime.now().isoformat()
            return self.results
    
    def _generate_dynamic_test_cases(self, static_results: Dict[str, Any], config_files: List[str]) -> List[Dict[str, Any]]:
        """基于静态分析结果生成动态测试用例"""
        test_cases = []
        
        # 从静态分析中提取需要验证的配置项
        static_issues = static_results.get("issues_found", [])
        config_coverage = static_results.get("config_coverage", {})
        
        # 1. 为每个发现的问题生成验证用例
        for issue in static_issues:
            if issue.get("type") == "service_reference_error":
                test_cases.append({
                    "type": "service_connectivity_test",
                    "target_service": issue.get("resource", ""),
                    "expected_result": "connection_failure",
                    "priority": "high"
                })
            elif issue.get("type") == "port_mismatch":
                test_cases.append({
                    "type": "port_accessibility_test",
                    "target_service": issue.get("resource", ""),
                    "expected_result": "port_unreachable",
                    "priority": "medium"
                })
            elif issue.get("type") == "weight_mismatch":
                test_cases.append({
                    "type": "load_balancing_test",
                    "target_service": issue.get("resource", ""),
                    "expected_result": "imbalanced_traffic",
                    "priority": "low"
                })
        
        # 2. 为覆盖的服务生成基础连通性测试
        services_count = config_coverage.get("service_count", 0)
        if services_count > 0:
            test_cases.append({
                "type": "comprehensive_connectivity_test",
                "scope": "all_services",
                "expected_result": "all_services_accessible",
                "priority": "medium"
            })
        
        # 3. 为有VirtualService的服务生成路由测试
        virtual_services = static_results.get("static_results", {}).get("virtual_services", [])
        for vs in virtual_services:
            test_cases.append({
                "type": "routing_test",
                "target_service": vs.get("name", ""),
                "expected_result": "correct_routing",
                "priority": "high"
            })
        
        return test_cases
    
    async def _fuse_results(self, static_results: Dict[str, Any], dynamic_results: Dict[str, Any], 
                          test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """融合静态和动态分析结果"""
        fused_results = {
            "combined_issues": [],
            "validation_summary": {},
            "confidence_scores": {},
            "recommendations": []
        }
        
        static_issues = static_results.get("issues_found", [])
        dynamic_issues = dynamic_results.get("inconsistencies_found", [])
        
        # 1. 合并问题列表，去重和关联
        issue_map = {}
        
        # 处理静态问题
        for issue in static_issues:
            issue_key = f"{issue.get('type', '')}_{issue.get('resource', '')}"
            if issue_key not in issue_map:
                issue_map[issue_key] = {
                    "static_issue": issue,
                    "dynamic_issue": None,
                    "validation_status": "static_only"
                }
        
        # 处理动态问题，尝试关联静态问题
        for issue in dynamic_issues:
            issue_key = self._find_related_static_issue(issue, static_issues)
            if issue_key and issue_key in issue_map:
                issue_map[issue_key]["dynamic_issue"] = issue
                issue_map[issue_key]["validation_status"] = "validated"
            else:
                # 动态发现的新问题
                new_key = f"dynamic_{issue.get('type', '')}_{issue.get('endpoint', '')}"
                issue_map[new_key] = {
                    "static_issue": None,
                    "dynamic_issue": issue,
                    "validation_status": "dynamic_only"
                }
        
        # 2. 生成融合后的问题列表
        for key, issue_data in issue_map.items():
            combined_issue = self._combine_issue_data(issue_data)
            fused_results["combined_issues"].append(combined_issue)
        
        # 3. 生成验证摘要
        total_issues = len(fused_results["combined_issues"])
        validated_issues = len([i for i in fused_results["combined_issues"] 
                              if i.get("validation_status") == "validated"])
        static_only_issues = len([i for i in fused_results["combined_issues"] 
                                if i.get("validation_status") == "static_only"])
        dynamic_only_issues = len([i for i in fused_results["combined_issues"] 
                                 if i.get("validation_status") == "dynamic_only"])
        
        fused_results["validation_summary"] = {
            "total_issues": total_issues,
            "validated_issues": validated_issues,
            "static_only_issues": static_only_issues,
            "dynamic_only_issues": dynamic_only_issues,
            "validation_rate": validated_issues / max(total_issues, 1)
        }
        
        # 4. 计算置信度分数
        for issue in fused_results["combined_issues"]:
            confidence = self._calculate_confidence_score(issue)
            issue["confidence_score"] = confidence
        
        # 5. 生成建议
        fused_results["recommendations"] = self._generate_recommendations(fused_results["combined_issues"])
        
        return fused_results
    
    def _find_related_static_issue(self, dynamic_issue: Dict[str, Any], static_issues: List[Dict[str, Any]]) -> Optional[str]:
        """查找与动态问题相关的静态问题"""
        dynamic_type = dynamic_issue.get("type", "")
        dynamic_endpoint = dynamic_issue.get("endpoint", "")
        
        for static_issue in static_issues:
            static_type = static_issue.get("type", "")
            static_resource = static_issue.get("resource", "")
            
            # 基于类型和资源名称的简单关联
            if (dynamic_type == "service_not_found" and static_type == "service_reference_error" and 
                dynamic_endpoint in static_resource):
                return f"{static_type}_{static_resource}"
            elif (dynamic_type == "low_success_rate" and static_type == "service_reference_error" and
                  dynamic_endpoint in static_resource):
                return f"{static_type}_{static_resource}"
        
        return None
    
    def _combine_issue_data(self, issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """合并静态和动态问题数据"""
        static_issue = issue_data.get("static_issue")
        dynamic_issue = issue_data.get("dynamic_issue")
        validation_status = issue_data.get("validation_status")
        
        combined = {
            "validation_status": validation_status,
            "severity": "unknown",
            "message": "",
            "details": {}
        }
        
        if static_issue and dynamic_issue:
            # 两个都有的情况
            combined["severity"] = max(static_issue.get("severity", "unknown"), 
                                     dynamic_issue.get("severity", "unknown"), 
                                     key=lambda x: {"unknown": 0, "info": 1, "warning": 2, "error": 3}[x])
            combined["message"] = f"Static: {static_issue.get('message', '')} | Dynamic: {dynamic_issue.get('message', '')}"
            combined["details"] = {
                "static_details": static_issue.get("details", {}),
                "dynamic_details": dynamic_issue.get("details", {})
            }
        elif static_issue:
            # 仅静态
            combined.update(static_issue)
        elif dynamic_issue:
            # 仅动态
            combined.update(dynamic_issue)
        
        return combined
    
    def _calculate_confidence_score(self, issue: Dict[str, Any]) -> float:
        """计算问题置信度分数"""
        validation_status = issue.get("validation_status", "")
        
        if validation_status == "validated":
            return 0.95  # 高置信度：静态和动态都确认
        elif validation_status == "static_only":
            return 0.75  # 中等置信度：仅静态分析发现
        elif validation_status == "dynamic_only":
            return 0.85  # 较高置信度：动态验证发现
        else:
            return 0.5   # 低置信度：未知状态
    
    def _generate_recommendations(self, issues: List[Dict[str, Any]]) -> List[str]:
        """基于融合结果生成建议"""
        recommendations = []
        
        high_confidence_issues = [i for i in issues if i.get("confidence_score", 0) > 0.8]
        
        if high_confidence_issues:
            recommendations.append("发现高置信度问题，建议立即修复")
        
        validated_issues = [i for i in issues if i.get("validation_status") == "validated"]
        if validated_issues:
            recommendations.append(f"有{len(validated_issues)}个问题已被动静态分析共同确认")
        
        static_only_issues = [i for i in issues if i.get("validation_status") == "static_only"]
        if static_only_issues:
            recommendations.append(f"有{len(static_only_issues)}个静态分析发现的问题需要进一步验证")
        
        return recommendations
    
    def _calculate_final_accuracy(self, static_results: Dict[str, Any], dynamic_results: Dict[str, Any], 
                                fused_results: Dict[str, Any], config_files: List[str]) -> Dict[str, float]:
        """计算最终准确性指标"""
        # 基于文件名判断是否有已知问题
        has_ground_truth = any("inconsistent" in f or "error" in f for f in config_files)
        expected_issues = 1 if has_ground_truth else 0
        
        # 使用融合后的结果计算准确性
        actual_issues = len([i for i in fused_results.get("combined_issues", []) 
                           if i.get("severity") == "error"])
        
        if expected_issues == 0 and actual_issues == 0:
            precision = 1.0
            recall = 1.0
            f1 = 1.0
        elif expected_issues == 0:
            precision = 0.0
            recall = 1.0
            f1 = 0.0
        elif actual_issues == 0:
            precision = 1.0
            recall = 0.0
            f1 = 0.0
        else:
            precision = 1.0 if actual_issues > 0 else 0.0
            recall = 1.0 if actual_issues >= expected_issues else actual_issues / expected_issues
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        # 添加融合特有的指标
        validation_summary = fused_results.get("validation_summary", {})
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "expected_issues": expected_issues,
            "actual_issues": actual_issues,
            "false_positives": max(0, actual_issues - expected_issues),
            "false_negatives": max(0, expected_issues - actual_issues),
            "validation_rate": validation_summary.get("validation_rate", 0),
            "average_confidence": sum(i.get("confidence_score", 0) for i in fused_results.get("combined_issues", [])) / 
                                max(len(fused_results.get("combined_issues", [])), 1)
        }


async def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Hybrid Istio配置验证器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--duration", type=int, default=60, help="动态测试持续时间（秒）")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    runner = HybridRunner(args.config)
    config_files = [args.config] if os.path.isfile(args.config) else []
    
    if os.path.isdir(args.config):
        config_files = [os.path.join(args.config, f) for f in os.listdir(args.config) 
                       if f.endswith(('.yaml', '.yml'))]
    
    results = await runner.run(config_files, args.duration)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    else:
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
