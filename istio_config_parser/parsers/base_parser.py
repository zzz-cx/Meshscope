"""
功能解析器基类
定义统一的解析接口
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from istio_config_parser.models.function_models import (
    FunctionModel, PlaneType, FunctionType
)


class FunctionParser(ABC):
    """功能解析器基类"""
    
    def __init__(self, function_type: FunctionType):
        self.function_type = function_type
    
    @abstractmethod
    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[FunctionModel]:
        """
        解析控制平面配置
        
        Args:
            config: 控制平面配置数据
            context: 上下文信息（如其他相关配置）
            
        Returns:
            功能模型列表
        """
        pass
    
    @abstractmethod
    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[FunctionModel]:
        """
        解析数据平面配置
        
        Args:
            config: 数据平面配置数据
            context: 上下文信息
            
        Returns:
            功能模型列表
        """
        pass
    
    def _extract_namespace_and_service(self, config: Dict[str, Any]) -> tuple:
        """提取命名空间和服务名"""
        metadata = config.get('metadata', {})
        namespace = metadata.get('namespace', 'default')
        name = metadata.get('name', 'unknown')
        return namespace, name
    
    def _get_labels(self, config: Dict[str, Any]) -> Dict[str, str]:
        """提取标签"""
        return config.get('metadata', {}).get('labels', {})
    
    def _get_annotations(self, config: Dict[str, Any]) -> Dict[str, str]:
        """提取注解"""
        return config.get('metadata', {}).get('annotations', {})


class ParserRegistry:
    """解析器注册表"""
    
    def __init__(self):
        self._parsers: Dict[FunctionType, FunctionParser] = {}
    
    def register(self, function_type: FunctionType, parser: FunctionParser):
        """注册解析器"""
        self._parsers[function_type] = parser
    
    def get_parser(self, function_type: FunctionType) -> Optional[FunctionParser]:
        """获取解析器"""
        return self._parsers.get(function_type)
    
    def get_all_parsers(self) -> Dict[FunctionType, FunctionParser]:
        """获取所有解析器"""
        return self._parsers.copy()
    
    def parse_control_plane_all(self, configs: Dict[str, Any]) -> Dict[str, List[FunctionModel]]:
        """
        使用所有解析器解析控制平面配置
        
        Returns:
            {function_type: [models]}
        """
        results = {}
        for func_type, parser in self._parsers.items():
            try:
                models = parser.parse_control_plane(configs)
                if models:
                    results[func_type.value] = models
            except Exception as e:
                print(f"解析 {func_type.value} 控制平面配置时出错: {str(e)}")
        return results
    
    def parse_data_plane_all(self, configs: Dict[str, Any]) -> Dict[str, List[FunctionModel]]:
        """
        使用所有解析器解析数据平面配置
        
        Returns:
            {function_type: [models]}
        """
        results = {}
        for func_type, parser in self._parsers.items():
            try:
                models = parser.parse_data_plane(configs)
                if models:
                    results[func_type.value] = models
            except Exception as e:
                print(f"解析 {func_type.value} 数据平面配置时出错: {str(e)}")
        return results


# 全局解析器注册表
global_parser_registry = ParserRegistry()

