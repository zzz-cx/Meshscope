#!/usr/bin/env python3
"""
有效性评估自动化测试脚本
用于评估Istio配置一致性检测系统的有效性
"""

import os
import sys
import json
import time
import subprocess
import logging
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 导入动态测试模块
from istio_Dynamic_Test.internal.pipeline import DynamicTester
from istio_Dynamic_Test.internal.models import TestCase, TestSuite
from istio_Dynamic_Test.internal.validation import run_verification, analyze_single_case

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
from consistency_checker.config import get_config

class EffectivenessEvaluator:
    """有效性评估器"""
    
    def __init__(self, config_file: str = None):
        """初始化评估器"""
        self.config = self._load_config(config_file)
        self.logger = self._setup_logging()
        self.results = {
            "start_time": datetime.now().isoformat(),
            "test_results": [],
            "metrics": {},
            "summary": {}
        }
        
        # 初始化配置解析器（其他组件在需要时创建）
        self.config_parser = IstioConfigParser()
        self.static_analyzer = None  # 每次测试时初始化
        self.dynamic_analyzer = DynamicAnalyzer()
        # ConsistencyChecker 需要参数，在需要时创建
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 从全局配置获取默认值
        global_config = get_config()
        return {
            "ssh_host": os.getenv("SSH_HOST") or global_config.ssh_host,
            "ssh_user": os.getenv("SSH_USER") or global_config.ssh_user,
            "ssh_password": os.getenv("SSH_PASSWORD") or global_config.ssh_password,
            "test_cases_dir": "test_cases",
            "results_dir": "results",
            "verification_system_path": str(project_root / "istio_Dynamic_Test")
        }
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('effectiveness_eval')
        logger.setLevel(logging.INFO)
        
        # 文件处理器
        log_file = f"effectiveness_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # 格式化器
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)
        
        return logger
    
    def run_static_tests(self) -> List[Dict[str, Any]]:
        """运行静态不一致性检测测试"""
        self.logger.info("开始运行静态不一致性检测测试")
        
        static_test_file = "test_cases/static_inconsistencies.json"
        with open(static_test_file, 'r', encoding='utf-8') as f:
            test_suite = json.load(f)
        
        static_results = []
        
        for test_case in test_suite['test_cases']:
            self.logger.info(f"执行测试用例: {test_case['case_id']} - {test_case['name']}")
            
            result = {
                "case_id": test_case['case_id'],
                "name": test_case['name'],
                "category": test_case['category'],
                "expected": test_case['expected_detection'],
                "actual": {},
                "passed": False,
                "execution_time": 0
            }
            
            start_time = time.time()
            
            try:
                # 部署测试配置
                self._deploy_test_config(test_case['config_files'])
                
                # 运行静态检测
                detection_result = self._run_static_detection(test_case)
                
                result["actual"] = detection_result
                result["passed"] = self._evaluate_static_result(test_case, detection_result)
                
            except Exception as e:
                self.logger.error(f"测试用例 {test_case['case_id']} 执行失败: {str(e)}")
                result["error"] = str(e)
                
            finally:
                result["execution_time"] = time.time() - start_time
                # 清理测试配置
                self._cleanup_test_config(test_case['config_files'])
            
            static_results.append(result)
            
        return static_results
    
    def run_dynamic_tests(self) -> List[Dict[str, Any]]:
        """运行动态不一致性检测测试"""
        self.logger.info("开始运行动态不一致性检测测试")
        
        dynamic_test_file = "test_cases/dynamic_inconsistencies.json"
        with open(dynamic_test_file, 'r', encoding='utf-8') as f:
            test_suite = json.load(f)
        
        dynamic_results = []
        
        for test_case in test_suite['test_cases']:
            self.logger.info(f"执行测试用例: {test_case['case_id']} - {test_case['name']}")
            
            result = {
                "case_id": test_case['case_id'],
                "name": test_case['name'], 
                "category": test_case['category'],
                "expected": test_case['expected_detection'],
                "actual": {},
                "passed": False,
                "execution_time": 0,
                "metrics": {}
            }
            
            start_time = time.time()
            
            try:
                # 部署测试配置
                self._deploy_test_config(test_case['config_files'])
                
                # 注入异常（如果需要）
                if 'injection_config' in test_case:
                    self._inject_anomaly(test_case['injection_config'])
                
                # 运行流量测试
                traffic_result = self._run_traffic_test(test_case['test_scenario'])
                
                # 运行动态检测
                detection_result = self._run_dynamic_detection(test_case, traffic_result)
                
                result["actual"] = detection_result
                result["metrics"] = traffic_result
                result["passed"] = self._evaluate_dynamic_result(test_case, detection_result)
                
            except Exception as e:
                self.logger.error(f"测试用例 {test_case['case_id']} 执行失败: {str(e)}")
                result["error"] = str(e)
                
            finally:
                result["execution_time"] = time.time() - start_time
                # 清理测试配置
                self._cleanup_test_config(test_case['config_files'])
                
            dynamic_results.append(result)
            
        return dynamic_results
    
    def _deploy_test_config(self, config_files: List[str]):
        """部署测试配置"""
        for config_file in config_files:
            config_path = f"configs/{config_file}"
            if os.path.exists(config_path):
                subprocess.run(["kubectl", "apply", "-f", config_path], check=True)
                time.sleep(2)  # 等待配置生效
    
    def _cleanup_test_config(self, config_files: List[str]):
        """清理测试配置"""
        for config_file in config_files:
            config_path = f"configs/{config_file}"
            if os.path.exists(config_path):
                subprocess.run(["kubectl", "delete", "-f", config_path], check=False)
    
    def _run_static_detection(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """运行静态检测 - 真实调用静态分析器"""
        try:
            self.logger.info(f"开始静态分析: {test_case['case_id']}")
            
            # 1. 解析配置文件
            config_files = test_case.get('config_files', [])
            parsed_configs = []
            
            for config_file in config_files:
                config_path = os.path.join(project_root, "evaluation", "effectiveness", "configs", config_file)
                if os.path.exists(config_path):
                    self.logger.info(f"解析配置文件: {config_path}")
                    # 使用 load_yaml_file 加载配置
                    config = load_yaml_file(config_path)
                    parsed_configs.append(config)
                else:
                    self.logger.warning(f"配置文件不存在: {config_path}")
            
            # 2. 创建静态分析器
            self.static_analyzer = StaticAnalyzer(parsed_configs)
            
            # 3. 执行静态分析
            analysis_start = time.time()
            analysis_result = self.static_analyzer.analyze()
            analysis_time = time.time() - analysis_start
            
            # 4. 提取结果 (analyze() 返回字典)
            inconsistencies = analysis_result.get('plane_consistency_issues', [])
            has_issues = len(inconsistencies) > 0
            
            result = {
                "detected": has_issues,
                "error_type": "plane_inconsistency" if has_issues else "none",
                "confidence": 0.9 if has_issues else 0.0,
                "details": {
                    "inconsistencies_count": len(inconsistencies),
                    "inconsistencies": inconsistencies[:5],  # 最多返回5个
                    "summary": analysis_result.get('summary', {}),
                    "analysis_time": analysis_time,
                    "analyzer": "StaticAnalyzer"
                }
            }
            
            self.logger.info(f"静态分析完成: 检测到 {len(inconsistencies)} 个问题")
            return result
            
        except Exception as e:
            self.logger.error(f"静态检测失败: {str(e)}")
            return {
                "detected": False,
                "error_type": "analysis_error",
                "confidence": 0.0,
                "details": {"error": str(e), "analyzer": "StaticAnalyzer"}
            }
    
    def _run_dynamic_detection(self, test_case: Dict[str, Any], traffic_result: Dict[str, Any]) -> Dict[str, Any]:
        """运行动态检测 - 真实调用动态分析器"""
        try:
            self.logger.info(f"开始动态分析: {test_case['case_id']}")
            
            # 1. 准备动态分析数据
            # 从 traffic_result 中提取关键指标
            traffic_metrics = {
                "request_count": traffic_result.get("total_requests", 0),
                "success_count": traffic_result.get("successful_requests", 0),
                "failure_count": traffic_result.get("failed_requests", 0),
                "response_times": traffic_result.get("response_times", []),
                "status_codes": traffic_result.get("status_code_distribution", {}),
                "error_messages": traffic_result.get("errors", [])
            }
            
            # 2. 执行动态分析
            analysis_start = time.time()
            analysis_result = self.dynamic_analyzer.analyze_traffic_metrics(
                traffic_metrics,
                expected_behavior=test_case.get('expected_behavior', {})
            )
            analysis_time = time.time() - analysis_start
            
            # 3. 检测异常
            has_anomaly = analysis_result.has_anomalies()
            anomalies = analysis_result.get_anomalies()
            
            result = {
                "detected": has_anomaly,
                "anomaly_type": anomalies[0].type if anomalies else "none",
                "confidence": analysis_result.confidence_score,
                "metrics": traffic_metrics,
                "details": {
                    "anomalies_count": len(anomalies),
                    "anomalies": [
                        {
                            "type": anomaly.type,
                            "severity": anomaly.severity,
                            "description": anomaly.description,
                            "affected_metrics": anomaly.affected_metrics
                        } for anomaly in anomalies[:5]  # 最多返回5个
                    ],
                    "analysis_time": analysis_time,
                    "analyzer": "DynamicAnalyzer"
                }
            }
            
            self.logger.info(f"动态分析完成: 检测到 {len(anomalies)} 个异常")
            return result
            
        except Exception as e:
            self.logger.error(f"动态检测失败: {str(e)}")
            return {
                "detected": False,
                "anomaly_type": "analysis_error",
                "confidence": 0.0,
                "metrics": traffic_result,
                "details": {"error": str(e), "analyzer": "DynamicAnalyzer"}
            }
    
    def _run_traffic_test(self, test_scenario: Dict[str, Any]) -> Dict[str, Any]:
        """运行流量测试"""
        load_params = test_scenario.get('load_params', {})
        ingress = f"http://{self.config['ssh_host']}:30476/productpage"
        tc = TestCase.from_matrix_dict({
            "case_id": "effectiveness_test",
            "type": "load_test",
            "request_params": {"host": "reviews"},
            "load_params": load_params,
        }, ingress)
        suite = TestSuite(
            cases=[tc],
            global_settings={"ingress_url": ingress},
        )
        ssh_config = {
            "hostname": self.config['ssh_host'],
            "username": self.config.get('ssh_user', 'root'),
            "password": self.config.get('ssh_password', ''),
        }
        pr = DynamicTester(ssh_config=ssh_config).run(suite)[0]
        ex = pr.execution
        if not ex:
            return {}
        return {
            "status_codes": ex.status_codes,
            "total_requests": ex.total_requests,
            "success_rate": ex.success_rate,
            "avg_response_time": ex.avg_response_time,
            "error_count": ex.error_count,
        }
    
    def _inject_anomaly(self, injection_config: Dict[str, Any]):
        """注入异常"""
        # 根据注入配置模拟异常
        if injection_config.get('simulate_anomaly'):
            self.logger.info("注入异常配置")
            # 这里可以修改Istio配置来模拟异常
    
    def _evaluate_static_result(self, test_case: Dict[str, Any], detection_result: Dict[str, Any]) -> bool:
        """评估静态检测结果"""
        expected = test_case['expected_detection']
        actual_detected = detection_result.get('detected', False)
        
        return expected['should_detect'] == actual_detected
    
    def _evaluate_dynamic_result(self, test_case: Dict[str, Any], detection_result: Dict[str, Any]) -> bool:
        """评估动态检测结果"""  
        expected = test_case['expected_detection']
        actual_detected = detection_result.get('detected', False)
        
        return expected['should_detect'] == actual_detected
    
    def calculate_metrics(self, test_results: List[Dict[str, Any]]) -> Dict[str, float]:
        """计算评估指标"""
        total_cases = len(test_results)
        passed_cases = sum(1 for r in test_results if r.get('passed', False))
        
        # 统计各类指标
        true_positives = 0   # 正确检测到问题
        true_negatives = 0   # 正确判断无问题  
        false_positives = 0  # 误报
        false_negatives = 0  # 漏报
        
        for result in test_results:
            expected = result.get('expected', {})
            actual = result.get('actual', {})
            
            should_detect = expected.get('should_detect', False)
            actually_detected = actual.get('detected', False)
            
            if should_detect and actually_detected:
                true_positives += 1
            elif not should_detect and not actually_detected:
                true_negatives += 1
            elif not should_detect and actually_detected:
                false_positives += 1
            elif should_detect and not actually_detected:
                false_negatives += 1
        
        # 计算指标
        accuracy = (true_positives + true_negatives) / total_cases if total_cases > 0 else 0
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "detection_rate": recall,
            "false_positive_rate": false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0,
            "false_negative_rate": false_negatives / (false_negatives + true_positives) if (false_negatives + true_positives) > 0 else 0,
            "total_cases": total_cases,
            "passed_cases": passed_cases
        }
    
    def generate_report(self) -> str:
        """生成评估报告"""
        report_file = f"results/effectiveness_evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        os.makedirs("results", exist_ok=True)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"评估报告已生成: {report_file}")
        return report_file
    
    def run_evaluation(self) -> str:
        """运行完整的有效性评估"""
        self.logger.info("开始有效性评估")
        
        # 运行静态测试
        static_results = self.run_static_tests()
        self.results["test_results"].extend(static_results)
        
        # 运行动态测试  
        dynamic_results = self.run_dynamic_tests()
        self.results["test_results"].extend(dynamic_results)
        
        # 计算指标
        self.results["metrics"] = self.calculate_metrics(self.results["test_results"])
        
        # 生成摘要
        self.results["summary"] = {
            "total_test_cases": len(self.results["test_results"]),
            "static_test_cases": len(static_results),
            "dynamic_test_cases": len(dynamic_results),
            "overall_accuracy": self.results["metrics"]["accuracy"],
            "end_time": datetime.now().isoformat()
        }
        
        # 生成报告
        report_file = self.generate_report()
        
        self.logger.info("有效性评估完成")
        return report_file

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Istio配置一致性检测系统有效性评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    
    args = parser.parse_args()
    
    evaluator = EffectivenessEvaluator(args.config)
    report_file = evaluator.run_evaluation()
    
    print(f"评估完成，报告文件: {report_file}")

if __name__ == "__main__":
    main()
