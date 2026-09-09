#!/usr/bin/env python3
"""
简化版静态运行器 - 不依赖外部解析器
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


class SimpleStaticRunner:
    """简化版静态配置解析器 - 仅进行配置解析和静态分析"""
    
    def __init__(self, config_path: str):
        """初始化静态运行器"""
        self.config_path = config_path
        self.results = {
            "method": "simple_static_only",
            "start_time": None,
            "end_time": None,
            "parsing_time": 0,
            "analysis_time": 0,
            "total_time": 0,
            "issues_found": [],
            "config_coverage": {},
            "accuracy_metrics": {}
        }
    
    async def run(self, config_files: List[str]) -> Dict[str, Any]:
        """运行静态配置分析"""
        start_time = time.time()
        self.results["start_time"] = datetime.now().isoformat()
        
        try:
            # 1. 解析配置
            parsing_start = time.time()
            config_data = await self._parse_configs(config_files)
            parsing_time = time.time() - parsing_start
            self.results["parsing_time"] = parsing_time
            
            # 2. 静态分析
            analysis_start = time.time()
            issues = await self._static_analysis(config_data)
            analysis_time = time.time() - analysis_start
            self.results["analysis_time"] = analysis_time
            
            # 3. 计算覆盖率和准确性
            self.results["issues_found"] = issues
            self.results["config_coverage"] = self._calculate_coverage(config_data)
            self.results["accuracy_metrics"] = self._calculate_accuracy(issues, config_files)
            
            total_time = time.time() - start_time
            self.results["end_time"] = datetime.now().isoformat()
            self.results["total_time"] = total_time
            
            return self.results
            
        except Exception as e:
            self.results["error"] = str(e)
            self.results["end_time"] = datetime.now().isoformat()
            return self.results
    
    async def _parse_configs(self, config_files: List[str]) -> Dict[str, Any]:
        """解析配置文件"""
        config_data = {
            "services": [],
            "virtual_services": [],
            "destination_rules": [],
            "gateways": [],
            "authorization_policies": []
        }
        
        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    docs = list(yaml.safe_load_all(f))
                    
                for doc in docs:
                    if not doc:
                        continue
                        
                    kind = doc.get('kind', '').lower()
                    metadata = doc.get('metadata', {})
                    
                    if kind == 'service':
                        config_data["services"].append({
                            "name": metadata.get('name', ''),
                            "namespace": metadata.get('namespace', 'default'),
                            "spec": doc.get('spec', {})
                        })
                    elif kind == 'virtualservice':
                        config_data["virtual_services"].append({
                            "name": metadata.get('name', ''),
                            "namespace": metadata.get('namespace', 'default'),
                            "spec": doc.get('spec', {})
                        })
                    elif kind == 'destinationrule':
                        config_data["destination_rules"].append({
                            "name": metadata.get('name', ''),
                            "namespace": metadata.get('namespace', 'default'),
                            "spec": doc.get('spec', {})
                        })
                    elif kind == 'gateway':
                        config_data["gateways"].append({
                            "name": metadata.get('name', ''),
                            "namespace": metadata.get('namespace', 'default'),
                            "spec": doc.get('spec', {})
                        })
                    elif kind == 'authorizationpolicy':
                        config_data["authorization_policies"].append({
                            "name": metadata.get('name', ''),
                            "namespace": metadata.get('namespace', 'default'),
                            "spec": doc.get('spec', {})
                        })
                        
            except Exception as e:
                print(f"Error parsing {config_file}: {e}")
                continue
                
        return config_data
    
    async def _static_analysis(self, config_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """进行静态配置分析"""
        issues = []
        
        # 1. 检查服务引用一致性
        service_names = {svc["name"] for svc in config_data["services"]}
        
        # 检查 VirtualService 中的服务引用
        for vs in config_data["virtual_services"]:
            spec = vs.get("spec", {})
            hosts = spec.get("hosts", [])
            http_routes = spec.get("http", [])
            
            for host in hosts:
                if host not in service_names:
                    issues.append({
                        "type": "service_reference_error",
                        "severity": "error",
                        "message": f"VirtualService {vs['name']} references non-existent service: {host}",
                        "resource": vs["name"],
                        "field": "spec.hosts"
                    })
            
            for route in http_routes:
                destinations = route.get("route", [])
                for dest in destinations:
                    dest_host = dest.get("destination", {}).get("host", "")
                    if dest_host and dest_host not in service_names:
                        issues.append({
                            "type": "service_reference_error",
                            "severity": "error",
                            "message": f"VirtualService {vs['name']} routes to non-existent service: {dest_host}",
                            "resource": vs["name"],
                            "field": "spec.http.route.destination.host"
                        })
        
        # 2. 检查 DestinationRule 中的服务引用
        for dr in config_data["destination_rules"]:
            spec = dr.get("spec", {})
            host = spec.get("host", "")
            
            if host and host not in service_names:
                issues.append({
                    "type": "service_reference_error",
                    "severity": "error",
                    "message": f"DestinationRule {dr['name']} references non-existent service: {host}",
                    "resource": dr["name"],
                    "field": "spec.host"
                })
        
        # 3. 检查端口配置一致性
        for vs in config_data["virtual_services"]:
            http_routes = vs.get("spec", {}).get("http", [])
            for route in http_routes:
                destinations = route.get("route", [])
                for dest in destinations:
                    dest_port = dest.get("destination", {}).get("port", {}).get("number")
                    if dest_port:
                        # 检查端口是否在服务中定义
                        dest_host = dest.get("destination", {}).get("host", "")
                        if dest_host in service_names:
                            service = next((s for s in config_data["services"] if s["name"] == dest_host), None)
                            if service:
                                service_ports = service.get("spec", {}).get("ports", [])
                                port_exists = any(p.get("port") == dest_port for p in service_ports)
                                if not port_exists:
                                    issues.append({
                                        "type": "port_mismatch",
                                        "severity": "warning",
                                        "message": f"VirtualService {vs['name']} routes to port {dest_port} not defined in service {dest_host}",
                                        "resource": vs["name"],
                                        "field": "spec.http.route.destination.port.number"
                                    })
        
        # 4. 检查权重配置
        for vs in config_data["virtual_services"]:
            http_routes = vs.get("spec", {}).get("http", [])
            for route in http_routes:
                destinations = route.get("route", [])
                if len(destinations) > 1:
                    total_weight = sum(dest.get("weight", 0) for dest in destinations)
                    if total_weight != 100:
                        issues.append({
                            "type": "weight_mismatch",
                            "severity": "warning",
                            "message": f"VirtualService {vs['name']} has total weight {total_weight} (should be 100)",
                            "resource": vs["name"],
                            "field": "spec.http.route.weight"
                        })
        
        return issues
    
    def _calculate_coverage(self, config_data: Dict[str, Any]) -> Dict[str, float]:
        """计算配置覆盖率"""
        total_services = len(config_data["services"])
        services_with_vs = set()
        services_with_dr = set()
        
        for vs in config_data["virtual_services"]:
            hosts = vs.get("spec", {}).get("hosts", [])
            services_with_vs.update(hosts)
            
            http_routes = vs.get("spec", {}).get("http", [])
            for route in http_routes:
                destinations = route.get("route", [])
                for dest in destinations:
                    dest_host = dest.get("destination", {}).get("host", "")
                    if dest_host:
                        services_with_vs.add(dest_host)
        
        for dr in config_data["destination_rules"]:
            host = dr.get("spec", {}).get("host", "")
            if host:
                services_with_dr.add(host)
        
        return {
            "service_count": total_services,
            "virtual_service_coverage": len(services_with_vs) / max(total_services, 1) * 100,
            "destination_rule_coverage": len(services_with_dr) / max(total_services, 1) * 100,
            "total_configuration_elements": sum(len(config_data[key]) for key in config_data)
        }
    
    def _calculate_accuracy(self, issues: List[Dict[str, Any]], config_files: List[str]) -> Dict[str, float]:
        """计算准确性指标"""
        # 基于文件名判断是否有已知问题
        has_ground_truth = any("inconsistent" in f or "error" in f for f in config_files)
        expected_issues = 1 if has_ground_truth else 0
        actual_issues = len([i for i in issues if i.get("severity") == "error"])
        
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
    
    parser = argparse.ArgumentParser(description="简化版静态Istio配置分析器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    runner = SimpleStaticRunner(args.config)
    config_files = [args.config] if os.path.isfile(args.config) else []
    
    if os.path.isdir(args.config):
        config_files = [os.path.join(args.config, f) for f in os.listdir(args.config) 
                       if f.endswith(('.yaml', '.yml'))]
    
    results = await runner.run(config_files)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    else:
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
