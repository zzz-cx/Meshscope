"""
限流功能解析器
解析控制平面和数据平面的限流配置，生成统一的RateLimitFunctionModel
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.models.function_models import (
    RateLimitFunctionModel, RateLimitRule, FunctionType, PlaneType,
    MatchCondition
)

logger = logging.getLogger(__name__)


class RateLimitParser(FunctionParser):
    """限流解析器"""
    
    def __init__(self):
        super().__init__(FunctionType.RATE_LIMIT)
    
    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RateLimitFunctionModel]:
        """
        解析控制平面限流配置（EnvoyFilter）
        
        Args:
            config: EnvoyFilter 配置字典
            context: 上下文信息
            
        Returns:
            限流功能模型列表
        """
        models = []
        items = config.get('items', []) if isinstance(config, dict) else config
        
        for item in items:
            if item.get('kind') != 'EnvoyFilter':
                continue
            
            namespace, name = self._extract_namespace_and_service(item)
            spec = item.get('spec', {})
            
            # 从workloadSelector获取服务名
            workload_selector = spec.get('workloadSelector', {})
            labels = workload_selector.get('labels', {})
            service_name = labels.get('app', name)
            
            model = RateLimitFunctionModel(
                function_type=FunctionType.RATE_LIMIT,
                service_name=service_name,
                namespace=namespace,
                plane_type=PlaneType.CONTROL_PLANE,
                raw_config=item
            )
            
            # 解析配置补丁
            for patch in spec.get('configPatches', []):
                apply_to = patch.get('applyTo')
                
                # 解析HTTP_FILTER类型的限流配置
                if apply_to == 'HTTP_FILTER':
                    patch_value = patch.get('patch', {}).get('value', {})
                    
                    if patch_value.get('name') == 'envoy.filters.http.local_ratelimit':
                        typed_config = patch_value.get('typed_config', {})
                        
                        if '@type' in typed_config:
                            token_bucket = typed_config.get('token_bucket', {})
                            
                            if token_bucket:
                                # 提取限流参数
                                max_tokens = token_bucket.get('max_tokens')
                                fill_interval = token_bucket.get('fill_interval', '')
                                
                                # 转换填充间隔为时间单位
                                unit = 'SECOND'
                                if 's' in fill_interval:
                                    seconds = int(''.join(filter(str.isdigit, fill_interval)) or '0')
                                    if seconds == 60:
                                        unit = 'MINUTE'
                                    elif seconds == 3600:
                                        unit = 'HOUR'
                                    elif seconds == 86400:
                                        unit = 'DAY'
                                
                                rule = RateLimitRule(
                                    requests_per_unit=max_tokens,
                                    unit=unit
                                )
                                model.rules.append(rule)
                
                # 解析VIRTUAL_HOST类型的限流配置
                elif apply_to == 'VIRTUAL_HOST':
                    patch_value = patch.get('patch', {}).get('value', {})
                    rate_limits = patch_value.get('rate_limits', [])
                    
                    for limit in rate_limits:
                        # 解析限流动作
                        match_condition = MatchCondition()
                        
                        for action in limit.get('actions', []):
                            if 'request_headers' in action:
                                header = action['request_headers']
                                match_condition.headers[header.get('header_name', '')] = {
                                    'descriptor_key': header.get('descriptor_key')
                                }
                            
                            if 'source_cluster' in action:
                                pass  # 可以添加源集群匹配
                            
                            if 'destination_cluster' in action:
                                pass  # 可以添加目标集群匹配
                        
                        # 注意：VIRTUAL_HOST类型通常需要与rate_limit_service配合使用
                        # 这里创建一个规则占位符
                        rule = RateLimitRule(
                            requests_per_unit=0,  # 需要从rate_limit_service获取
                            unit='MINUTE',
                            match_conditions=match_condition if match_condition.headers else None
                        )
                        model.rules.append(rule)
                
                # 解析CLUSTER类型的限流服务配置
                elif apply_to == 'CLUSTER':
                    patch_value = patch.get('patch', {}).get('value', {})
                    if 'rate_limit_service' in patch_value or 'ratelimit' in str(patch_value).lower():
                        model.rate_limit_service = patch_value
            
            if model.rules or model.rate_limit_service:
                models.append(model)
        
        return models
    
    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RateLimitFunctionModel]:
        """
        解析数据平面限流配置（Envoy Listener中的限流过滤器）
        
        Args:
            config: Envoy listeners.json 配置
            context: 上下文信息
            
        Returns:
            限流功能模型列表
        """
        models = []
        
        # 数据平面限流配置在listener的filter chain中
        if isinstance(config, dict):
            listeners = config.get('dynamicListeners', [])
        elif isinstance(config, list):
            listeners = config
        else:
            listeners = []
        
        # 按服务聚合限流配置
        service_ratelimits: Dict[str, Dict] = {}
        
        for listener_item in listeners:
            listener = listener_item.get('activeState', {}).get('listener', {}) if 'activeState' in listener_item else listener_item
            
            # 从listener名称提取服务信息
            listener_name = listener.get('name', '')
            
            # 遍历filter chains
            for filter_chain in listener.get('filterChains', []):
                for net_filter in filter_chain.get('filters', []):
                    if net_filter.get('name') == 'envoy.filters.network.http_connection_manager':
                        typed_config = net_filter.get('typedConfig', {})
                        http_filters = typed_config.get('httpFilters', [])
                        
                        for http_filter in http_filters:
                            filter_name = http_filter.get('name', '')
                            
                            # 查找local_ratelimit过滤器
                            if 'local_ratelimit' in filter_name or 'ratelimit' in filter_name:
                                filter_config = http_filter.get('typedConfig', {})
                                
                                # 提取服务名（从route config或listener名称）
                                service_name = 'unknown'
                                namespace = 'default'
                                
                                # 尝试从route_config获取
                                route_config = typed_config.get('routeConfig', {})
                                if route_config:
                                    vhosts = route_config.get('virtualHosts', [])
                                    if vhosts:
                                        domains = vhosts[0].get('domains', [])
                                        if domains:
                                            domain_parts = domains[0].split('.')
                                            if domain_parts:
                                                service_name = domain_parts[0]
                                                if len(domain_parts) > 1:
                                                    namespace = domain_parts[1]
                                
                                if service_name not in service_ratelimits:
                                    service_ratelimits[service_name] = {
                                        'namespace': namespace,
                                        'rules': [],
                                        'config': []
                                    }
                                
                                # 解析token bucket配置
                                token_bucket = filter_config.get('tokenBucket', {})
                                if token_bucket:
                                    max_tokens = token_bucket.get('maxTokens')
                                    tokens_per_fill = token_bucket.get('tokensPerFill', {}).get('value')
                                    fill_interval = token_bucket.get('fillInterval', '')
                                    
                                    # 转换时间单位
                                    unit = 'SECOND'
                                    if 's' in str(fill_interval):
                                        seconds = int(''.join(filter(str.isdigit, str(fill_interval))) or '0')
                                        if seconds == 60:
                                            unit = 'MINUTE'
                                        elif seconds == 3600:
                                            unit = 'HOUR'
                                        elif seconds == 86400:
                                            unit = 'DAY'
                                    
                                    service_ratelimits[service_name]['rules'].append({
                                        'requests_per_unit': max_tokens or tokens_per_fill,
                                        'unit': unit
                                    })
                                
                                service_ratelimits[service_name]['config'].append(filter_config)
        
        # 为每个服务创建限流模型
        for service_name, ratelimit_info in service_ratelimits.items():
            model = RateLimitFunctionModel(
                function_type=FunctionType.RATE_LIMIT,
                service_name=service_name,
                namespace=ratelimit_info['namespace'],
                plane_type=PlaneType.DATA_PLANE,
                raw_config={'configs': ratelimit_info['config']}
            )
            
            for rule_dict in ratelimit_info['rules']:
                rule = RateLimitRule(
                    requests_per_unit=rule_dict['requests_per_unit'],
                    unit=rule_dict['unit']
                )
                model.rules.append(rule)
            
            if model.rules:
                models.append(model)
        
        return models

