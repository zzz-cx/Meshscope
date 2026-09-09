#!/usr/bin/env python3
"""
Accuracy评估实验主控脚本
调用所有检测方法并收集结果
"""

import asyncio
import argparse
import json
import yaml
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
import os

# 添加方法模块路径
sys.path.append(str(Path(__file__).parent.parent / "methods"))

from static_only import StaticOnlyDetector
from dynamic_only import DynamicOnlyDetector
from hybrid import HybridDetector
from existing_tools import ExistingToolsDetector

from evaluator import AccuracyEvaluator
from utils import ExperimentUtils

class AccuracyExperimentRunner:
    """Accuracy评估实验运行器"""
    
    def __init__(self, config_file: str):
        """初始化实验运行器"""
        self.config = self._load_config(config_file)
        self.logger = self._setup_logging()
        
        # 初始化检测器
        self.detectors = {
            "static_only": StaticOnlyDetector(self.config),
            "dynamic_only": DynamicOnlyDetector(self.config),
            "hybrid": HybridDetector(self.config),
            "existing_tools": ExistingToolsDetector(self.config)
        }
        
        # 初始化评估器
        self.evaluator = AccuracyEvaluator(self.config)
        
        # 初始化工具
        self.utils = ExperimentUtils(self.config)
        
        # 加载ground truth
        self.ground_truth = self._load_ground_truth()
        
        # 实验结果
        self.experiment_results = {
            "experiment_info": {
                "start_time": datetime.now().isoformat(),
                "config_file": config_file,
                "total_configs": 0,
                "methods_tested": list(self.detectors.keys())
            },
            "method_results": {},
            "comparison_results": {},
            "statistical_analysis": {},
            "summary": {}
        }
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载实验配置"""
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 创建格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        
        return logger
    
    def _load_ground_truth(self) -> Dict[str, Any]:
        """加载ground truth"""
        ground_truth_file = Path(__file__).parent.parent / "configs" / "ground_truth.json"
        
        with open(ground_truth_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    async def run_experiment(self, methods: List[str] = None, configs: List[str] = None) -> Dict[str, Any]:
        """运行实验"""
        self.logger.info("开始Accuracy评估实验")
        
        # 确定要测试的方法
        if methods is None:
            methods = list(self.detectors.keys())
        
        # 确定要测试的配置
        if configs is None:
            configs = self._get_all_config_files()
        
        self.experiment_results["experiment_info"]["total_configs"] = len(configs)
        self.experiment_results["experiment_info"]["methods_tested"] = methods
        
        self.logger.info(f"测试方法: {methods}")
        self.logger.info(f"测试配置数量: {len(configs)}")
        
        # 运行每种检测方法
        for method_name in methods:
            if method_name in self.detectors:
                self.logger.info(f"运行 {method_name} 检测方法")
                
                try:
                    start_time = time.time()
                    
                    if method_name == "dynamic_only" or method_name == "hybrid":
                        # 异步方法
                        result = await self.detectors[method_name].detect_faults(configs)
                    else:
                        # 同步方法
                        result = self.detectors[method_name].detect_faults(configs)
                    
                    end_time = time.time()
                    result["execution_time"] = end_time - start_time
                    
                    self.experiment_results["method_results"][method_name] = result
                    
                    self.logger.info(f"{method_name} 完成，执行时间: {result['execution_time']:.2f}秒")
                    
                except Exception as e:
                    self.logger.error(f"{method_name} 执行失败: {e}")
                    self.experiment_results["method_results"][method_name] = {
                        "error": str(e),
                        "execution_time": 0
                    }
            else:
                self.logger.warning(f"未知的检测方法: {method_name}")
        
        # 进行结果比较和评估
        self.logger.info("进行结果比较和评估")
        self.experiment_results["comparison_results"] = self.evaluator.compare_methods(
            self.experiment_results["method_results"], self.ground_truth
        )
        
        # 进行统计分析
        self.logger.info("进行统计分析")
        self.experiment_results["statistical_analysis"] = self.evaluator.perform_statistical_analysis(
            self.experiment_results["comparison_results"]
        )
        
        # 生成总结
        self.experiment_results["summary"] = self.evaluator.generate_summary(
            self.experiment_results["method_results"],
            self.experiment_results["comparison_results"],
            self.experiment_results["statistical_analysis"]
        )
        
        self.experiment_results["experiment_info"]["end_time"] = datetime.now().isoformat()
        
        self.logger.info("Accuracy评估实验完成")
        return self.experiment_results
    
    def _get_all_config_files(self) -> List[str]:
        """获取所有配置文件"""
        config_dir = Path(__file__).parent.parent / "configs"
        config_files = []
        
        # 遍历所有子目录
        for subdir in ["human_errors", "real_world", "mutated", "correct"]:
            subdir_path = config_dir / subdir
            if subdir_path.exists():
                for config_file in subdir_path.glob("*.yaml"):
                    config_files.append(str(config_file))
        
        return config_files
    
    def save_results(self, output_file: str = None):
        """保存实验结果"""
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"results/accuracy_experiment_results_{timestamp}.json"
        
        # 确保输出目录存在
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存结果
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.experiment_results, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"实验结果已保存到: {output_file}")
        return output_file
    
    def generate_report(self, output_file: str = None):
        """生成实验报告"""
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"results/accuracy_experiment_report_{timestamp}.md"
        
        # 确保输出目录存在
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 生成Markdown报告
        report_content = self._generate_markdown_report()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        self.logger.info(f"实验报告已生成: {output_file}")
        return output_file
    
    def _generate_markdown_report(self) -> str:
        """生成Markdown格式的报告"""
        report = []
        
        # 标题
        report.append("# Accuracy评估实验报告")
        report.append("")
        
        # 实验信息
        experiment_info = self.experiment_results["experiment_info"]
        report.append("## 实验信息")
        report.append("")
        report.append(f"- **开始时间**: {experiment_info['start_time']}")
        report.append(f"- **结束时间**: {experiment_info['end_time']}")
        report.append(f"- **测试配置数量**: {experiment_info['total_configs']}")
        report.append(f"- **测试方法**: {', '.join(experiment_info['methods_tested'])}")
        report.append("")
        
        # 方法结果摘要
        report.append("## 方法结果摘要")
        report.append("")
        
        method_results = self.experiment_results["method_results"]
        for method_name, result in method_results.items():
            if "error" in result:
                report.append(f"### {method_name}")
                report.append(f"- **状态**: 执行失败")
                report.append(f"- **错误**: {result['error']}")
                report.append("")
            else:
                summary = result.get("summary", {})
                report.append(f"### {method_name}")
                report.append(f"- **执行时间**: {result.get('execution_time', 0):.2f}秒")
                report.append(f"- **检测到故障数**: {summary.get('total_faults', 0)}")
                report.append(f"- **有故障的配置文件数**: {summary.get('files_with_faults', 0)}")
                report.append("")
        
        # 比较结果
        report.append("## 方法比较结果")
        report.append("")
        
        comparison_results = self.experiment_results["comparison_results"]
        if comparison_results:
            report.append("### 主要指标对比")
            report.append("")
            report.append("| 方法 | Precision | Recall | F1-Score |")
            report.append("|------|-----------|--------|----------|")
            
            for method_name, metrics in comparison_results.get("method_metrics", {}).items():
                precision = metrics.get("precision", 0)
                recall = metrics.get("recall", 0)
                f1_score = metrics.get("f1_score", 0)
                report.append(f"| {method_name} | {precision:.3f} | {recall:.3f} | {f1_score:.3f} |")
            
            report.append("")
        
        # 统计分析
        report.append("## 统计分析")
        report.append("")
        
        statistical_analysis = self.experiment_results["statistical_analysis"]
        if statistical_analysis:
            report.append("### 统计显著性检验")
            report.append("")
            
            for test_name, test_result in statistical_analysis.get("significance_tests", {}).items():
                report.append(f"**{test_name}**:")
                report.append(f"- p值: {test_result.get('p_value', 'N/A')}")
                report.append(f"- 显著性: {'是' if test_result.get('significant', False) else '否'}")
                report.append("")
        
        # 总结
        report.append("## 实验总结")
        report.append("")
        
        summary = self.experiment_results["summary"]
        if summary:
            report.append(f"**最佳方法**: {summary.get('best_method', 'N/A')}")
            report.append(f"**最佳F1-Score**: {summary.get('best_f1_score', 0):.3f}")
            report.append(f"**主要发现**: {summary.get('key_findings', 'N/A')}")
            report.append("")
        
        return "\n".join(report)

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Accuracy评估实验")
    parser.add_argument("--config", default="experiment_config.yaml", help="实验配置文件")
    parser.add_argument("--methods", nargs="+", help="要测试的检测方法")
    parser.add_argument("--configs", nargs="+", help="要测试的配置文件")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--report", help="报告文件路径")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 检查配置文件
    config_path = Path(__file__).parent.parent / args.config
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return
    
    # 初始化实验运行器
    runner = AccuracyExperimentRunner(str(config_path))
    
    # 运行实验
    results = await runner.run_experiment(
        methods=args.methods,
        configs=args.configs
    )
    
    # 保存结果
    output_file = runner.save_results(args.output)
    
    # 生成报告
    report_file = runner.generate_report(args.report)
    
    # 打印摘要
    print("\n📊 实验摘要:")
    summary = results["summary"]
    if summary:
        print(f"   最佳方法: {summary.get('best_method', 'N/A')}")
        print(f"   最佳F1-Score: {summary.get('best_f1_score', 0):.3f}")
        print(f"   主要发现: {summary.get('key_findings', 'N/A')}")
    
    print(f"\n📁 结果文件: {output_file}")
    print(f"📄 报告文件: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())
