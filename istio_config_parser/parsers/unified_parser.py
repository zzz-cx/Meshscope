"""
统一解析管道（Unified Parsing Pipeline）
整合所有解析器，提供统一的解析接口
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import ParserRegistry, global_parser_registry
from istio_config_parser.parsers.routing_parser import RoutingParser
from istio_config_parser.parsers.circuit_breaker_parser import CircuitBreakerParser
from istio_config_parser.parsers.ratelimit_parser import RateLimitParser
from istio_config_parser.parsers.traffic_shifting_parser import TrafficShiftingParser
from istio_config_parser.models.function_models import (
    FunctionType, AnyFunctionModel
)
from istio_config_parser.models.alignment_models import (
    ModelAligner, AlignmentResult
)
from istio_config_parser.models.ir_models import (
    IRBuilder, SystemIR
)
from istio_config_parser.parsers.model_exporter import ModelExporter

logger = logging.getLogger(__name__)


class UnifiedParser:
    """统一解析器"""
    
    def __init__(self):
        self.registry = ParserRegistry()
        self._register_default_parsers()
    
    def _register_default_parsers(self):
        """注册默认解析器"""
        self.registry.register(FunctionType.ROUTING, RoutingParser())
        self.registry.register(FunctionType.CIRCUIT_BREAKER, CircuitBreakerParser())
        self.registry.register(FunctionType.RATE_LIMIT, RateLimitParser())
        self.registry.register(FunctionType.TRAFFIC_SHIFTING, TrafficShiftingParser())
        # 可以继续注册其他解析器
    
    def parse_control_plane(
        self,
        services_config: Dict[str, Any],
        virtual_services_config: Dict[str, Any],
        destination_rules_config: Dict[str, Any],
        envoy_filters_config: Dict[str, Any],
        **kwargs
    ) -> Dict[str, List[AnyFunctionModel]]:
        """
        解析控制平面配置
        
        Args:
            services_config: Service配置
            virtual_services_config: VirtualService配置
            destination_rules_config: DestinationRule配置
            envoy_filters_config: EnvoyFilter配置
            
        Returns:
            {function_type: [models]}
        """
        results = {}
        
        # 路由解析
        routing_parser = self.registry.get_parser(FunctionType.ROUTING)
        if routing_parser:
            try:
                routing_models = routing_parser.parse_control_plane(virtual_services_config)
                if routing_models:
                    results[FunctionType.ROUTING.value] = routing_models
                    logger.info(f"解析到 {len(routing_models)} 个路由配置")
            except Exception as e:
                logger.error(f"解析路由配置失败: {str(e)}")
        
        # 熔断解析
        circuit_breaker_parser = self.registry.get_parser(FunctionType.CIRCUIT_BREAKER)
        if circuit_breaker_parser:
            try:
                cb_models = circuit_breaker_parser.parse_control_plane(destination_rules_config)
                if cb_models:
                    results[FunctionType.CIRCUIT_BREAKER.value] = cb_models
                    logger.info(f"解析到 {len(cb_models)} 个熔断配置")
            except Exception as e:
                logger.error(f"解析熔断配置失败: {str(e)}")
        
        # 限流解析
        ratelimit_parser = self.registry.get_parser(FunctionType.RATE_LIMIT)
        if ratelimit_parser:
            try:
                rl_models = ratelimit_parser.parse_control_plane(envoy_filters_config)
                if rl_models:
                    results[FunctionType.RATE_LIMIT.value] = rl_models
                    logger.info(f"解析到 {len(rl_models)} 个限流配置")
            except Exception as e:
                logger.error(f"解析限流配置失败: {str(e)}")
        
        # 流量迁移解析
        traffic_shifting_parser = self.registry.get_parser(FunctionType.TRAFFIC_SHIFTING)
        if traffic_shifting_parser:
            try:
                # 流量迁移需要同时解析DR和VS
                combined_config = {
                    'destination_rules': destination_rules_config,
                    'virtual_services': virtual_services_config
                }
                ts_models = traffic_shifting_parser.parse_control_plane(combined_config)
                if ts_models:
                    results[FunctionType.TRAFFIC_SHIFTING.value] = ts_models
                    logger.info(f"解析到 {len(ts_models)} 个流量迁移配置")
            except Exception as e:
                logger.error(f"解析流量迁移配置失败: {str(e)}")
        
        return results
    
    def parse_data_plane(
        self,
        routes_config: Any,
        clusters_config: Any,
        listeners_config: Any,
        **kwargs
    ) -> Dict[str, List[AnyFunctionModel]]:
        """
        解析数据平面配置
        
        Args:
            routes_config: Envoy路由配置
            clusters_config: Envoy集群配置
            listeners_config: Envoy监听器配置
            
        Returns:
            {function_type: [models]}
        """
        results = {}
        
        # 路由解析
        routing_parser = self.registry.get_parser(FunctionType.ROUTING)
        if routing_parser and routes_config:
            try:
                routing_models = routing_parser.parse_data_plane(routes_config)
                if routing_models:
                    results[FunctionType.ROUTING.value] = routing_models
                    logger.info(f"解析到 {len(routing_models)} 个数据平面路由配置")
            except Exception as e:
                logger.error(f"解析数据平面路由配置失败: {str(e)}")
        
        # 熔断解析
        circuit_breaker_parser = self.registry.get_parser(FunctionType.CIRCUIT_BREAKER)
        if circuit_breaker_parser and clusters_config:
            try:
                cb_models = circuit_breaker_parser.parse_data_plane(clusters_config)
                if cb_models:
                    results[FunctionType.CIRCUIT_BREAKER.value] = cb_models
                    logger.info(f"解析到 {len(cb_models)} 个数据平面熔断配置")
            except Exception as e:
                logger.error(f"解析数据平面熔断配置失败: {str(e)}")
        
        # 限流解析
        ratelimit_parser = self.registry.get_parser(FunctionType.RATE_LIMIT)
        if ratelimit_parser and listeners_config:
            try:
                rl_models = ratelimit_parser.parse_data_plane(listeners_config)
                if rl_models:
                    results[FunctionType.RATE_LIMIT.value] = rl_models
                    logger.info(f"解析到 {len(rl_models)} 个数据平面限流配置")
            except Exception as e:
                logger.error(f"解析数据平面限流配置失败: {str(e)}")
        
        # 流量迁移解析
        traffic_shifting_parser = self.registry.get_parser(FunctionType.TRAFFIC_SHIFTING)
        if traffic_shifting_parser and routes_config:
            try:
                ts_models = traffic_shifting_parser.parse_data_plane(routes_config)
                if ts_models:
                    results[FunctionType.TRAFFIC_SHIFTING.value] = ts_models
                    logger.info(f"解析到 {len(ts_models)} 个数据平面流量迁移配置")
            except Exception as e:
                logger.error(f"解析数据平面流量迁移配置失败: {str(e)}")
        
        return results
    
    def parse_and_align(
        self,
        control_plane_configs: Dict[str, Any],
        data_plane_configs: Dict[str, Any]
    ) -> AlignmentResult:
        """
        解析并对齐控制平面和数据平面配置
        
        Args:
            control_plane_configs: 控制平面配置字典，包含:
                - services
                - virtual_services
                - destination_rules
                - envoy_filters
            data_plane_configs: 数据平面配置字典，包含:
                - routes
                - clusters
                - listeners
                
        Returns:
            对齐结果
        """
        # 解析控制平面
        logger.info("开始解析控制平面配置...")
        cp_models = self.parse_control_plane(
            services_config=control_plane_configs.get('services', {}),
            virtual_services_config=control_plane_configs.get('virtual_services', {}),
            destination_rules_config=control_plane_configs.get('destination_rules', {}),
            envoy_filters_config=control_plane_configs.get('envoy_filters', {})
        )
        
        # 解析数据平面
        logger.info("开始解析数据平面配置...")
        dp_models = self.parse_data_plane(
            routes_config=data_plane_configs.get('routes'),
            clusters_config=data_plane_configs.get('clusters'),
            listeners_config=data_plane_configs.get('listeners')
        )
        
        # 对齐模型
        logger.info("开始对齐配置...")
        aligner = ModelAligner()
        aligned_pairs = aligner.align(cp_models, dp_models)
        
        logger.info(f"对齐完成，共 {len(aligned_pairs)} 对配置")
        logger.info(f"对齐摘要: {aligner.get_summary()}")
        
        return AlignmentResult(aligner=aligner)
    
    def parse_align_and_build_ir(
        self,
        control_plane_configs: Dict[str, Any],
        data_plane_configs: Dict[str, Any]
    ) -> SystemIR:
        """
        完整的解析、对齐和构建IR流程
        
        Args:
            control_plane_configs: 控制平面配置
            data_plane_configs: 数据平面配置
            
        Returns:
            系统级IR
        """
        # 解析并对齐
        alignment_result = self.parse_and_align(control_plane_configs, data_plane_configs)
        
        # 构建IR
        logger.info("开始构建中间表示（IR）...")
        system_ir = IRBuilder.build_from_aligned_pairs(alignment_result.get_all_pairs())
        
        logger.info(f"IR构建完成")
        logger.info(f"系统摘要: {system_ir.get_summary()}")
        
        return system_ir
    
    def parse_and_export(
        self,
        control_plane_configs: Dict[str, Any],
        data_plane_configs: Dict[str, Any],
        output_dir: str = "models_output"
    ) -> Dict[str, str]:
        """
        解析配置并导出独立的建模文件
        
        Args:
            control_plane_configs: 控制平面配置
            data_plane_configs: 数据平面配置
            output_dir: 输出目录
            
        Returns:
            导出文件路径字典
        """
        # 解析控制平面
        logger.info("开始解析控制平面配置...")
        cp_models = self.parse_control_plane(
            services_config=control_plane_configs.get('services', {}),
            virtual_services_config=control_plane_configs.get('virtual_services', {}),
            destination_rules_config=control_plane_configs.get('destination_rules', {}),
            envoy_filters_config=control_plane_configs.get('envoy_filters', {})
        )
        
        # 解析数据平面
        logger.info("开始解析数据平面配置...")
        dp_models = self.parse_data_plane(
            routes_config=data_plane_configs.get('routes'),
            clusters_config=data_plane_configs.get('clusters'),
            listeners_config=data_plane_configs.get('listeners')
        )
        
        # 导出模型
        logger.info(f"开始导出建模文件到: {output_dir}")
        exported_files = ModelExporter.export_models(cp_models, dp_models, output_dir)
        
        # 同时导出可视化数据
        viz_file = ModelExporter.export_for_visualization(
            cp_models, dp_models,
            output_file=f"{output_dir}/visualization_data.json"
        )
        exported_files['visualization_file'] = viz_file
        
        logger.info("建模文件导出完成")
        return exported_files


# 全局统一解析器实例
global_unified_parser = UnifiedParser()

