#!/usr/bin/env python3
"""
配置应用器模块
用于应用和管理Istio配置
"""

import subprocess
import asyncio
import yaml
import tempfile
import os
from typing import Dict, List, Any
import logging

class ConfigApplier:
    """配置应用器"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化配置应用器"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.applied_configs = []  # 记录已应用的配置
    
    async def apply_config(self, config_path: str) -> bool:
        """应用单个配置文件"""
        try:
            self.logger.info(f"应用配置文件: {config_path}")
            
            result = subprocess.run(
                ["kubectl", "apply", "-f", config_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.applied_configs.append(config_path)
                self.logger.info(f"配置应用成功: {config_path}")
                return True
            else:
                self.logger.error(f"配置应用失败: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"应用配置时发生异常: {e}")
            return False
    
    async def apply_configs(self, config_paths: List[str]) -> Dict[str, bool]:
        """批量应用配置文件"""
        results = {}
        
        for config_path in config_paths:
            success = await self.apply_config(config_path)
            results[config_path] = success
            
            # 配置间等待时间
            await asyncio.sleep(2)
        
        return results
    
    async def delete_config(self, config_path: str) -> bool:
        """删除配置"""
        try:
            self.logger.info(f"删除配置: {config_path}")
            
            result = subprocess.run(
                ["kubectl", "delete", "-f", config_path, "--ignore-not-found"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                if config_path in self.applied_configs:
                    self.applied_configs.remove(config_path)
                self.logger.info(f"配置删除成功: {config_path}")
                return True
            else:
                self.logger.warning(f"配置删除警告: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"删除配置时发生异常: {e}")
            return False
    
    async def cleanup_all_configs(self):
        """清理所有已应用的配置"""
        self.logger.info("开始清理所有已应用的配置")
        
        for config_path in reversed(self.applied_configs):  # 反向清理
            await self.delete_config(config_path)
            await asyncio.sleep(1)
        
        self.applied_configs.clear()
        self.logger.info("配置清理完成")
    
    async def apply_dynamic_config(self, config_dict: Dict[str, Any]) -> bool:
        """应用动态生成的配置"""
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                yaml.dump(config_dict, temp_file, default_flow_style=False)
                temp_path = temp_file.name
            
            # 应用配置
            success = await self.apply_config(temp_path)
            
            # 清理临时文件
            os.unlink(temp_path)
            
            return success
            
        except Exception as e:
            self.logger.error(f"应用动态配置失败: {e}")
            return False
    
    async def patch_config(self, resource_type: str, resource_name: str, 
                          namespace: str, patch: str, patch_type: str = "json") -> bool:
        """修补现有配置"""
        try:
            self.logger.info(f"修补配置: {resource_type}/{resource_name}")
            
            cmd = [
                "kubectl", "patch", resource_type, resource_name,
                "-n", namespace, "--type", patch_type, "-p", patch
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info(f"配置修补成功: {resource_type}/{resource_name}")
                return True
            else:
                self.logger.error(f"配置修补失败: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"修补配置时发生异常: {e}")
            return False
    
    async def wait_for_config_propagation(self, timeout: int = 60) -> bool:
        """等待配置传播完成"""
        self.logger.info(f"等待配置传播完成，超时时间: {timeout}秒")
        
        await asyncio.sleep(min(timeout, 30))  # 简化实现，固定等待时间
        
        # 实际实现中应该检查Envoy配置状态
        return True
    
    async def verify_config_applied(self, resource_type: str, resource_name: str, namespace: str) -> bool:
        """验证配置是否成功应用"""
        try:
            result = subprocess.run(
                ["kubectl", "get", resource_type, resource_name, "-n", namespace],
                capture_output=True,
                text=True
            )
            
            return result.returncode == 0
            
        except Exception as e:
            self.logger.error(f"验证配置时发生异常: {e}")
            return False
