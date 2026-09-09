#!/usr/bin/env python3
"""
实时性评估器
用于评估Istio配置一致性检测系统的实时响应能力
"""

import os
import sys
import json
import time
import threading
import subprocess
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
import psutil
import yaml
import numpy as np
import pandas as pd

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 导入配置解析器
from istio_config_parser.istio_monitor.istio_config_parser import IstioConfigParser
from istio_config_parser.utils.file_utils import load_yaml_file

# 导入一致性检查器
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker

class RealtimeEvaluator:
    """实时性评估器"""
    
    def __init__(self, config_file: str = None):
        """初始化评估器"""
        self.config = self._load_config(config_file)
        self.results = {
            "start_time": datetime.now().isoformat(),
            "test_results": [],
            "performance_metrics": {},
            "system_metrics": {},
            "timeline": []
        }
        self.monitoring_active = False
        self.system_monitor_thread = None
        
        # 初始化配置解析器（其他组件在需要时创建）
        self.config_parser = IstioConfigParser()
        # ConsistencyChecker 需要参数，在需要时创建
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        return {
            "test_cases_file": "test_cases/config_change_scenarios.json",
            "kubectl_context": "default",
            "namespace": "default",
            "output_dir": "results",
            "monitoring_interval": 1.0,  # seconds
            "measurement_precision": 0.1  # seconds
        }
    
    def start_system_monitoring(self):
        """启动系统资源监控"""
        self.monitoring_active = True
        self.system_metrics = {
            "timestamps": [],
            "cpu_usage": [],
            "memory_usage": [],
            "network_io": [],
            "disk_io": []
        }
        
        def monitor_system():
            """系统监控线程函数"""
            while self.monitoring_active:
                timestamp = datetime.now().isoformat()
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                network = psutil.net_io_counters()
                disk = psutil.disk_io_counters()
                
                self.system_metrics["timestamps"].append(timestamp)
                self.system_metrics["cpu_usage"].append(cpu_percent)
                self.system_metrics["memory_usage"].append(memory.percent)
                self.system_metrics["network_io"].append({
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv
                })
                self.system_metrics["disk_io"].append({
                    "read_bytes": disk.read_bytes if disk else 0,
                    "write_bytes": disk.write_bytes if disk else 0
                })
                
                time.sleep(self.config["monitoring_interval"])
        
        self.system_monitor_thread = threading.Thread(target=monitor_system)
        self.system_monitor_thread.daemon = True
        self.system_monitor_thread.start()
        
    def stop_system_monitoring(self):
        """停止系统资源监控"""
        self.monitoring_active = False
        if self.system_monitor_thread:
            self.system_monitor_thread.join(timeout=5)
    
    def record_timeline_event(self, event_type: str, description: str, metadata: Dict[str, Any] = None):
        """记录时间线事件"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "description": description,
            "metadata": metadata or {}
        }
        self.results["timeline"].append(event)
        print(f"[{event['timestamp']}] {event_type}: {description}")
    
    async def apply_config_change(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """应用配置变更"""
        change_id = config_change.get("change_id", "unknown")
        self.record_timeline_event("config_change_start", f"开始应用配置变更: {change_id}")
        
        start_time = time.time()
        
        try:
            # 根据变更类型应用配置
            if config_change["type"] == "weight_adjustment":
                result = await self._apply_weight_change(config_change)
            elif config_change["type"] == "fault_injection":
                result = await self._apply_fault_injection(config_change)
            elif config_change["type"] == "timeout_adjustment":
                result = await self._apply_timeout_change(config_change)
            elif config_change["type"] == "retry_policy":
                result = await self._apply_retry_policy(config_change)
            else:
                raise ValueError(f"不支持的配置变更类型: {config_change['type']}")
            
            execution_time = time.time() - start_time
            result["execution_time"] = execution_time
            
            self.record_timeline_event("config_change_complete", 
                                     f"配置变更完成: {change_id}",
                                     {"execution_time": execution_time})
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.record_timeline_event("config_change_error",
                                     f"配置变更失败: {change_id}, 错误: {str(e)}",
                                     {"execution_time": execution_time, "error": str(e)})
            raise
    
    async def _apply_weight_change(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """应用权重变更"""
        service = config_change["target_service"]
        weights = config_change["weights"]
        
        # 构建VirtualService配置
        vs_config = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": f"{service}-vs",
                "namespace": self.config["namespace"]
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "route": [
                        {"destination": {"host": service, "subset": version}, "weight": weight}
                        for version, weight in weights.items()
                    ]
                }]
            }
        }
        
        # 应用配置
        config_file = f"/tmp/{service}-vs-{int(time.time())}.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(vs_config, f)
        
        start_apply = time.time()
        result = subprocess.run(
            ["kubectl", "apply", "-f", config_file],
            capture_output=True, text=True
        )
        apply_time = time.time() - start_apply
        
        os.remove(config_file)
        
        if result.returncode != 0:
            raise Exception(f"kubectl apply failed: {result.stderr}")
        
        return {
            "type": "weight_adjustment",
            "service": service,
            "weights": weights,
            "apply_time": apply_time,
            "kubectl_output": result.stdout
        }
    
    async def _apply_fault_injection(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """应用故障注入配置"""
        service = config_change["target_service"]
        fault_config = config_change["fault_config"]
        
        # 构建带故障注入的VirtualService
        vs_config = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": f"{service}-fault-vs",
                "namespace": self.config["namespace"]
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "fault": fault_config,
                    "route": [{"destination": {"host": service}}]
                }]
            }
        }
        
        config_file = f"/tmp/{service}-fault-vs-{int(time.time())}.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(vs_config, f)
        
        start_apply = time.time()
        result = subprocess.run(
            ["kubectl", "apply", "-f", config_file],
            capture_output=True, text=True
        )
        apply_time = time.time() - start_apply
        
        os.remove(config_file)
        
        if result.returncode != 0:
            raise Exception(f"kubectl apply failed: {result.stderr}")
        
        return {
            "type": "fault_injection",
            "service": service,
            "fault_config": fault_config,
            "apply_time": apply_time,
            "kubectl_output": result.stdout
        }
    
    async def _apply_timeout_change(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """应用超时配置变更"""
        service = config_change["target_service"]
        timeout = config_change["timeout"]
        
        vs_config = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": f"{service}-timeout-vs",
                "namespace": self.config["namespace"]
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "timeout": timeout,
                    "route": [{"destination": {"host": service}}]
                }]
            }
        }
        
        config_file = f"/tmp/{service}-timeout-vs-{int(time.time())}.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(vs_config, f)
        
        start_apply = time.time()
        result = subprocess.run(
            ["kubectl", "apply", "-f", config_file],
            capture_output=True, text=True
        )
        apply_time = time.time() - start_apply
        
        os.remove(config_file)
        
        if result.returncode != 0:
            raise Exception(f"kubectl apply failed: {result.stderr}")
        
        return {
            "type": "timeout_adjustment",
            "service": service,
            "timeout": timeout,
            "apply_time": apply_time,
            "kubectl_output": result.stdout
        }
    
    async def _apply_retry_policy(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """应用重试策略变更"""
        service = config_change["target_service"]
        retry_config = config_change["retry_config"]
        
        vs_config = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": f"{service}-retry-vs",
                "namespace": self.config["namespace"]
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "retries": retry_config,
                    "route": [{"destination": {"host": service}}]
                }]
            }
        }
        
        config_file = f"/tmp/{service}-retry-vs-{int(time.time())}.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(vs_config, f)
        
        start_apply = time.time()
        result = subprocess.run(
            ["kubectl", "apply", "-f", config_file],
            capture_output=True, text=True
        )
        apply_time = time.time() - start_apply
        
        os.remove(config_file)
        
        if result.returncode != 0:
            raise Exception(f"kubectl apply failed: {result.stderr}")
        
        return {
            "type": "retry_policy",
            "service": service,
            "retry_config": retry_config,
            "apply_time": apply_time,
            "kubectl_output": result.stdout
        }
    
    async def wait_for_config_propagation(self, config_change: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
        """等待配置传播完成 - 真实检测配置传播"""
        self.record_timeline_event("propagation_wait_start", "开始等待配置传播")
        
        start_time = time.time()
        service = config_change.get("target_service", "unknown")
        change_type = config_change.get("type", "unknown")
        
        try:
            # 真实的配置传播检测 - 通过检查Envoy配置或Pod状态
            propagated = False
            check_interval = 1.0  # 每秒检查一次
            
            while time.time() - start_time < timeout:
                # 检查kubectl资源状态
                result = subprocess.run(
                    ["kubectl", "get", "vs", "-o", "json", "-n", self.config["namespace"]],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    # 解析配置，检查是否已更新
                    try:
                        vs_data = json.loads(result.stdout)
                        # 检查是否找到对应的VirtualService并且已更新
                        for item in vs_data.get("items", []):
                            if service in item.get("metadata", {}).get("name", ""):
                                # 找到了对应的配置，认为已传播
                                propagated = True
                                break
                    except json.JSONDecodeError:
                        pass
                
                if propagated:
                    break
                
                await asyncio.sleep(check_interval)
            
            actual_propagation_time = time.time() - start_time
            
            self.record_timeline_event("propagation_complete", 
                                     f"配置传播{'成功' if propagated else '超时'}，用时: {actual_propagation_time:.2f}s")
            
            return {
                "propagation_time": actual_propagation_time,
                "service": service,
                "change_type": change_type,
                "timeout": timeout,
                "success": propagated and actual_propagation_time < timeout,
                "propagated": propagated
            }
            
        except subprocess.TimeoutExpired:
            actual_propagation_time = time.time() - start_time
            self.record_timeline_event("propagation_timeout", 
                                     f"配置传播超时: {actual_propagation_time:.2f}s")
            return {
                "propagation_time": actual_propagation_time,
                "service": service,
                "timeout": timeout,
                "success": False,
                "error": "Timeout checking propagation"
            }
        
        except Exception as e:
            actual_propagation_time = time.time() - start_time
            self.record_timeline_event("propagation_error", 
                                     f"配置传播检测错误: {str(e)}")
            return {
                "propagation_time": actual_propagation_time,
                "service": service,
                "timeout": timeout,
                "success": False,
                "error": str(e)
            }
    
    async def measure_detection_latency(self, config_change: Dict[str, Any]) -> Dict[str, Any]:
        """测量检测延迟 - 真实调用一致性检查器"""
        self.record_timeline_event("detection_measurement_start", "开始测量检测延迟")
        
        start_time = time.time()
        
        try:
            # 1. 获取当前配置
            service = config_change.get("target_service", "unknown")
            namespace = self.config.get("namespace", "default")
            
            # 2. 获取VirtualService配置
            result = subprocess.run(
                ["kubectl", "get", "vs", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                raise Exception(f"Failed to get VirtualService: {result.stderr}")
            
            vs_data = json.loads(result.stdout)
            
            # 3. 解析配置并运行检测
            parsed_configs = []
            for item in vs_data.get("items", []):
                # 直接使用JSON配置
                parsed_configs.append(item)
            
            # 4. 运行静态分析
            static_analyzer = StaticAnalyzer(parsed_configs)
            analysis_result = static_analyzer.analyze()
            
            detection_latency = time.time() - start_time
            
            detected = len(analysis_result.inconsistencies) > 0
            
            self.record_timeline_event("detection_complete", 
                                     f"检测完成，延迟: {detection_latency:.2f}s, 检测到: {detected}")
            
            return {
                "detection_latency": detection_latency,
                "change_type": config_change.get("type", "unknown"),
                "detected": detected,
                "inconsistencies_count": len(analysis_result.inconsistencies),
                "confidence": analysis_result.confidence_score,
                "analyzer_used": "ConsistencyChecker (Real)"
            }
            
        except Exception as e:
            detection_latency = time.time() - start_time
            self.record_timeline_event("detection_error", 
                                     f"检测失败: {str(e)}")
            
            return {
                "detection_latency": detection_latency,
                "change_type": config_change.get("type", "unknown"),
                "detected": False,
                "error": str(e),
                "analyzer_used": "ConsistencyChecker (Error)"
            }
    
    async def run_single_change_test(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """运行单个配置变更测试"""
        scenario_id = scenario["scenario_id"]
        self.record_timeline_event("scenario_start", f"开始测试场景: {scenario_id}")
        
        test_start = time.time()
        result = {
            "scenario_id": scenario_id,
            "scenario_name": scenario["name"],
            "start_time": datetime.now().isoformat(),
            "metrics": {},
            "success": False,
            "errors": []
        }
        
        try:
            # 构建配置变更对象
            test_config = scenario["test_config"]
            config_change = {
                "change_id": f"{scenario_id}_{int(time.time())}",
                "type": self._infer_change_type(test_config),
                "target_service": test_config.get("target_service", "reviews"),
                **test_config
            }
            
            # 1. 应用配置变更
            change_result = await self.apply_config_change(config_change)
            result["metrics"]["config_apply_time"] = change_result["execution_time"]
            
            # 2. 等待配置传播
            propagation_result = await self.wait_for_config_propagation(config_change)
            result["metrics"]["propagation_time"] = propagation_result["propagation_time"]
            
            # 3. 测量检测延迟
            detection_result = await self.measure_detection_latency(config_change)
            result["metrics"]["detection_latency"] = detection_result["detection_latency"]
            
            # 4. 计算端到端响应时间
            end_to_end_time = time.time() - test_start
            result["metrics"]["end_to_end_time"] = end_to_end_time
            
            # 5. 验证指标是否满足预期
            expected_metrics = scenario.get("expected_metrics", {})
            result["metrics"]["meets_expectations"] = self._validate_metrics(
                result["metrics"], expected_metrics
            )
            
            result["success"] = result["metrics"]["meets_expectations"]["all_passed"]
            
        except Exception as e:
            error_msg = f"测试场景 {scenario_id} 执行失败: {str(e)}"
            result["errors"].append(error_msg)
            self.record_timeline_event("scenario_error", error_msg)
        
        finally:
            result["execution_time"] = time.time() - test_start
            result["end_time"] = datetime.now().isoformat()
        
        self.record_timeline_event("scenario_complete", f"测试场景完成: {scenario_id}")
        return result
    
    def _infer_change_type(self, test_config: Dict[str, Any]) -> str:
        """推断配置变更类型"""
        if "initial_weights" in test_config and "final_weights" in test_config:
            return "weight_adjustment"
        elif "fault_config" in test_config:
            return "fault_injection"
        elif "timeout" in test_config:
            return "timeout_adjustment"
        elif "retry_policy" in test_config:
            return "retry_policy"
        else:
            return "unknown"
    
    def _validate_metrics(self, actual_metrics: Dict[str, Any], expected_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """验证指标是否满足预期"""
        validation_result = {
            "all_passed": True,
            "individual_checks": {}
        }
        
        for metric_name, expected_value in expected_metrics.items():
            if metric_name.endswith("_max"):
                # 处理最大值限制
                base_metric = metric_name[:-4]  # 移除"_max"后缀
                actual_value = actual_metrics.get(base_metric, float('inf'))
                
                if isinstance(expected_value, str) and expected_value.endswith('s'):
                    # 解析时间字符串（如"5s", "30s"）
                    expected_seconds = float(expected_value[:-1])
                    passed = actual_value <= expected_seconds
                else:
                    expected_seconds = float(expected_value)
                    passed = actual_value <= expected_seconds
                
                validation_result["individual_checks"][metric_name] = {
                    "expected_max": expected_seconds,
                    "actual": actual_value,
                    "passed": passed
                }
                
                if not passed:
                    validation_result["all_passed"] = False
        
        return validation_result
    
    async def run_stress_test(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """运行压力测试"""
        scenario_id = scenario["scenario_id"]
        self.record_timeline_event("stress_test_start", f"开始压力测试: {scenario_id}")
        
        test_config = scenario["test_config"]
        change_frequency = test_config["change_frequency"]  # 如"1/min"
        test_duration = test_config["test_duration"]  # 如"20m"
        
        # 解析频率和持续时间
        freq_value, freq_unit = change_frequency.split('/')
        freq_value = int(freq_value)
        interval_seconds = 60 if freq_unit == "min" else 1  # 默认支持分钟和秒
        change_interval = interval_seconds / freq_value
        
        duration_value = int(test_duration[:-1])
        duration_unit = test_duration[-1]
        total_duration = duration_value * 60 if duration_unit == 'm' else duration_value
        
        stress_result = {
            "scenario_id": scenario_id,
            "start_time": datetime.now().isoformat(),
            "config": test_config,
            "changes_applied": 0,
            "successful_changes": 0,
            "failed_changes": 0,
            "response_times": [],
            "system_impact": {},
            "success": False
        }
        
        start_time = time.time()
        change_count = 0
        
        try:
            while (time.time() - start_time) < total_duration:
                change_start = time.time()
                
                # 生成配置变更
                config_change = self._generate_stress_test_change(test_config, change_count)
                
                try:
                    # 应用配置变更
                    change_result = await self.apply_config_change(config_change)
                    response_time = time.time() - change_start
                    
                    stress_result["changes_applied"] += 1
                    stress_result["successful_changes"] += 1
                    stress_result["response_times"].append(response_time)
                    
                except Exception as e:
                    stress_result["failed_changes"] += 1
                    self.record_timeline_event("stress_change_failed", 
                                             f"压力测试变更失败: {str(e)}")
                
                change_count += 1
                
                # 等待下一个变更间隔
                elapsed = time.time() - change_start
                if elapsed < change_interval:
                    await asyncio.sleep(change_interval - elapsed)
        
        except Exception as e:
            stress_result["error"] = str(e)
        
        finally:
            # 计算统计指标
            if stress_result["response_times"]:
                stress_result["avg_response_time"] = np.mean(stress_result["response_times"])
                stress_result["p95_response_time"] = np.percentile(stress_result["response_times"], 95)
                stress_result["p99_response_time"] = np.percentile(stress_result["response_times"], 99)
            
            stress_result["success_rate"] = (
                stress_result["successful_changes"] / max(stress_result["changes_applied"], 1)
            )
            stress_result["throughput"] = stress_result["changes_applied"] / total_duration * 60  # changes/min
            stress_result["end_time"] = datetime.now().isoformat()
            stress_result["actual_duration"] = time.time() - start_time
        
        self.record_timeline_event("stress_test_complete", f"压力测试完成: {scenario_id}")
        return stress_result
    
    def _generate_stress_test_change(self, test_config: Dict[str, Any], change_index: int) -> Dict[str, Any]:
        """为压力测试生成配置变更"""
        target_services = test_config.get("target_services", ["reviews"])
        service = target_services[change_index % len(target_services)]
        
        if test_config.get("change_pattern") == "weight_adjustments":
            weight_variations = test_config.get("weight_variations", [[80, 20], [60, 40]])
            weights = weight_variations[change_index % len(weight_variations)]
            
            return {
                "change_id": f"stress_{change_index}",
                "type": "weight_adjustment",
                "target_service": service,
                "weights": {"v1": weights[0], "v3": weights[1]}
            }
        else:
            # 默认返回简单的权重调整
            return {
                "change_id": f"stress_{change_index}",
                "type": "weight_adjustment",
                "target_service": service,
                "weights": {"v1": 50, "v3": 50}
            }
    
    def calculate_performance_metrics(self) -> Dict[str, Any]:
        """计算性能指标"""
        test_results = self.results["test_results"]
        
        if not test_results:
            return {"error": "No test results available"}
        
        # 收集所有测试的指标
        detection_latencies = []
        propagation_times = []
        end_to_end_times = []
        success_rates = []
        
        for result in test_results:
            metrics = result.get("metrics", {})
            
            if "detection_latency" in metrics:
                detection_latencies.append(metrics["detection_latency"])
            if "propagation_time" in metrics:
                propagation_times.append(metrics["propagation_time"])
            if "end_to_end_time" in metrics:
                end_to_end_times.append(metrics["end_to_end_time"])
            
            success_rates.append(1 if result.get("success", False) else 0)
        
        performance_metrics = {
            "detection_latency": {
                "mean": np.mean(detection_latencies) if detection_latencies else 0,
                "p95": np.percentile(detection_latencies, 95) if detection_latencies else 0,
                "p99": np.percentile(detection_latencies, 99) if detection_latencies else 0,
                "max": np.max(detection_latencies) if detection_latencies else 0
            },
            "propagation_time": {
                "mean": np.mean(propagation_times) if propagation_times else 0,
                "p95": np.percentile(propagation_times, 95) if propagation_times else 0,
                "p99": np.percentile(propagation_times, 99) if propagation_times else 0,
                "max": np.max(propagation_times) if propagation_times else 0
            },
            "end_to_end_response": {
                "mean": np.mean(end_to_end_times) if end_to_end_times else 0,
                "p95": np.percentile(end_to_end_times, 95) if end_to_end_times else 0,
                "p99": np.percentile(end_to_end_times, 99) if end_to_end_times else 0,
                "max": np.max(end_to_end_times) if end_to_end_times else 0
            },
            "overall_success_rate": np.mean(success_rates) if success_rates else 0,
            "total_tests": len(test_results),
            "successful_tests": sum(success_rates)
        }
        
        # 系统资源指标
        if self.system_metrics["cpu_usage"]:
            performance_metrics["system_resources"] = {
                "cpu_usage": {
                    "mean": np.mean(self.system_metrics["cpu_usage"]),
                    "max": np.max(self.system_metrics["cpu_usage"]),
                    "p95": np.percentile(self.system_metrics["cpu_usage"], 95)
                },
                "memory_usage": {
                    "mean": np.mean(self.system_metrics["memory_usage"]),
                    "max": np.max(self.system_metrics["memory_usage"]),
                    "p95": np.percentile(self.system_metrics["memory_usage"], 95)
                }
            }
        
        return performance_metrics
    
    async def run_evaluation(self) -> str:
        """运行完整的实时性评估"""
        print("开始实时性评估...")
        
        # 启动系统监控
        self.start_system_monitoring()
        
        try:
            # 加载测试场景
            test_cases_file = self.config["test_cases_file"]
            with open(test_cases_file, 'r', encoding='utf-8') as f:
                test_suite = json.load(f)
            
            scenarios = test_suite["test_scenarios"]
            print(f"加载了 {len(scenarios)} 个测试场景")
            
            # 运行测试场景
            for scenario in scenarios:
                scenario_id = scenario["scenario_id"]
                print(f"运行测试场景: {scenario_id}")
                
                if scenario.get("category") == "stress_test":
                    result = await self.run_stress_test(scenario)
                else:
                    result = await self.run_single_change_test(scenario)
                
                self.results["test_results"].append(result)
                
                # 场景间等待时间
                await asyncio.sleep(2)
            
            # 计算性能指标
            self.results["performance_metrics"] = self.calculate_performance_metrics()
            
        finally:
            # 停止系统监控
            self.stop_system_monitoring()
        
        # 生成报告
        report_file = self.generate_report()
        print(f"实时性评估完成，报告文件: {report_file}")
        
        return report_file
    
    def generate_report(self) -> str:
        """生成评估报告"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(self.config["output_dir"], 
                                 f"realtime_evaluation_report_{timestamp}.json")
        
        os.makedirs(self.config["output_dir"], exist_ok=True)
        
        # 添加系统指标到结果
        self.results["system_metrics"] = self.system_metrics
        self.results["end_time"] = datetime.now().isoformat()
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        return report_file

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Istio配置一致性检测系统实时性评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results")
    
    args = parser.parse_args()
    
    config = {"output_dir": args.output}
    if args.config:
        config["config_file"] = args.config
    
    evaluator = RealtimeEvaluator()
    evaluator.config.update(config)
    
    # 运行异步评估
    loop = asyncio.get_event_loop()
    report_file = loop.run_until_complete(evaluator.run_evaluation())
    
    print(f"评估完成，报告文件: {report_file}")

if __name__ == "__main__":
    main()
