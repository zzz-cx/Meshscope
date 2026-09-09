#!/usr/bin/env python3
"""
动静态结合一致性配置检验系统完整评估脚本
运行所有六个评估维度的测试并生成综合报告
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import concurrent.futures

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

class ComprehensiveEvaluator:
    """综合评估器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化评估器"""
        self.config = config or self._default_config()
        self.results = {
            "evaluation_start_time": datetime.now().isoformat(),
            "evaluation_metadata": {
                "system_under_test": "Istio动静态结合一致性配置检验系统",
                "evaluation_version": "1.0.0",
                "evaluator": "ComprehensiveEvaluator"
            },
            "dimension_results": {},
            "summary": {},
            "recommendations": []
        }
        
    def _default_config(self) -> Dict[str, Any]:
        """默认配置"""
        return {
            "parallel_execution": True,
            "max_workers": 3,
            "output_dir": "results",
            "comprehensive_report": True,
            "cleanup_intermediate": False,
            "evaluation_dimensions": [
                "effectiveness",
                "accuracy", 
                "realtime",
                "efficiency",
                "scalability",
                "performance"
            ]
        }
    
    def run_dimension_evaluation(self, dimension: str) -> Dict[str, Any]:
        """运行单个维度的评估"""
        print(f"\n{'='*50}")
        print(f"开始 {dimension} 评估")
        print(f"{'='*50}")
        
        dimension_start_time = time.time()
        result = {
            "dimension": dimension,
            "start_time": datetime.now().isoformat(),
            "status": "running",
            "report_file": None,
            "execution_time": 0,
            "error": None
        }
        
        try:
            # 构建评估脚本路径
            script_map = {
                "effectiveness": "effectiveness/scripts/run_effectiveness_eval.py",
                "accuracy": "accuracy/scripts/accuracy_evaluator.py",
                "realtime": "realtime/scripts/realtime_evaluator.py",
                "efficiency": "efficiency/scripts/efficiency_evaluator.py",
                "scalability": f"scalability/scripts/scalability_evaluator.py",  # 需要创建
                "performance": f"performance/scripts/performance_evaluator.py"   # 需要创建
            }
            
            script_path = Path(__file__).parent / script_map.get(dimension, "")
            
            if not script_path.exists():
                # 如果脚本不存在，创建一个简单的占位符
                result["status"] = "skipped"
                result["error"] = f"评估脚本 {script_path} 不存在，跳过该维度评估"
                print(f"警告: {result['error']}")
                return result
            
            # 执行评估脚本
            cmd = [
                sys.executable, 
                str(script_path),
                "--output", str(Path(self.config["output_dir"]) / dimension)
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200  # 2小时超时
            )
            
            if process.returncode == 0:
                result["status"] = "completed"
                result["stdout"] = process.stdout
                result["stderr"] = process.stderr
                
                # 尝试找到生成的报告文件
                output_dir = Path(self.config["output_dir"]) / dimension
                if output_dir.exists():
                    report_files = list(output_dir.glob("*_report_*.json"))
                    if report_files:
                        result["report_file"] = str(report_files[-1])  # 最新的报告文件
                        
                        # 读取报告摘要
                        try:
                            with open(report_files[-1], 'r', encoding='utf-8') as f:
                                report_data = json.load(f)
                                result["summary"] = report_data.get("summary", {})
                                result["metrics"] = report_data.get("metrics", {})
                        except Exception as e:
                            print(f"读取报告文件失败: {e}")
                            
            else:
                result["status"] = "failed"
                result["error"] = f"脚本执行失败: {process.stderr}"
                print(f"错误: {result['error']}")
                
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["error"] = "评估超时（2小时）"
            print(f"错误: {result['error']}")
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            print(f"错误: {result['error']}")
            
        finally:
            result["execution_time"] = time.time() - dimension_start_time
            result["end_time"] = datetime.now().isoformat()
            
        print(f"{dimension} 评估完成，状态: {result['status']}")
        return result
    
    def run_parallel_evaluations(self) -> Dict[str, Dict[str, Any]]:
        """并行运行多个评估维度"""
        dimensions = self.config["evaluation_dimensions"]
        max_workers = min(self.config["max_workers"], len(dimensions))
        
        print(f"开始并行评估 {len(dimensions)} 个维度，最大并发数: {max_workers}")
        
        results = {}
        
        if self.config["parallel_execution"] and max_workers > 1:
            # 并行执行
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_dimension = {
                    executor.submit(self.run_dimension_evaluation, dimension): dimension
                    for dimension in dimensions
                }
                
                for future in concurrent.futures.as_completed(future_to_dimension):
                    dimension = future_to_dimension[future]
                    try:
                        result = future.result()
                        results[dimension] = result
                    except Exception as e:
                        print(f"维度 {dimension} 评估异常: {e}")
                        results[dimension] = {
                            "dimension": dimension,
                            "status": "error",
                            "error": str(e)
                        }
        else:
            # 串行执行
            for dimension in dimensions:
                result = self.run_dimension_evaluation(dimension)
                results[dimension] = result
        
        return results
    
    def generate_comprehensive_summary(self, dimension_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """生成综合评估总结"""
        summary = {
            "total_dimensions": len(dimension_results),
            "completed_dimensions": 0,
            "failed_dimensions": 0,
            "skipped_dimensions": 0,
            "total_execution_time": 0,
            "dimension_status": {},
            "key_findings": [],
            "overall_performance": {},
            "critical_issues": [],
            "success_rate": 0
        }
        
        for dimension, result in dimension_results.items():
            status = result.get("status", "unknown")
            summary["dimension_status"][dimension] = status
            summary["total_execution_time"] += result.get("execution_time", 0)
            
            if status == "completed":
                summary["completed_dimensions"] += 1
                
                # 提取关键发现
                if result.get("summary"):
                    dimension_summary = result["summary"]
                    if "key_findings" in dimension_summary:
                        summary["key_findings"].extend(dimension_summary["key_findings"])
                
                # 提取性能指标
                if result.get("metrics"):
                    summary["overall_performance"][dimension] = result["metrics"]
                    
            elif status == "failed" or status == "error":
                summary["failed_dimensions"] += 1
                summary["critical_issues"].append(f"{dimension}: {result.get('error', '未知错误')}")
                
            elif status == "skipped":
                summary["skipped_dimensions"] += 1
        
        # 计算成功率
        total_attempted = summary["total_dimensions"] - summary["skipped_dimensions"]
        if total_attempted > 0:
            summary["success_rate"] = summary["completed_dimensions"] / total_attempted
        
        return summary
    
    def generate_recommendations(self, summary: Dict[str, Any]) -> List[str]:
        """基于评估结果生成改进建议"""
        recommendations = []
        
        # 基于成功率的建议
        success_rate = summary.get("success_rate", 0)
        if success_rate < 0.8:
            recommendations.append("系统整体稳定性需要改进，建议优先解决失败的评估维度问题")
        
        # 基于性能的建议
        performance = summary.get("overall_performance", {})
        
        if "effectiveness" in performance:
            effectiveness_metrics = performance["effectiveness"]
            if effectiveness_metrics.get("accuracy", 0) < 0.8:
                recommendations.append("有效性评估显示检测准确率偏低，建议优化检测算法")
        
        if "realtime" in performance:
            realtime_metrics = performance["realtime"]
            if realtime_metrics.get("average_response_time", float('inf')) > 60:
                recommendations.append("实时性评估显示响应时间过长，建议优化系统响应速度")
        
        if "scalability" in performance:
            scalability_metrics = performance["scalability"]
            if scalability_metrics.get("linear_scaling_efficiency", 0) < 0.7:
                recommendations.append("可扩展性评估显示线性扩展效率不足，建议优化系统架构")
        
        # 通用建议
        if summary["failed_dimensions"] > 0:
            recommendations.append("建议修复失败的评估维度，确保系统功能完整性")
        
        if summary["total_execution_time"] > 28800:  # 8小时
            recommendations.append("评估总时间过长，建议优化评估流程和提高并行度")
        
        # 如果没有特定建议，添加默认建议
        if not recommendations:
            recommendations.extend([
                "系统整体表现良好，建议继续监控各项指标",
                "建议建立定期评估机制，持续跟踪系统性能变化",
                "考虑引入更多自动化测试用例，提高评估覆盖度"
            ])
        
        return recommendations
    
    def generate_comprehensive_report(self) -> str:
        """生成综合评估报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = Path(self.config["output_dir"]) / f"comprehensive_evaluation_report_{timestamp}.json"
        
        # 确保输出目录存在
        report_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 添加评估结束时间
        self.results["evaluation_end_time"] = datetime.now().isoformat()
        self.results["total_evaluation_time"] = time.time() - time.mktime(
            datetime.fromisoformat(self.results["evaluation_start_time"]).timetuple()
        )
        
        # 写入报告文件
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        print(f"\n综合评估报告已生成: {report_file}")
        return str(report_file)
    
    def run_comprehensive_evaluation(self) -> str:
        """运行完整的综合评估"""
        print("开始动静态结合一致性配置检验系统综合评估")
        print(f"评估维度: {', '.join(self.config['evaluation_dimensions'])}")
        print(f"并行执行: {'是' if self.config['parallel_execution'] else '否'}")
        
        try:
            # 运行各维度评估
            dimension_results = self.run_parallel_evaluations()
            self.results["dimension_results"] = dimension_results
            
            # 生成综合总结
            summary = self.generate_comprehensive_summary(dimension_results)
            self.results["summary"] = summary
            
            # 生成改进建议
            recommendations = self.generate_recommendations(summary)
            self.results["recommendations"] = recommendations
            
            # 生成报告
            report_file = self.generate_comprehensive_report()
            
            # 打印总结
            self._print_evaluation_summary()
            
            return report_file
            
        except Exception as e:
            print(f"综合评估过程中发生错误: {e}")
            self.results["evaluation_error"] = str(e)
            return self.generate_comprehensive_report()
    
    def _print_evaluation_summary(self):
        """打印评估总结到控制台"""
        print("\n" + "="*80)
        print("综合评估总结")
        print("="*80)
        
        summary = self.results.get("summary", {})
        
        print(f"总评估维度数: {summary.get('total_dimensions', 0)}")
        print(f"成功完成: {summary.get('completed_dimensions', 0)}")
        print(f"执行失败: {summary.get('failed_dimensions', 0)}")
        print(f"跳过执行: {summary.get('skipped_dimensions', 0)}")
        print(f"成功率: {summary.get('success_rate', 0):.2%}")
        print(f"总执行时间: {summary.get('total_execution_time', 0):.1f}秒")
        
        # 打印各维度状态
        print("\n各维度评估状态:")
        dimension_status = summary.get("dimension_status", {})
        for dimension, status in dimension_status.items():
            status_emoji = {"completed": "✅", "failed": "❌", "skipped": "⏭️", "error": "⚠️"}.get(status, "❓")
            print(f"  {status_emoji} {dimension}: {status}")
        
        # 打印关键问题
        critical_issues = summary.get("critical_issues", [])
        if critical_issues:
            print("\n关键问题:")
            for issue in critical_issues:
                print(f"  ⚠️ {issue}")
        
        # 打印改进建议
        recommendations = self.results.get("recommendations", [])
        if recommendations:
            print("\n改进建议:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
        
        print("\n" + "="*80)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="动静态结合一致性配置检验系统综合评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    parser.add_argument("--parallel", action="store_true", default=True, help="启用并行执行")
    parser.add_argument("--max-workers", type=int, default=3, help="最大并发数")
    parser.add_argument("--dimensions", nargs="+", 
                       choices=["effectiveness", "accuracy", "realtime", "efficiency", "scalability", "performance"],
                       default=["effectiveness", "accuracy", "realtime", "efficiency", "scalability", "performance"],
                       help="要评估的维度")
    
    args = parser.parse_args()
    
    # 构建配置
    config = {
        "output_dir": args.output,
        "parallel_execution": args.parallel,
        "max_workers": args.max_workers,
        "evaluation_dimensions": args.dimensions
    }
    
    # 如果指定了配置文件，加载配置
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            file_config = json.load(f)
            config.update(file_config)
    
    # 运行评估
    evaluator = ComprehensiveEvaluator(config)
    report_file = evaluator.run_comprehensive_evaluation()
    
    print(f"\n🎉 综合评估完成！")
    print(f"📊 详细报告: {report_file}")

if __name__ == "__main__":
    main()
