#!/usr/bin/env python3
"""
实验三主入口脚本 - 调度不同对比方法
"""

import os
import sys
import json
import time
import asyncio
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import yaml

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 导入实验模块
try:
    from runners.static_runner import StaticRunner
    STATIC_RUNNER_AVAILABLE = True
except ImportError:
    STATIC_RUNNER_AVAILABLE = False

try:
    from runners.simple_static_runner import SimpleStaticRunner
    SIMPLE_STATIC_RUNNER_AVAILABLE = True
except ImportError:
    SIMPLE_STATIC_RUNNER_AVAILABLE = False

from runners.dynamic_runner import DynamicRunner

try:
    from runners.hybrid_runner import HybridRunner
    HYBRID_RUNNER_AVAILABLE = True
except ImportError:
    HYBRID_RUNNER_AVAILABLE = False
from monitor.watcher import ConfigWatcher, ConfigChangeEvent
from utils.instrumentation import get_instrumentation, stage_timer, log_stage_start, log_stage_end
from utils.metrics import MetricsAnalyzer


class Experiment3Runner:
    """实验三运行器"""
    
    def __init__(self, config_file: str = None):
        """初始化实验运行器"""
        self.config = self._load_config(config_file)
        self.results = {
            "experiment_id": f"exp3_{int(time.time())}",
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "config": self.config,
            "method_results": {},
            "comparison_analysis": {},
            "summary": {}
        }
        
        # 初始化打点管理器
        self.instrumentation = get_instrumentation()
        
        # 初始化配置监听器
        self.watcher = ConfigWatcher(
            watch_paths=self.config.get("watch_paths", ["configs"]),
            namespace=self.config.get("namespace", "default")
        )
        
        # 运行器映射
        self.runners = {}
        
        if STATIC_RUNNER_AVAILABLE:
            self.runners["static_only"] = StaticRunner
        if SIMPLE_STATIC_RUNNER_AVAILABLE:
            self.runners["simple_static_only"] = SimpleStaticRunner
        if HYBRID_RUNNER_AVAILABLE:
            self.runners["hybrid"] = HybridRunner
        
        self.runners["dynamic_only"] = DynamicRunner
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载实验配置"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        
        # 默认配置
        return {
            "experiment_name": "Experiment 3: Configuration Change Response",
            "description": "评估系统在频繁配置变更场景下的响应能力",
            "config_scales": ["small", "medium", "large"],
            "change_rates": ["low", "medium", "high"],
            "methods": ["static_only", "dynamic_only"],
            "repetitions": 10,
            "test_duration": 60,  # 秒
            "output_dir": "results",
            "namespace": "default",
            "watch_paths": ["configs"],
            "metrics": {
                "confidence_level": 0.95,
                "bootstrap_samples": 1000
            }
        }
    
    async def run_experiment(self) -> Dict[str, Any]:
        """运行完整实验"""
        try:
            log_stage_start("Experiment", {"experiment_id": self.results["experiment_id"]})
            
            # 1. 初始化阶段
            await self._initialize_experiment()
            
            # 2. 运行各配置规模和变更速率的组合
            all_results = []
            
            for config_scale in self.config["config_scales"]:
                for change_rate in self.config["change_rates"]:
                    scale_results = await self._run_configuration_scale(
                        config_scale, change_rate
                    )
                    all_results.extend(scale_results)
            
            # 3. 分析结果
            await self._analyze_results(all_results)
            
            # 4. 生成报告
            report_file = await self._generate_report()
            
            self.results["end_time"] = datetime.now().isoformat()
            log_stage_end("Experiment", {"report_file": report_file})
            
            return self.results
            
        except Exception as e:
            self.results["error"] = str(e)
            self.results["end_time"] = datetime.now().isoformat()
            log_stage_end("Experiment", {"error": str(e)})
            raise
    
    async def _initialize_experiment(self):
        """初始化实验"""
        log_stage_start("Initialization")
        
        # 创建输出目录
        output_dir = Path(self.config["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 启动配置监听器
        self.watcher.start()
        
        log_stage_end("Initialization")
    
    async def _run_configuration_scale(self, config_scale: str, change_rate: str) -> List[Dict[str, Any]]:
        """运行特定配置规模和变更速率的实验"""
        log_stage_start("ConfigScale", {
            "scale": config_scale,
            "change_rate": change_rate
        })
        
        results = []
        config_files = self._get_config_files(config_scale)
        
        # 为每种方法运行实验
        for method in self.config["methods"]:
            method_results = await self._run_method_experiments(
                method, config_scale, change_rate, config_files
            )
            results.extend(method_results)
        
        log_stage_end("ConfigScale", {
            "scale": config_scale,
            "change_rate": change_rate,
            "total_experiments": len(results)
        })
        
        return results
    
    async def _run_method_experiments(self, method: str, config_scale: str, 
                                    change_rate: str, config_files: List[str]) -> List[Dict[str, Any]]:
        """运行特定方法的重复实验"""
        log_stage_start("Method", {
            "method": method,
            "scale": config_scale,
            "change_rate": change_rate
        })
        
        results = []
        repetitions = self.config["repetitions"]
        
        for i in range(repetitions):
            log_stage_start("Repetition", {
                "method": method,
                "repetition": i + 1,
                "total": repetitions
            })
            
            try:
                # 创建运行器实例
                runner_class = self.runners.get(method)
                if not runner_class:
                    raise ValueError(f"Unknown method: {method}")
                
                runner = runner_class(f"configs/{config_scale}")
                
                # 根据方法类型调整参数
                if method == "dynamic_only" or method == "hybrid":
                    duration = self._get_test_duration(change_rate)
                    result = await runner.run(config_files, duration)
                else:
                    result = await runner.run(config_files)
                
                # 添加元数据
                result.update({
                    "method": method,
                    "config_scale": config_scale,
                    "change_rate": change_rate,
                    "repetition": i + 1,
                    "timestamp": datetime.now().isoformat()
                })
                
                results.append(result)
                
                log_stage_end("Repetition", {
                    "method": method,
                    "repetition": i + 1,
                    "success": True,
                    "duration": result.get("total_time", 0)
                })
                
                # 短暂延迟避免资源竞争
                await asyncio.sleep(1)
                
            except Exception as e:
                error_result = {
                    "method": method,
                    "config_scale": config_scale,
                    "change_rate": change_rate,
                    "repetition": i + 1,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                    "success": False
                }
                results.append(error_result)
                
                log_stage_end("Repetition", {
                    "method": method,
                    "repetition": i + 1,
                    "success": False,
                    "error": str(e)
                })
        
        log_stage_end("Method", {
            "method": method,
            "scale": config_scale,
            "change_rate": change_rate,
            "successful_runs": len([r for r in results if r.get("success", True)]),
            "failed_runs": len([r for r in results if not r.get("success", True)])
        })
        
        return results
    
    def _get_config_files(self, config_scale: str) -> List[str]:
        """获取指定规模的配置文件"""
        config_dir = Path(f"configs/{config_scale}")
        
        if not config_dir.exists():
            raise FileNotFoundError(f"Config directory not found: {config_dir}")
        
        config_files = []
        for file_path in config_dir.glob("*.yaml"):
            config_files.append(str(file_path))
        
        return config_files
    
    def _get_test_duration(self, change_rate: str) -> int:
        """根据变更速率获取测试持续时间"""
        duration_map = {
            "low": 300,    # 5分钟
            "medium": 120, # 2分钟
            "high": 60     # 1分钟
        }
        return duration_map.get(change_rate, 60)
    
    async def _analyze_results(self, all_results: List[Dict[str, Any]]):
        """分析实验结果"""
        log_stage_start("Analysis")
        
        # 使用指标分析器
        analyzer = MetricsAnalyzer()
        analysis = analyzer.analyze_experiment_results(all_results)
        
        # 按方法分组分析
        method_analysis = {}
        for method in self.config["methods"]:
            method_results = [r for r in all_results if r.get("method") == method]
            if method_results:
                method_analysis[method] = analyzer.analyze_experiment_results(method_results)
        
        # 按配置规模分析
        scale_analysis = {}
        for scale in self.config["config_scales"]:
            scale_results = [r for r in all_results if r.get("config_scale") == scale]
            if scale_results:
                scale_analysis[scale] = analyzer.analyze_experiment_results(scale_results)
        
        # 按变更速率分析
        rate_analysis = {}
        for rate in self.config["change_rates"]:
            rate_results = [r for r in all_results if r.get("change_rate") == rate]
            if rate_results:
                rate_analysis[rate] = analyzer.analyze_experiment_results(rate_results)
        
        self.results["method_results"] = all_results
        self.results["comparison_analysis"] = {
            "overall": analysis,
            "by_method": method_analysis,
            "by_scale": scale_analysis,
            "by_rate": rate_analysis
        }
        
        # 生成总结
        self.results["summary"] = self._generate_summary(analysis, method_analysis)
        
        log_stage_end("Analysis")
    
    def _generate_summary(self, overall_analysis: Dict[str, Any], 
                         method_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """生成实验总结"""
        summary = {
            "total_experiments": overall_analysis.get("summary", {}).get("total_experiments", 0),
            "success_rate": 0.0,
            "best_method": None,
            "performance_insights": [],
            "accuracy_insights": [],
            "recommendations": overall_analysis.get("recommendations", [])
        }
        
        # 计算成功率
        successful = overall_analysis.get("summary", {}).get("successful_experiments", 0)
        total = overall_analysis.get("summary", {}).get("total_experiments", 1)
        summary["success_rate"] = successful / total
        
        # 找出最佳方法
        if method_analysis:
            best_method = None
            best_f1 = 0.0
            
            for method, analysis in method_analysis.items():
                f1_score = analysis.get("accuracy_analysis", {}).get("f1_score", {}).get("mean", 0)
                if f1_score > best_f1:
                    best_f1 = f1_score
                    best_method = method
            
            summary["best_method"] = best_method
        
        # 性能洞察
        performance = overall_analysis.get("performance_analysis", {})
        if performance:
            for method, metrics in performance.items():
                avg_latency = metrics.get("average_latency_ms", 0)
                summary["performance_insights"].append({
                    "method": method,
                    "average_latency_ms": avg_latency,
                    "performance_grade": self._grade_performance(avg_latency)
                })
        
        # 准确性洞察
        accuracy = overall_analysis.get("accuracy_analysis", {})
        if accuracy:
            f1_mean = accuracy.get("f1_score", {}).get("mean", 0)
            summary["accuracy_insights"].append({
                "overall_f1_score": f1_mean,
                "accuracy_grade": self._grade_accuracy(f1_mean)
            })
        
        return summary
    
    def _grade_performance(self, latency_ms: float) -> str:
        """性能评级"""
        if latency_ms < 1000:
            return "优秀"
        elif latency_ms < 5000:
            return "良好"
        elif latency_ms < 10000:
            return "一般"
        else:
            return "需要改进"
    
    def _grade_accuracy(self, f1_score: float) -> str:
        """准确性评级"""
        if f1_score >= 0.9:
            return "优秀"
        elif f1_score >= 0.8:
            return "良好"
        elif f1_score >= 0.7:
            return "一般"
        else:
            return "需要改进"
    
    async def _generate_report(self) -> str:
        """生成实验报告"""
        log_stage_start("ReportGeneration")
        
        output_dir = Path(self.config["output_dir"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = output_dir / f"experiment3_report_{timestamp}.json"
        
        # 保存详细结果
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        # 导出打点数据
        instrumentation_file = output_dir / f"instrumentation_{timestamp}.json"
        self.instrumentation.logger.export_points(str(instrumentation_file))
        
        log_stage_end("ReportGeneration", {"report_file": str(report_file)})
        
        return str(report_file)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="实验三：配置变更响应能力评估")
    parser.add_argument("--config", help="实验配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    parser.add_argument("--scales", nargs="+", help="配置规模列表", 
                       choices=["small", "medium", "large"], default=["small", "medium", "large"])
    parser.add_argument("--rates", nargs="+", help="变更速率列表",
                       choices=["low", "medium", "high"], default=["low", "medium", "high"])
    parser.add_argument("--methods", nargs="+", help="对比方法列表",
                       choices=["static_only", "dynamic_only", "hybrid"], 
                       default=["static_only", "dynamic_only", "hybrid"])
    parser.add_argument("--repetitions", type=int, help="重复次数", default=10)
    parser.add_argument("--duration", type=int, help="测试持续时间（秒）", default=60)
    
    args = parser.parse_args()
    
    # 创建实验配置
    config = {
        "config_scales": args.scales,
        "change_rates": args.rates,
        "methods": args.methods,
        "repetitions": args.repetitions,
        "test_duration": args.duration,
        "output_dir": args.output
    }
    
    # 如果有配置文件，加载并更新
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            file_config = yaml.safe_load(f)
            config.update(file_config)
    
    # 保存配置到临时文件
    temp_config_file = "temp_experiment_config.yaml"
    with open(temp_config_file, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    try:
        # 运行实验
        runner = Experiment3Runner(temp_config_file)
        results = await runner.run_experiment()
        
        print(f"\n实验完成！")
        print(f"实验ID: {results['experiment_id']}")
        print(f"总实验数: {results['summary']['total_experiments']}")
        print(f"成功率: {results['summary']['success_rate']:.2%}")
        
        if results['summary']['best_method']:
            print(f"最佳方法: {results['summary']['best_method']}")
        
        print(f"详细报告: {results.get('report_file', 'N/A')}")
        
    finally:
        # 清理临时文件
        if os.path.exists(temp_config_file):
            os.remove(temp_config_file)


if __name__ == "__main__":
    asyncio.run(main())
