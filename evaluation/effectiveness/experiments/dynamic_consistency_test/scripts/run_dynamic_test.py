#!/usr/bin/env python3
"""
动态一致性检验实验主脚本
"""

import os
import sys
import json
import yaml
import time
import argparse
import asyncio
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests
import numpy as np
import pandas as pd

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))

from traffic_generator import TrafficGenerator
from behavior_analyzer import BehaviorAnalyzer
from config_applier import ConfigApplier
from result_collector import ResultCollector

class DynamicConsistencyTester:
    """动态一致性测试器"""
    
    def __init__(self, config_file: str):
        """初始化测试器"""
        self.config = self._load_config(config_file)
        self.traffic_gen = TrafficGenerator(self.config)
        self.behavior_analyzer = BehaviorAnalyzer(self.config)
        self.config_applier = ConfigApplier(self.config)
        self.result_collector = ResultCollector(self.config)
        
        self.test_results = {
            "experiment_start": datetime.now().isoformat(),
            "scenarios": {},
            "overall_metrics": {},
            "detected_anomalies": []
        }
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载实验配置"""
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def setup_environment(self):
        """设置实验环境"""
        print("🔧 设置实验环境...")
        
        # 检查集群连接
        try:
            result = subprocess.run(["kubectl", "get", "pods", "-n", "default"], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"无法连接到Kubernetes集群: {result.stderr}")
            print("✅ Kubernetes集群连接正常")
        except Exception as e:
            print(f"❌ 集群连接失败: {e}")
            return False
        
        # 检查Istio组件
        try:
            result = subprocess.run(["kubectl", "get", "pods", "-n", "istio-system"], 
                                  capture_output=True, text=True)
            if "istiod" not in result.stdout:
                raise Exception("Istio控制平面未运行")
            print("✅ Istio控制平面正常")
        except Exception as e:
            print(f"❌ Istio检查失败: {e}")
            return False
        
        # 检查测试应用
        app_name = self.config['environment']['cluster_config']['test_app']
        try:
            result = subprocess.run(["kubectl", "get", "pods", "-l", f"app={app_name}"], 
                                  capture_output=True, text=True)
            if app_name not in result.stdout:
                print(f"⚠️  测试应用 {app_name} 未运行，尝试部署...")
                await self._deploy_test_app(app_name)
            else:
                print(f"✅ 测试应用 {app_name} 运行正常")
        except Exception as e:
            print(f"❌ 测试应用检查失败: {e}")
            return False
        
        return True
    
    async def _deploy_test_app(self, app_name: str):
        """部署测试应用"""
        if app_name == "bookinfo":
            # 部署Bookinfo应用
            bookinfo_url = "https://raw.githubusercontent.com/istio/istio/release-1.18/samples/bookinfo/platform/kube/bookinfo.yaml"
            result = subprocess.run(["kubectl", "apply", "-f", bookinfo_url], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Bookinfo部署失败: {result.stderr}")
            
            # 等待Pod就绪
            await asyncio.sleep(30)
            print("✅ Bookinfo应用部署完成")
    
    async def run_scenario(self, scenario_name: str, scenario_config: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个测试场景"""
        print(f"\n🧪 开始场景测试: {scenario_name}")
        
        scenario_result = {
            "name": scenario_name,
            "start_time": datetime.now().isoformat(),
            "config": scenario_config,
            "phases": {},
            "detected_anomalies": [],
            "metrics": {},
            "success": False
        }
        
        try:
            # 阶段1: 应用配置
            print("  📋 阶段1: 应用测试配置")
            phase1_start = time.time()
            
            for config_file in scenario_config['config_files']:
                config_path = Path(__file__).parent.parent / config_file
                await self.config_applier.apply_config(str(config_path))
            
            # 等待配置生效
            await asyncio.sleep(10)
            scenario_result["phases"]["config_application"] = {
                "duration": time.time() - phase1_start,
                "status": "completed"
            }
            
            # 阶段2: 基线测试
            print("  📊 阶段2: 收集基线行为数据")
            phase2_start = time.time()
            
            baseline_duration = 120  # 2分钟基线测试
            await self.traffic_gen.start_traffic(scenario_config['traffic_generation'], baseline_duration)
            
            baseline_data = await self.result_collector.collect_metrics(
                start_time=datetime.now() - timedelta(seconds=baseline_duration),
                duration=baseline_duration
            )
            
            scenario_result["phases"]["baseline_collection"] = {
                "duration": time.time() - phase2_start,
                "status": "completed",
                "data_points": len(baseline_data.get('requests', []))
            }
            
            # 阶段3: 异常注入
            if 'anomaly_injection' in scenario_config:
                print("  💉 阶段3: 注入配置异常")
                phase3_start = time.time()
                
                injection_delay = scenario_config['anomaly_injection'].get('injection_delay', '2m')
                delay_seconds = self._parse_duration(injection_delay)
                await asyncio.sleep(delay_seconds)
                
                await self._inject_anomaly(scenario_config['anomaly_injection'])
                
                scenario_result["phases"]["anomaly_injection"] = {
                    "duration": time.time() - phase3_start,
                    "status": "completed",
                    "injection_type": scenario_config['anomaly_injection']['type']
                }
            
            # 阶段4: 异常期间数据收集
            print("  📈 阶段4: 收集异常期间数据")
            phase4_start = time.time()
            
            anomaly_duration = 180  # 3分钟异常期间测试
            await self.traffic_gen.continue_traffic(anomaly_duration)
            
            anomaly_data = await self.result_collector.collect_metrics(
                start_time=datetime.now() - timedelta(seconds=anomaly_duration),
                duration=anomaly_duration
            )
            
            scenario_result["phases"]["anomaly_data_collection"] = {
                "duration": time.time() - phase4_start,
                "status": "completed",
                "data_points": len(anomaly_data.get('requests', []))
            }
            
            # 阶段5: 行为分析和异常检测
            print("  🔍 阶段5: 分析行为并检测异常")
            phase5_start = time.time()
            
            analysis_result = await self.behavior_analyzer.analyze_behavior_change(
                baseline_data, anomaly_data, scenario_config['expected_detection']
            )
            
            scenario_result["phases"]["behavior_analysis"] = {
                "duration": time.time() - phase5_start,
                "status": "completed"
            }
            
            # 汇总结果
            scenario_result["detected_anomalies"] = analysis_result.get('anomalies', [])
            scenario_result["metrics"] = analysis_result.get('metrics', {})
            scenario_result["success"] = analysis_result.get('detection_success', False)
            
            print(f"  ✅ 场景 {scenario_name} 完成")
            if scenario_result["success"]:
                print(f"    🎯 成功检测到 {len(scenario_result['detected_anomalies'])} 个异常")
            else:
                print(f"    ⚠️  未检测到预期异常")
                
        except Exception as e:
            print(f"  ❌ 场景 {scenario_name} 执行失败: {str(e)}")
            scenario_result["error"] = str(e)
            scenario_result["success"] = False
        
        finally:
            # 清理配置
            await self._cleanup_scenario_config(scenario_config)
            scenario_result["end_time"] = datetime.now().isoformat()
        
        return scenario_result
    
    async def _inject_anomaly(self, injection_config: Dict[str, Any]):
        """注入异常"""
        injection_type = injection_config['type']
        
        if injection_type == "envoy_config_override":
            # 修改Envoy路由配置
            await self._override_envoy_route_config(injection_config)
        elif injection_type == "fault_injection_disable":
            # 禁用故障注入
            await self._disable_fault_injection(injection_config)
        elif injection_type == "rate_limit_bypass":
            # 绕过限流
            await self._bypass_rate_limit(injection_config)
        elif injection_type == "retry_disable":
            # 禁用重试
            await self._disable_retry_policy(injection_config)
        elif injection_type == "circuit_breaker_disable":
            # 禁用熔断器
            await self._disable_circuit_breaker(injection_config)
        elif injection_type == "timeout_disable":
            # 禁用超时
            await self._disable_timeout_policy(injection_config)
    
    async def _override_envoy_route_config(self, injection_config: Dict[str, Any]):
        """覆盖Envoy路由配置以模拟流量分发异常"""
        # 这里需要实现实际的Envoy配置修改逻辑
        # 简化实现：通过修改VirtualService来模拟
        target_dist = injection_config.get('target_distribution', [50, 50])
        
        override_vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": "reviews-traffic-split",
                "namespace": "default"
            },
            "spec": {
                "hosts": ["reviews.default.svc.cluster.local"],
                "http": [{
                    "route": [
                        {
                            "destination": {
                                "host": "reviews.default.svc.cluster.local",
                                "subset": "v1"
                            },
                            "weight": target_dist[0]
                        },
                        {
                            "destination": {
                                "host": "reviews.default.svc.cluster.local", 
                                "subset": "v3"
                            },
                            "weight": target_dist[1]
                        }
                    ]
                }]
            }
        }
        
        # 应用修改后的配置
        temp_file = "/tmp/override_vs.yaml"
        with open(temp_file, 'w') as f:
            yaml.dump(override_vs, f)
        
        subprocess.run(["kubectl", "apply", "-f", temp_file])
        os.remove(temp_file)
        print(f"    🔄 已修改流量分发为 {target_dist}")
    
    async def _disable_fault_injection(self, injection_config: Dict[str, Any]):
        """禁用故障注入"""
        # 移除故障注入配置
        result = subprocess.run([
            "kubectl", "patch", "virtualservice", "productpage-fault-injection", 
            "-n", "default", "--type", "json", 
            "-p", '[{"op": "remove", "path": "/spec/http/0/fault"}]'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("    🚫 已禁用故障注入")
        else:
            print(f"    ❌ 禁用故障注入失败: {result.stderr}")
    
    async def _bypass_rate_limit(self, injection_config: Dict[str, Any]):
        """绕过限流"""
        # 删除限流EnvoyFilter
        subprocess.run([
            "kubectl", "delete", "envoyfilter", "adservice-rate-limit-test", 
            "-n", "online-boutique", "--ignore-not-found"
        ])
        print("    🚫 已绕过限流策略")
    
    async def _disable_retry_policy(self, injection_config: Dict[str, Any]):
        """禁用重试策略"""
        # 移除重试配置
        result = subprocess.run([
            "kubectl", "patch", "virtualservice", "productpage-retry-test",
            "-n", "default", "--type", "json",
            "-p", '[{"op": "remove", "path": "/spec/http/0/retries"}]'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("    🚫 已禁用重试策略")
        else:
            print(f"    ❌ 禁用重试策略失败: {result.stderr}")
    
    async def _disable_circuit_breaker(self, injection_config: Dict[str, Any]):
        """禁用熔断器"""
        # 移除熔断器配置
        result = subprocess.run([
            "kubectl", "patch", "destinationrule", "reviews-circuit-breaker-test",
            "-n", "default", "--type", "json", 
            "-p", '[{"op": "remove", "path": "/spec/trafficPolicy/outlierDetection"}]'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("    🚫 已禁用熔断器")
        else:
            print(f"    ❌ 禁用熔断器失败: {result.stderr}")
    
    async def _disable_timeout_policy(self, injection_config: Dict[str, Any]):
        """禁用超时策略"""
        # 移除超时配置
        result = subprocess.run([
            "kubectl", "patch", "virtualservice", "productpage-timeout-test",
            "-n", "default", "--type", "json",
            "-p", '[{"op": "remove", "path": "/spec/http/0/timeout"}]'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("    🚫 已禁用超时策略")
        else:
            print(f"    ❌ 禁用超时策略失败: {result.stderr}")
    
    async def _cleanup_scenario_config(self, scenario_config: Dict[str, Any]):
        """清理场景配置"""
        print("  🧹 清理场景配置...")
        
        for config_file in scenario_config['config_files']:
            config_path = Path(__file__).parent.parent / config_file
            if config_path.exists():
                result = subprocess.run(["kubectl", "delete", "-f", str(config_path), "--ignore-not-found"],
                                      capture_output=True, text=True)
        
        # 等待清理完成
        await asyncio.sleep(5)
    
    def _parse_duration(self, duration_str: str) -> int:
        """解析时间字符串为秒数"""
        if duration_str.endswith('s'):
            return int(duration_str[:-1])
        elif duration_str.endswith('m'):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith('h'):
            return int(duration_str[:-1]) * 3600
        else:
            return int(duration_str)
    
    def calculate_overall_metrics(self) -> Dict[str, Any]:
        """计算整体评价指标"""
        scenarios = self.test_results["scenarios"]
        total_scenarios = len(scenarios)
        successful_detections = sum(1 for s in scenarios.values() if s.get("success", False))
        
        total_anomalies = sum(len(s.get("detected_anomalies", [])) for s in scenarios.values())
        
        return {
            "total_scenarios": total_scenarios,
            "successful_detections": successful_detections,
            "detection_rate": successful_detections / total_scenarios if total_scenarios > 0 else 0,
            "total_anomalies_detected": total_anomalies,
            "average_detection_time": self._calculate_average_detection_time(),
            "overall_accuracy": self._calculate_overall_accuracy()
        }
    
    def _calculate_average_detection_time(self) -> float:
        """计算平均检测时间"""
        detection_times = []
        for scenario in self.test_results["scenarios"].values():
            if scenario.get("success") and "behavior_analysis" in scenario.get("phases", {}):
                detection_times.append(scenario["phases"]["behavior_analysis"]["duration"])
        
        return np.mean(detection_times) if detection_times else 0
    
    def _calculate_overall_accuracy(self) -> float:
        """计算整体准确性"""
        # 基于成功检测的场景比例
        scenarios = self.test_results["scenarios"]
        if not scenarios:
            return 0
        
        return sum(1 for s in scenarios.values() if s.get("success", False)) / len(scenarios)
    
    def generate_report(self) -> str:
        """生成实验报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = f"results/dynamic_consistency_test_report_{timestamp}.json"
        
        # 计算整体指标
        self.test_results["overall_metrics"] = self.calculate_overall_metrics()
        self.test_results["experiment_end"] = datetime.now().isoformat()
        
        # 确保输出目录存在
        os.makedirs("results", exist_ok=True)
        
        # 写入报告
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.test_results, f, ensure_ascii=False, indent=2)
        
        print(f"\n📊 实验报告已生成: {report_file}")
        return report_file
    
    async def run_all_scenarios(self):
        """运行所有测试场景"""
        scenarios_config = self.config['test_scenarios']
        
        print(f"🚀 开始运行 {len(scenarios_config)} 个测试场景")
        
        for scenario_name, scenario_config in scenarios_config.items():
            scenario_result = await self.run_scenario(scenario_name, scenario_config)
            self.test_results["scenarios"][scenario_name] = scenario_result
            
            # 场景间休息时间
            await asyncio.sleep(30)
        
        print("\n🎉 所有场景测试完成")

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="动态一致性检验实验")
    parser.add_argument("--config", default="experiment_config.yaml", help="实验配置文件")
    parser.add_argument("--scenario", help="运行指定场景")
    parser.add_argument("--setup-only", action="store_true", help="仅设置环境")
    
    args = parser.parse_args()
    
    # 检查配置文件
    config_path = Path(__file__).parent.parent / args.config
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return
    
    # 初始化测试器
    tester = DynamicConsistencyTester(str(config_path))
    
    # 设置环境
    if not await tester.setup_environment():
        print("❌ 环境设置失败，退出实验")
        return
    
    if args.setup_only:
        print("✅ 环境设置完成")
        return
    
    # 运行实验
    if args.scenario:
        # 运行指定场景
        scenario_config = tester.config['test_scenarios'].get(args.scenario)
        if not scenario_config:
            print(f"❌ 场景 {args.scenario} 不存在")
            return
        
        result = await tester.run_scenario(args.scenario, scenario_config)
        tester.test_results["scenarios"][args.scenario] = result
    else:
        # 运行所有场景
        await tester.run_all_scenarios()
    
    # 生成报告
    report_file = tester.generate_report()
    
    # 打印摘要
    overall_metrics = tester.test_results["overall_metrics"]
    print(f"\n📈 实验摘要:")
    print(f"   总场景数: {overall_metrics['total_scenarios']}")
    print(f"   成功检测: {overall_metrics['successful_detections']}")
    print(f"   检测率: {overall_metrics['detection_rate']:.2%}")
    print(f"   检测到的异常: {overall_metrics['total_anomalies_detected']}")
    print(f"   平均检测时间: {overall_metrics['average_detection_time']:.2f}秒")

if __name__ == "__main__":
    asyncio.run(main())
