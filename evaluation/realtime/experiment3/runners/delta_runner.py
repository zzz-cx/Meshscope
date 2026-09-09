#!/usr/bin/env python3
"""
Delta/Incremental Static Runner - 仅对受影响的配置子图进行增量检查
"""

import os
import sys
import json
import time
import asyncio
import yaml
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.append(str(project_root))

from runners.static_runner import StaticRunner


class DeltaRunner:
    """增量静态分析器 - 仅分析受影响的配置部分"""
    
    def __init__(self, config_path: str):
        """初始化增量运行器"""
        self.config_path = config_path
        self.static_runner = StaticRunner(config_path)
        self.results = {
            "method": "delta_incremental",
            "start_time": None,
            "end_time": None,
            "change_detection_time": 0,
            "incremental_analysis_time": 0,
            "total_time": 0,
            "changed_resources": [],
            "issues_found": [],
            "accuracy_metrics": {}
        }
        self.previous_config_hash = None
        self.dependency_graph = {}
    
    async def run(self, config_files: List[str]) -> Dict[str, Any]:
        """运行增量分析"""
        start_time = time.time()
        self.results["start_time"] = datetime.now().isoformat()
        
        try:
            # 1. 检测配置变更
            change_start = time.time()
            changed_resources = await self._detect_changes(config_files)
            change_time = time.time() - change_start
            self.results["change_detection_time"] = change_time
            self.results["changed_resources"] = changed_resources
            
            # 2. 增量分析
            analysis_start = time.time()
            if changed_resources:
                issues = await self._incremental_analysis(config_files, changed_resources)
            else:
                issues = []
            analysis_time = time.time() - analysis_start
            self.results["incremental_analysis_time"] = analysis_time
            self.results["issues_found"] = issues
            
            # 3. 计算准确性
            self.results["accuracy_metrics"] = self._calculate_accuracy(issues, config_files)
            
            total_time = time.time() - start_time
            self.results["end_time"] = datetime.now().isoformat()
            self.results["total_time"] = total_time
            
            return self.results
            
        except Exception as e:
            self.results["error"] = str(e)
            self.results["end_time"] = datetime.now().isoformat()
            return self.results
    
    async def _detect_changes(self, config_files: List[str]) -> List[Dict[str, Any]]:
        """检测配置变更"""
        changed_resources = []
        
        for config_file in config_files:
            try:
                # 计算文件哈希
                current_hash = self._calculate_file_hash(config_file)
                
                # 检查是否有变更
                if self.previous_config_hash and current_hash != self.previous_config_hash.get(config_file):
                    # 解析变更的资源
                    changed_in_file = await self._parse_changed_resources(config_file)
                    changed_resources.extend(changed_in_file)
                
                # 更新哈希记录
                if not self.previous_config_hash:
                    self.previous_config_hash = {}
                self.previous_config_hash[config_file] = current_hash
                
            except Exception as e:
                print(f"Error detecting changes in {config_file}: {e}")
                continue
        
        return changed_resources
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件哈希值"""
        import hashlib
        
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                return hashlib.md5(content).hexdigest()
        except Exception as e:
            print(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    async def _parse_changed_resources(self, config_file: str) -> List[Dict[str, Any]]:
        """解析变更的资源"""
        changed_resources = []
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                docs = list(yaml.safe_load_all(f))
            
            for doc in docs:
                if not doc:
                    continue
                
                metadata = doc.get('metadata', {})
                kind = doc.get('kind', '')
                
                resource = {
                    "file": config_file,
                    "kind": kind,
                    "name": metadata.get('name', ''),
                    "namespace": metadata.get('namespace', 'default'),
                    "change_type": "modified"  # 简化假设为修改
                }
                
                changed_resources.append(resource)
                
        except Exception as e:
            print(f"Error parsing changed resources in {config_file}: {e}")
        
        return changed_resources
    
    async def _incremental_analysis(self, config_files: List[str], 
                                  changed_resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """增量分析变更的资源"""
        issues = []
        
        # 构建依赖图（如果还没有）
        if not self.dependency_graph:
            self.dependency_graph = await self._build_dependency_graph(config_files)
        
        # 分析每个变更的资源及其依赖
        for resource in changed_resources:
            # 分析直接变更的资源
            direct_issues = await self._analyze_resource(resource, config_files)
            issues.extend(direct_issues)
            
            # 分析受影响的依赖资源
            affected_resources = self._find_affected_resources(resource)
            for affected in affected_resources:
                affected_issues = await self._analyze_resource(affected, config_files)
                issues.extend(affected_issues)
        
        return issues
    
    async def _build_dependency_graph(self, config_files: List[str]) -> Dict[str, Set[str]]:
        """构建资源依赖图"""
        graph = {}
        
        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    docs = list(yaml.safe_load_all(f))
                
                for doc in docs:
                    if not doc:
                        continue
                    
                    metadata = doc.get('metadata', {})
                    kind = doc.get('kind', '')
                    name = metadata.get('name', '')
                    
                    if not name:
                        continue
                    
                    resource_key = f"{kind}/{name}"
                    graph[resource_key] = set()
                    
                    # 分析依赖关系
                    dependencies = self._extract_dependencies(doc)
                    graph[resource_key].update(dependencies)
                    
            except Exception as e:
                print(f"Error building dependency graph for {config_file}: {e}")
                continue
        
        return graph
    
    def _extract_dependencies(self, doc: Dict[str, Any]) -> List[str]:
        """提取资源配置的依赖"""
        dependencies = []
        spec = doc.get('spec', {})
        kind = doc.get('kind', '')
        
        if kind == 'VirtualService':
            # VirtualService依赖目标服务
            hosts = spec.get('hosts', [])
            dependencies.extend([f"Service/{host}" for host in hosts])
            
            http_routes = spec.get('http', [])
            for route in http_routes:
                destinations = route.get('route', [])
                for dest in destinations:
                    dest_host = dest.get('destination', {}).get('host', '')
                    if dest_host:
                        dependencies.append(f"Service/{dest_host}")
        
        elif kind == 'DestinationRule':
            # DestinationRule依赖目标服务
            host = spec.get('host', '')
            if host:
                dependencies.append(f"Service/{host}")
        
        elif kind == 'Gateway':
            # Gateway依赖服务
            servers = spec.get('servers', [])
            for server in servers:
                hosts = server.get('hosts', [])
                dependencies.extend([f"Service/{host}" for host in hosts if host != '*'])
        
        return dependencies
    
    def _find_affected_resources(self, changed_resource: Dict[str, Any]) -> List[Dict[str, Any]]:
        """查找受影响的资源"""
        affected = []
        resource_key = f"{changed_resource['kind']}/{changed_resource['name']}"
        
        # 查找依赖该资源的其他资源
        for dependent_key, dependencies in self.dependency_graph.items():
            if resource_key in dependencies:
                kind, name = dependent_key.split('/', 1)
                affected.append({
                    "kind": kind,
                    "name": name,
                    "dependency_type": "dependent"
                })
        
        return affected
    
    async def _analyze_resource(self, resource: Dict[str, Any], 
                              config_files: List[str]) -> List[Dict[str, Any]]:
        """分析单个资源"""
        issues = []
        
        # 简化实现：复用静态分析器的逻辑
        # 实际实现中应该只分析特定资源
        try:
            # 查找包含该资源的配置文件
            resource_file = None
            for config_file in config_files:
                if self._resource_in_file(resource, config_file):
                    resource_file = config_file
                    break
            
            if resource_file:
                # 运行静态分析（仅对该文件）
                static_result = await self.static_runner.run([resource_file])
                resource_issues = static_result.get("issues_found", [])
                
                # 过滤出与该资源相关的问题
                for issue in resource_issues:
                    if (issue.get("resource") == resource["name"] or 
                        issue.get("resource") == f"{resource['kind']}/{resource['name']}"):
                        issues.append(issue)
        
        except Exception as e:
            print(f"Error analyzing resource {resource}: {e}")
        
        return issues
    
    def _resource_in_file(self, resource: Dict[str, Any], config_file: str) -> bool:
        """检查资源是否在指定文件中"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            return (resource["kind"] in content and 
                   resource["name"] in content)
        
        except Exception as e:
            print(f"Error checking resource in file {config_file}: {e}")
            return False
    
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
    
    parser = argparse.ArgumentParser(description="Delta/Incremental Istio配置分析器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    runner = DeltaRunner(args.config)
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
