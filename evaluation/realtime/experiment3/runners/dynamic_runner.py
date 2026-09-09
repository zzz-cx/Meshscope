#!/usr/bin/env python3
"""
Dynamic-only Runner - 仅运行时流量验证
"""

import os
import sys
import json
import time
import asyncio
import aiohttp
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))


class DynamicRunner:
    """动态流量验证器 - 仅进行运行时流量测试"""
    
    def __init__(self, config_path: str):
        """初始化动态运行器"""
        self.config_path = config_path
        self.results = {
            "method": "dynamic_only",
            "start_time": None,
            "end_time": None,
            "traffic_generation_time": 0,
            "validation_time": 0,
            "total_time": 0,
            "traffic_results": [],
            "inconsistencies_found": [],
            "accuracy_metrics": {}
        }
        self.test_endpoints = []
        self.expected_behaviors = {}
    
    async def run(self, config_files: List[str], test_duration: int = 60) -> Dict[str, Any]:
        """运行动态流量验证"""
        start_time = time.time()
        self.results["start_time"] = datetime.now().isoformat()
        
        try:
            # 1. 发现测试端点
            traffic_start = time.time()
            endpoints = await self._discover_endpoints()
            traffic_time = time.time() - traffic_start
            self.results["traffic_generation_time"] = traffic_time
            
            # 2. 生成和执行流量
            validation_start = time.time()
            traffic_results = await self._generate_traffic(endpoints, test_duration)
            validation_time = time.time() - validation_start
            self.results["validation_time"] = validation_time
            
            # 3. 分析流量结果
            inconsistencies = await self._analyze_traffic_results(traffic_results)
            
            # 4. 计算准确性
            self.results["traffic_results"] = traffic_results
            self.results["inconsistencies_found"] = inconsistencies
            self.results["accuracy_metrics"] = self._calculate_accuracy(inconsistencies, config_files)
            
            total_time = time.time() - start_time
            self.results["end_time"] = datetime.now().isoformat()
            self.results["total_time"] = total_time
            
            return self.results
            
        except Exception as e:
            self.results["error"] = str(e)
            self.results["end_time"] = datetime.now().isoformat()
            return self.results
    
    async def _discover_endpoints(self) -> List[Dict[str, Any]]:
        """发现可测试的端点"""
        endpoints = []
        
        try:
            # 通过 kubectl 获取服务
            result = subprocess.run([
                "kubectl", "get", "services", "-o", "json", "--all-namespaces"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                services_data = json.loads(result.stdout)
                for item in services_data.get("items", []):
                    service = item.get("metadata", {})
                    spec = item.get("spec", {})
                    
                    if spec.get("type") == "ClusterIP" or spec.get("type") == "NodePort":
                        for port in spec.get("ports", []):
                            endpoints.append({
                                "name": service.get("name", ""),
                                "namespace": service.get("namespace", "default"),
                                "port": port.get("port", 0),
                                "target_port": port.get("targetPort", 0),
                                "protocol": port.get("protocol", "TCP")
                            })
            
        except Exception as e:
            print(f"Error discovering endpoints: {e}")
            # 使用默认端点作为fallback
            endpoints = [
                {"name": "productpage", "namespace": "default", "port": 9080, "target_port": 9080},
                {"name": "reviews", "namespace": "default", "port": 9080, "target_port": 9080},
                {"name": "ratings", "namespace": "default", "port": 9080, "target_port": 9080}
            ]
        
        return endpoints
    
    async def _generate_traffic(self, endpoints: List[Dict[str, Any]], duration: int) -> List[Dict[str, Any]]:
        """生成测试流量"""
        traffic_results = []
        
        # 创建测试任务
        tasks = []
        for endpoint in endpoints:
            task = self._test_endpoint(endpoint, duration)
            tasks.append(task)
        
        # 并发执行测试
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    traffic_results.append({
                        "endpoint": endpoints[i],
                        "error": str(result),
                        "success": False
                    })
                else:
                    traffic_results.append(result)
        
        return traffic_results
    
    async def _test_endpoint(self, endpoint: Dict[str, Any], duration: int) -> Dict[str, Any]:
        """测试单个端点"""
        start_time = time.time()
        requests_made = 0
        successful_requests = 0
        failed_requests = 0
        response_times = []
        error_codes = {}
        
        # 构建测试URL
        service_url = f"http://{endpoint['name']}.{endpoint['namespace']}.svc.cluster.local:{endpoint['port']}"
        
        timeout = aiohttp.ClientTimeout(total=10)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while time.time() - start_time < duration:
                    request_start = time.time()
                    
                    try:
                        async with session.get(service_url) as response:
                            response_time = time.time() - request_start
                            response_times.append(response_time)
                            
                            requests_made += 1
                            
                            if 200 <= response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                error_codes[response.status] = error_codes.get(response.status, 0) + 1
                    
                    except Exception as e:
                        failed_requests += 1
                        response_times.append(time.time() - request_start)
                        error_codes[f"Exception: {type(e).__name__}"] = error_codes.get(f"Exception: {type(e).__name__}", 0) + 1
                    
                    # 短暂延迟避免过于频繁的请求
                    await asyncio.sleep(0.1)
        
        except Exception as e:
            return {
                "endpoint": endpoint,
                "error": str(e),
                "success": False,
                "requests_made": requests_made,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests
            }
        
        # 计算统计信息
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        success_rate = successful_requests / requests_made if requests_made > 0 else 0
        
        return {
            "endpoint": endpoint,
            "success": True,
            "requests_made": requests_made,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "success_rate": success_rate,
            "average_response_time": avg_response_time,
            "response_times": response_times,
            "error_codes": error_codes,
            "test_duration": duration
        }
    
    async def _analyze_traffic_results(self, traffic_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析流量结果，检测不一致性"""
        inconsistencies = []
        
        for result in traffic_results:
            if not result.get("success", False):
                continue
            
            endpoint = result["endpoint"]
            success_rate = result.get("success_rate", 0)
            avg_response_time = result.get("average_response_time", 0)
            error_codes = result.get("error_codes", {})
            
            # 检测低成功率
            if success_rate < 0.8:  # 80% 成功率阈值
                inconsistencies.append({
                    "type": "low_success_rate",
                    "severity": "error",
                    "endpoint": endpoint["name"],
                    "message": f"Low success rate: {success_rate:.2%}",
                    "details": {
                        "success_rate": success_rate,
                        "total_requests": result.get("requests_made", 0),
                        "failed_requests": result.get("failed_requests", 0)
                    }
                })
            
            # 检测高响应时间
            if avg_response_time > 5.0:  # 5秒响应时间阈值
                inconsistencies.append({
                    "type": "high_response_time",
                    "severity": "warning",
                    "endpoint": endpoint["name"],
                    "message": f"High response time: {avg_response_time:.2f}s",
                    "details": {
                        "average_response_time": avg_response_time,
                        "response_times": result.get("response_times", [])
                    }
                })
            
            # 检测特定错误码
            for error_code, count in error_codes.items():
                if isinstance(error_code, int):
                    if error_code >= 500:  # 服务器错误
                        inconsistencies.append({
                            "type": "server_error",
                            "severity": "error",
                            "endpoint": endpoint["name"],
                            "message": f"Server errors detected: {error_code} ({count} times)",
                            "details": {
                                "error_code": error_code,
                                "count": count,
                                "error_rate": count / result.get("requests_made", 1)
                            }
                        })
                    elif error_code == 404:  # 服务不存在
                        inconsistencies.append({
                            "type": "service_not_found",
                            "severity": "error",
                            "endpoint": endpoint["name"],
                            "message": f"Service not found: 404 errors ({count} times)",
                            "details": {
                                "error_code": 404,
                                "count": count,
                                "error_rate": count / result.get("requests_made", 1)
                            }
                        })
        
        return inconsistencies
    
    def _calculate_accuracy(self, inconsistencies: List[Dict[str, Any]], config_files: List[str]) -> Dict[str, float]:
        """计算准确性指标"""
        # 基于文件名判断是否有已知问题
        has_ground_truth = any("inconsistent" in f or "error" in f for f in config_files)
        expected_issues = 1 if has_ground_truth else 0
        actual_issues = len([i for i in inconsistencies if i.get("severity") == "error"])
        
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
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "expected_issues": expected_issues,
            "actual_issues": actual_issues,
            "false_positives": max(0, actual_issues - expected_issues),
            "false_negatives": max(0, expected_issues - actual_issues)
        }


async def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Dynamic-only Istio流量验证器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--duration", type=int, default=60, help="测试持续时间（秒）")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    runner = DynamicRunner(args.config)
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
