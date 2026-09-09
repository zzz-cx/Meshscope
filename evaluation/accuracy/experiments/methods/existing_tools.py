#!/usr/bin/env python3
"""
现有工具检测方法实现
调用istioctl analyze, kube-linter等现有工具
"""

import subprocess
import json
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path
import logging
from datetime import datetime
import tempfile
import os

class ExistingToolsDetector:
    """现有工具检测器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化现有工具检测器"""
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 工具配置
        self.tools_config = self.config.get('existing_tools', {})
        self.istioctl_config = self.tools_config.get('istioctl', {})
        self.kube_linter_config = self.tools_config.get('kube_linter', {})
        self.kubeval_config = self.tools_config.get('kubeval', {})
        
        # 工具路径
        self.istioctl_path = self.istioctl_config.get('path', 'istioctl')
        self.kube_linter_path = self.kube_linter_config.get('path', 'kube-linter')
        self.kubeval_path = self.kubeval_config.get('path', 'kubeval')
        
        # 检测规则映射
        self.tool_result_mapping = {
            'istioctl': self._map_istioctl_results,
            'kube_linter': self._map_kube_linter_results,
            'kubeval': self._map_kubeval_results
        }
    
    def detect_faults(self, config_files: List[str]) -> Dict[str, Any]:
        """检测配置文件中的故障"""
        detection_result = {
            "method": "existing_tools",
            "start_time": datetime.now().isoformat(),
            "config_files": config_files,
            "detected_faults": [],
            "tool_results": {},
            "summary": {
                "total_files": len(config_files),
                "files_with_faults": 0,
                "total_faults": 0,
                "fault_types": {},
                "tools_used": []
            }
        }
        
        try:
            # 使用istioctl analyze
            if self.istioctl_config.get('enabled', True):
                istioctl_result = self._run_istioctl_analyze(config_files)
                detection_result["tool_results"]["istioctl"] = istioctl_result
                detection_result["summary"]["tools_used"].append("istioctl")
                
                # 映射istioctl结果
                istioctl_faults = self._map_istioctl_results(istioctl_result, config_files)
                detection_result["detected_faults"].extend(istioctl_faults)
            
            # 使用kube-linter
            if self.kube_linter_config.get('enabled', True):
                kube_linter_result = self._run_kube_linter(config_files)
                detection_result["tool_results"]["kube_linter"] = kube_linter_result
                detection_result["summary"]["tools_used"].append("kube_linter")
                
                # 映射kube-linter结果
                kube_linter_faults = self._map_kube_linter_results(kube_linter_result, config_files)
                detection_result["detected_faults"].extend(kube_linter_faults)
            
            # 使用kubeval
            if self.kubeval_config.get('enabled', True):
                kubeval_result = self._run_kubeval(config_files)
                detection_result["tool_results"]["kubeval"] = kubeval_result
                detection_result["summary"]["tools_used"].append("kubeval")
                
                # 映射kubeval结果
                kubeval_faults = self._map_kubeval_results(kubeval_result, config_files)
                detection_result["detected_faults"].extend(kubeval_faults)
            
            # 去重和合并结果
            detection_result["detected_faults"] = self._deduplicate_faults(detection_result["detected_faults"])
            
            # 计算统计信息
            detection_result["summary"]["files_with_faults"] = len(set(
                fault["config_file"] for fault in detection_result["detected_faults"]
            ))
            detection_result["summary"]["total_faults"] = len(detection_result["detected_faults"])
            
            # 统计故障类型
            for fault in detection_result["detected_faults"]:
                fault_type = fault["fault_type"]
                detection_result["summary"]["fault_types"][fault_type] = \
                    detection_result["summary"]["fault_types"].get(fault_type, 0) + 1
            
        except Exception as e:
            self.logger.error(f"现有工具检测过程中发生错误: {e}")
            detection_result["error"] = str(e)
        
        detection_result["end_time"] = datetime.now().isoformat()
        return detection_result
    
    def _run_istioctl_analyze(self, config_files: List[str]) -> Dict[str, Any]:
        """运行istioctl analyze"""
        self.logger.info("运行istioctl analyze")
        
        result = {
            "tool": "istioctl",
            "command": "analyze",
            "config_files": config_files,
            "output": "",
            "errors": [],
            "warnings": [],
            "success": False
        }
        
        try:
            # 创建临时文件包含所有配置
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                for config_file in config_files:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        temp_file.write(f.read())
                        temp_file.write('\n---\n')
                temp_file_path = temp_file.name
            
            # 运行istioctl analyze
            cmd = [self.istioctl_path, "analyze", temp_file_path, "--output", "json"]
            
            process_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            result["output"] = process_result.stdout
            result["success"] = process_result.returncode == 0
            
            # 解析输出
            if process_result.stdout:
                try:
                    analyze_output = json.loads(process_result.stdout)
                    result["errors"] = analyze_output.get("messages", [])
                except json.JSONDecodeError:
                    # 如果不是JSON格式，解析文本输出
                    result["errors"] = self._parse_istioctl_text_output(process_result.stdout)
            
            if process_result.stderr:
                result["warnings"].append(process_result.stderr)
            
            # 清理临时文件
            os.unlink(temp_file_path)
            
        except subprocess.TimeoutExpired:
            result["errors"].append("istioctl analyze超时")
            self.logger.error("istioctl analyze超时")
        except Exception as e:
            result["errors"].append(f"运行istioctl analyze时发生错误: {e}")
            self.logger.error(f"运行istioctl analyze时发生错误: {e}")
        
        return result
    
    def _parse_istioctl_text_output(self, output: str) -> List[Dict[str, Any]]:
        """解析istioctl文本输出"""
        messages = []
        lines = output.strip().split('\n')
        
        for line in lines:
            if line.strip():
                # 解析消息格式
                if 'Error' in line or 'Warning' in line:
                    message = {
                        "level": "Error" if "Error" in line else "Warning",
                        "message": line.strip(),
                        "resource": "",
                        "namespace": ""
                    }
                    messages.append(message)
        
        return messages
    
    def _run_kube_linter(self, config_files: List[str]) -> Dict[str, Any]:
        """运行kube-linter"""
        self.logger.info("运行kube-linter")
        
        result = {
            "tool": "kube_linter",
            "command": "lint",
            "config_files": config_files,
            "output": "",
            "violations": [],
            "success": False
        }
        
        try:
            # 创建临时文件包含所有配置
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                for config_file in config_files:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        temp_file.write(f.read())
                        temp_file.write('\n---\n')
                temp_file_path = temp_file.name
            
            # 运行kube-linter
            cmd = [self.kube_linter_path, "lint", temp_file_path, "--format", "json"]
            
            process_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            result["output"] = process_result.stdout
            result["success"] = process_result.returncode == 0
            
            # 解析输出
            if process_result.stdout:
                try:
                    lint_output = json.loads(process_result.stdout)
                    result["violations"] = lint_output.get("violations", [])
                except json.JSONDecodeError:
                    # 如果不是JSON格式，解析文本输出
                    result["violations"] = self._parse_kube_linter_text_output(process_result.stdout)
            
            # 清理临时文件
            os.unlink(temp_file_path)
            
        except subprocess.TimeoutExpired:
            result["violations"].append({"message": "kube-linter超时"})
            self.logger.error("kube-linter超时")
        except Exception as e:
            result["violations"].append({"message": f"运行kube-linter时发生错误: {e}"})
            self.logger.error(f"运行kube-linter时发生错误: {e}")
        
        return result
    
    def _parse_kube_linter_text_output(self, output: str) -> List[Dict[str, Any]]:
        """解析kube-linter文本输出"""
        violations = []
        lines = output.strip().split('\n')
        
        for line in lines:
            if line.strip() and ('violation' in line.lower() or 'error' in line.lower()):
                violation = {
                    "message": line.strip(),
                    "resource": "",
                    "namespace": "",
                    "rule": ""
                }
                violations.append(violation)
        
        return violations
    
    def _run_kubeval(self, config_files: List[str]) -> Dict[str, Any]:
        """运行kubeval"""
        self.logger.info("运行kubeval")
        
        result = {
            "tool": "kubeval",
            "command": "validate",
            "config_files": config_files,
            "output": "",
            "errors": [],
            "success": False
        }
        
        try:
            # 创建临时文件包含所有配置
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                for config_file in config_files:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        temp_file.write(f.read())
                        temp_file.write('\n---\n')
                temp_file_path = temp_file.name
            
            # 运行kubeval
            cmd = [self.kubeval_path, temp_file_path, "--output", "json"]
            
            process_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            result["output"] = process_result.stdout
            result["success"] = process_result.returncode == 0
            
            # 解析输出
            if process_result.stdout:
                try:
                    kubeval_output = json.loads(process_result.stdout)
                    result["errors"] = kubeval_output.get("errors", [])
                except json.JSONDecodeError:
                    # 如果不是JSON格式，解析文本输出
                    result["errors"] = self._parse_kubeval_text_output(process_result.stdout)
            
            # 清理临时文件
            os.unlink(temp_file_path)
            
        except subprocess.TimeoutExpired:
            result["errors"].append({"message": "kubeval超时"})
            self.logger.error("kubeval超时")
        except Exception as e:
            result["errors"].append({"message": f"运行kubeval时发生错误: {e}"})
            self.logger.error(f"运行kubeval时发生错误: {e}")
        
        return result
    
    def _parse_kubeval_text_output(self, output: str) -> List[Dict[str, Any]]:
        """解析kubeval文本输出"""
        errors = []
        lines = output.strip().split('\n')
        
        for line in lines:
            if line.strip() and ('error' in line.lower() or 'invalid' in line.lower()):
                error = {
                    "message": line.strip(),
                    "resource": "",
                    "namespace": ""
                }
                errors.append(error)
        
        return errors
    
    def _map_istioctl_results(self, istioctl_result: Dict[str, Any], config_files: List[str]) -> List[Dict[str, Any]]:
        """映射istioctl结果到标准故障格式"""
        faults = []
        
        messages = istioctl_result.get("errors", [])
        
        for message in messages:
            # 解析消息内容
            message_text = message.get("message", "")
            level = message.get("level", "Error")
            resource = message.get("resource", "")
            
            # 确定故障类型
            fault_type = self._determine_fault_type_from_istioctl(message_text)
            
            # 确定配置文件
            config_file = self._determine_config_file_from_resource(resource, config_files)
            
            if fault_type and config_file:
                fault = {
                    "config_file": config_file,
                    "fault_type": fault_type,
                    "severity": "high" if level == "Error" else "medium",
                    "description": message_text,
                    "details": {
                        "tool": "istioctl",
                        "resource": resource,
                        "level": level,
                        "original_message": message_text
                    },
                    "confidence": 0.9 if level == "Error" else 0.7,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _map_kube_linter_results(self, kube_linter_result: Dict[str, Any], config_files: List[str]) -> List[Dict[str, Any]]:
        """映射kube-linter结果到标准故障格式"""
        faults = []
        
        violations = kube_linter_result.get("violations", [])
        
        for violation in violations:
            message = violation.get("message", "")
            resource = violation.get("resource", "")
            rule = violation.get("rule", "")
            
            # 确定故障类型
            fault_type = self._determine_fault_type_from_kube_linter(message, rule)
            
            # 确定配置文件
            config_file = self._determine_config_file_from_resource(resource, config_files)
            
            if fault_type and config_file:
                fault = {
                    "config_file": config_file,
                    "fault_type": fault_type,
                    "severity": "medium",
                    "description": message,
                    "details": {
                        "tool": "kube_linter",
                        "resource": resource,
                        "rule": rule,
                        "original_message": message
                    },
                    "confidence": 0.8,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _map_kubeval_results(self, kubeval_result: Dict[str, Any], config_files: List[str]) -> List[Dict[str, Any]]:
        """映射kubeval结果到标准故障格式"""
        faults = []
        
        errors = kubeval_result.get("errors", [])
        
        for error in errors:
            message = error.get("message", "")
            resource = error.get("resource", "")
            
            # 确定故障类型
            fault_type = self._determine_fault_type_from_kubeval(message)
            
            # 确定配置文件
            config_file = self._determine_config_file_from_resource(resource, config_files)
            
            if fault_type and config_file:
                fault = {
                    "config_file": config_file,
                    "fault_type": fault_type,
                    "severity": "high",
                    "description": message,
                    "details": {
                        "tool": "kubeval",
                        "resource": resource,
                        "original_message": message
                    },
                    "confidence": 0.9,
                    "detection_time": datetime.now().isoformat()
                }
                faults.append(fault)
        
        return faults
    
    def _determine_fault_type_from_istioctl(self, message: str) -> Optional[str]:
        """从istioctl消息确定故障类型"""
        message_lower = message.lower()
        
        if "subset" in message_lower and "not found" in message_lower:
            return "missing_subset"
        elif "weight" in message_lower and ("invalid" in message_lower or "error" in message_lower):
            return "weight_error"
        elif "gateway" in message_lower and "selector" in message_lower:
            return "gateway_selector_error"
        elif "service" in message_lower and "not found" in message_lower:
            return "missing_service_ref"
        elif "routing" in message_lower and ("conflict" in message_lower or "invalid" in message_lower):
            return "routing_conflict"
        elif "fault" in message_lower and "injection" in message_lower:
            return "fault_injection_error"
        elif "rate" in message_lower and "limit" in message_lower:
            return "rate_limit_error"
        elif "retry" in message_lower and ("invalid" in message_lower or "error" in message_lower):
            return "retry_policy_error"
        elif "circuit" in message_lower and "breaker" in message_lower:
            return "circuit_breaker_error"
        elif "timeout" in message_lower and ("invalid" in message_lower or "error" in message_lower):
            return "timeout_error"
        else:
            return "generic_config_error"
    
    def _determine_fault_type_from_kube_linter(self, message: str, rule: str) -> Optional[str]:
        """从kube-linter消息确定故障类型"""
        message_lower = message.lower()
        rule_lower = rule.lower()
        
        if "duplicate" in message_lower or "duplicate" in rule_lower:
            return "duplicate_config"
        elif "security" in message_lower or "security" in rule_lower:
            return "security_config_error"
        elif "resource" in message_lower and "limit" in message_lower:
            return "resource_limit_error"
        elif "label" in message_lower and ("missing" in message_lower or "invalid" in message_lower):
            return "label_config_error"
        else:
            return "generic_config_error"
    
    def _determine_fault_type_from_kubeval(self, message: str) -> Optional[str]:
        """从kubeval消息确定故障类型"""
        message_lower = message.lower()
        
        if "schema" in message_lower and "invalid" in message_lower:
            return "schema_validation_error"
        elif "required" in message_lower and "missing" in message_lower:
            return "missing_required_field"
        elif "type" in message_lower and "invalid" in message_lower:
            return "type_validation_error"
        else:
            return "generic_validation_error"
    
    def _determine_config_file_from_resource(self, resource: str, config_files: List[str]) -> Optional[str]:
        """从资源信息确定配置文件"""
        if not resource:
            return config_files[0] if config_files else None
        
        # 尝试从资源名称匹配配置文件
        resource_lower = resource.lower()
        
        for config_file in config_files:
            config_name = Path(config_file).stem.lower()
            
            # 检查资源是否包含配置文件名
            if config_name in resource_lower:
                return config_file
            
            # 检查常见的资源名称匹配
            if any(keyword in resource_lower for keyword in ["productpage", "reviews", "details", "ratings"]):
                if "productpage" in config_name or "bookinfo" in config_name:
                    return config_file
        
        # 如果无法匹配，返回第一个配置文件
        return config_files[0] if config_files else None
    
    def _deduplicate_faults(self, faults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重故障列表"""
        unique_faults = []
        seen_faults = set()
        
        for fault in faults:
            # 创建故障的唯一标识
            fault_key = (
                fault.get("config_file", ""),
                fault.get("fault_type", ""),
                fault.get("description", "")[:100]  # 只取前100个字符
            )
            
            if fault_key not in seen_faults:
                unique_faults.append(fault)
                seen_faults.add(fault_key)
        
        return unique_faults
