"""
统一解析管道（Unified Parsing Pipeline）
整合所有解析器，提供统一的解析接口
"""
import logging
import concurrent.futures
import threading
import os
from typing import Dict, List, Any, Optional, Callable, Tuple
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
    
    def __init__(self, enable_parallel: bool = True, max_workers: Optional[int] = None):
        """
        初始化统一解析器
        
        Args:
            enable_parallel: 是否启用并行处理
            max_workers: 最大工作线程数，None表示使用CPU核心数
        """
        self.registry = ParserRegistry()
        self.enable_parallel = enable_parallel
        self.max_workers = max_workers or min(32, os.cpu_count() + 4 if os.cpu_count() else 8)
        self._register_default_parsers()
        logger.info(f"统一解析器初始化完成，并行处理: {enable_parallel}, 最大工作线程: {self.max_workers}")
    
    def _register_default_parsers(self):
        """注册默认解析器"""
        self.registry.register(FunctionType.ROUTING, RoutingParser())
        self.registry.register(FunctionType.CIRCUIT_BREAKER, CircuitBreakerParser())
        self.registry.register(FunctionType.RATE_LIMIT, RateLimitParser())
        self.registry.register(FunctionType.TRAFFIC_SHIFTING, TrafficShiftingParser())
        # 可以继续注册其他解析器
    
    def _parse_control_plane_parser_task(
        self, 
        func_type: FunctionType, 
        config_data: Dict[str, Any], 
        task_name: str
    ) -> Tuple[str, List[AnyFunctionModel], Optional[Exception]]:
        """
        单个解析器任务的包装函数，用于并行执行
        
        Args:
            func_type: 功能类型
            config_data: 配置数据
            task_name: 任务名称（用于日志）
            
        Returns:
            (function_type, models, error)
        """
        try:
            parser = self.registry.get_parser(func_type)
            if not parser:
                return func_type.value, [], None
            
            if func_type == FunctionType.ROUTING:
                models = parser.parse_control_plane(config_data)
            elif func_type == FunctionType.CIRCUIT_BREAKER:
                models = parser.parse_control_plane(config_data)
            elif func_type == FunctionType.RATE_LIMIT:
                models = parser.parse_control_plane(config_data)
            elif func_type == FunctionType.TRAFFIC_SHIFTING:
                # 流量迁移需要特殊处理
                combined_config = {
                    'destination_rules': config_data.get('destination_rules', {}),
                    'virtual_services': config_data.get('virtual_services', {})
                }
                models = parser.parse_control_plane(combined_config)
            else:
                models = []
            
            logger.info(f"[并行] {task_name}: 解析到 {len(models)} 个配置")
            return func_type.value, models or [], None
            
        except Exception as e:
            logger.error(f"[并行] {task_name}: 解析失败 - {str(e)}")
            return func_type.value, [], e
    
    def _parse_data_plane_parser_task(
        self, 
        func_type: FunctionType, 
        config_data: Dict[str, Any], 
        task_name: str
    ) -> Tuple[str, List[AnyFunctionModel], Optional[Exception]]:
        """
        单个数据平面解析器任务的包装函数，用于并行执行
        
        Args:
            func_type: 功能类型
            config_data: 配置数据
            task_name: 任务名称（用于日志）
            
        Returns:
            (function_type, models, error)
        """
        try:
            parser = self.registry.get_parser(func_type)
            if not parser:
                return func_type.value, [], None
            
            models = []
            if func_type == FunctionType.ROUTING and config_data.get('routes'):
                models = parser.parse_data_plane(config_data['routes'])
            elif func_type == FunctionType.CIRCUIT_BREAKER and config_data.get('clusters'):
                models = parser.parse_data_plane(config_data['clusters'])
            elif func_type == FunctionType.RATE_LIMIT and config_data.get('listeners'):
                models = parser.parse_data_plane(config_data['listeners'])
            elif func_type == FunctionType.TRAFFIC_SHIFTING and config_data.get('routes'):
                models = parser.parse_data_plane(config_data['routes'])
            
            logger.info(f"[并行] {task_name}: 解析到 {len(models)} 个数据平面配置")
            return func_type.value, models or [], None
            
        except Exception as e:
            logger.error(f"[并行] {task_name}: 解析失败 - {str(e)}")
            return func_type.value, [], e
    
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
        if not self.enable_parallel:
            # 串行处理（原有逻辑）
            return self._parse_control_plane_serial(
                services_config, virtual_services_config, 
                destination_rules_config, envoy_filters_config
            )
        
        # 并行处理
        logger.info("[并行] 开始并行解析控制平面配置...")
        results = {}
        tasks = []
        
        # 准备任务数据
        config_data = {
            FunctionType.ROUTING: virtual_services_config,
            FunctionType.CIRCUIT_BREAKER: destination_rules_config,
            FunctionType.RATE_LIMIT: envoy_filters_config,
            FunctionType.TRAFFIC_SHIFTING: {
                'destination_rules': destination_rules_config,
                'virtual_services': virtual_services_config
            }
        }
        
        # 创建任务列表
        for func_type in [FunctionType.ROUTING, FunctionType.CIRCUIT_BREAKER, 
                         FunctionType.RATE_LIMIT, FunctionType.TRAFFIC_SHIFTING]:
            if func_type in config_data:
                tasks.append((
                    func_type, 
                    config_data[func_type], 
                    f"控制平面-{func_type.value}"
                ))
        
        # 并行执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._parse_control_plane_parser_task, func_type, config, task_name): task_name
                for func_type, config, task_name in tasks
            }
            
            for future in concurrent.futures.as_completed(future_to_task):
                task_name = future_to_task[future]
                try:
                    func_type_key, models, error = future.result()
                    if error:
                        logger.error(f"[并行] {task_name} 失败: {error}")
                    elif models:
                        results[func_type_key] = models
                except Exception as e:
                    logger.error(f"[并行] {task_name} 执行异常: {e}")
        
        logger.info(f"[并行] 控制平面解析完成，共 {len(results)} 个解析结果")
        return results
    
    def _parse_control_plane_serial(
        self,
        services_config: Dict[str, Any],
        virtual_services_config: Dict[str, Any],
        destination_rules_config: Dict[str, Any],
        envoy_filters_config: Dict[str, Any]
    ) -> Dict[str, List[AnyFunctionModel]]:
        """
        串行解析控制平面配置（原有逻辑）
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
        if not self.enable_parallel:
            # 串行处理（原有逻辑）
            return self._parse_data_plane_serial(routes_config, clusters_config, listeners_config)
        
        # 并行处理
        logger.info("[并行] 开始并行解析数据平面配置...")
        results = {}
        tasks = []
        
        # 准备任务数据
        config_data = {
            'routes': routes_config,
            'clusters': clusters_config,
            'listeners': listeners_config
        }
        
        # 创建任务列表 - 只处理有数据的配置
        if routes_config:
            tasks.append((FunctionType.ROUTING, config_data, "数据平面-路由"))
            tasks.append((FunctionType.TRAFFIC_SHIFTING, config_data, "数据平面-流量迁移"))
        
        if clusters_config:
            tasks.append((FunctionType.CIRCUIT_BREAKER, config_data, "数据平面-熔断"))
        
        if listeners_config:
            tasks.append((FunctionType.RATE_LIMIT, config_data, "数据平面-限流"))
        
        if not tasks:
            logger.info("[并行] 没有可解析的数据平面配置")
            return results
        
        # 并行执行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._parse_data_plane_parser_task, func_type, config, task_name): task_name
                for func_type, config, task_name in tasks
            }
            
            for future in concurrent.futures.as_completed(future_to_task):
                task_name = future_to_task[future]
                try:
                    func_type_key, models, error = future.result()
                    if error:
                        logger.error(f"[并行] {task_name} 失败: {error}")
                    elif models:
                        results[func_type_key] = models
                except Exception as e:
                    logger.error(f"[并行] {task_name} 执行异常: {e}")
        
        logger.info(f"[并行] 数据平面解析完成，共 {len(results)} 个解析结果")
        return results
    
    def _parse_data_plane_serial(
        self,
        routes_config: Any,
        clusters_config: Any,
        listeners_config: Any
    ) -> Dict[str, List[AnyFunctionModel]]:
        """
        串行解析数据平面配置（原有逻辑）
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

