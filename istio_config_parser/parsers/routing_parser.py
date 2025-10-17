"""
路由功能解析器
解析控制平面和数据平面的路由配置，生成统一的RoutingFunctionModel
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.models.function_models import (
    RoutingFunctionModel, FunctionType, PlaneType,
    MatchCondition, RouteDestination
)

logger = logging.getLogger(__name__)


class RoutingParser(FunctionParser):
    """路由解析器"""
    
    def __init__(self):
        super().__init__(FunctionType.ROUTING)
    
    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RoutingFunctionModel]:
        """
        解析控制平面路由配置（VirtualService）
        
        Args:
            config: VirtualService 配置字典，格式 {'items': [vs1, vs2, ...]}
            context: 上下文信息
            
        Returns:
            路由功能模型列表
        """
        models = []
        items = config.get('items', []) if isinstance(config, dict) else config
        
        for item in items:
            if item.get('kind') != 'VirtualService':
                continue
            
            namespace, name = self._extract_namespace_and_service(item)
            spec = item.get('spec', {})
            
            # 获取hosts
            hosts = spec.get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            
            # 获取gateways
            gateways = spec.get('gateways', [])
            if not isinstance(gateways, list):
                gateways = [gateways]
            
            # 为每个host创建一个路由模型
            for host in hosts:
                service_name = host.split('.')[0] if host != '*' else name
                
                model = RoutingFunctionModel(
                    function_type=FunctionType.ROUTING,
                    service_name=service_name,
                    namespace=namespace,
                    plane_type=PlaneType.CONTROL_PLANE,
                    hosts=hosts,
                    gateways=gateways,
                    raw_config=item
                )
                
                # 解析HTTP路由规则
                http_routes = spec.get('http', [])
                for idx, http_route in enumerate(http_routes):
                    # 解析匹配条件
                    match_condition = None
                    if 'match' in http_route:
                        match_list = http_route['match']
                        if match_list:
                            first_match = match_list[0]
                            match_condition = MatchCondition(
                                headers=first_match.get('headers', {}),
                                uri=first_match.get('uri'),
                                method=first_match.get('method'),
                                query_params=first_match.get('queryParams', {}),
                                source_labels=first_match.get('sourceLabels', {})
                            )
                    
                    # 解析目标
                    destinations = []
                    for route in http_route.get('route', []):
                        if 'destination' in route:
                            dest = route['destination']
                            destination = RouteDestination(
                                host=dest.get('host', ''),
                                subset=dest.get('subset'),
                                port=dest.get('port', {}).get('number') if isinstance(dest.get('port'), dict) else dest.get('port'),
                                weight=route.get('weight', 100)
                            )
                            destinations.append(destination)
                    
                    # 添加路由规则
                    model.add_route(
                        match=match_condition,
                        destinations=destinations,
                        priority=idx
                    )
                
                models.append(model)
        
        return models
    
    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RoutingFunctionModel]:
        """
        解析数据平面路由配置（Envoy Route Configuration）
        
        Args:
            config: Envoy routes.json 配置
            context: 上下文信息
            
        Returns:
            路由功能模型列表
        """
        models = []
        
        # 确保config是列表格式
        if isinstance(config, dict):
            config = [config]
        
        for route_config in config:
            if 'virtualHosts' not in route_config:
                continue
            
            for vhost in route_config['virtualHosts']:
                domains = vhost.get('domains', [])
                
                # 从域名提取服务名和命名空间
                service_name = 'unknown'
                namespace = 'default'
                
                for domain in domains:
                    if domain != '*':
                        parts = domain.split('.')
                        if len(parts) >= 1:
                            service_name = parts[0]
                        if len(parts) >= 2:
                            namespace = parts[1]
                        break
                
                model = RoutingFunctionModel(
                    function_type=FunctionType.ROUTING,
                    service_name=service_name,
                    namespace=namespace,
                    plane_type=PlaneType.DATA_PLANE,
                    hosts=domains,
                    raw_config=vhost
                )
                
                # 解析路由规则
                for idx, route in enumerate(vhost.get('routes', [])):
                    if 'route' not in route:
                        continue
                    
                    route_info = route['route']
                    
                    # 解析匹配条件
                    match_condition = None
                    if 'match' in route:
                        match = route['match']
                        match_condition = MatchCondition(
                            headers=match.get('headers', {}),
                            uri={'prefix': match.get('prefix')} if 'prefix' in match else None,
                            method=match.get('method'),
                        )
                    
                    # 解析目标
                    destinations = []
                    
                    # 处理加权集群
                    if 'weightedClusters' in route_info:
                        clusters = route_info['weightedClusters'].get('clusters', [])
                        for cluster in clusters:
                            cluster_name = cluster.get('name', '')
                            weight = cluster.get('weight', 0)
                            
                            # 从集群名称解析: outbound|port|subset|host
                            if '|' in cluster_name:
                                parts = cluster_name.split('|')
                                if len(parts) >= 4:
                                    port = parts[1]
                                    subset = parts[2] if parts[2] else None
                                    host = parts[3]
                                    
                                    destination = RouteDestination(
                                        host=host,
                                        subset=subset,
                                        port=int(port) if port.isdigit() else None,
                                        weight=weight
                                    )
                                    destinations.append(destination)
                    
                    # 处理单一集群
                    elif 'cluster' in route_info:
                        cluster_name = route_info['cluster']
                        
                        if '|' in cluster_name:
                            parts = cluster_name.split('|')
                            if len(parts) >= 4:
                                port = parts[1]
                                subset = parts[2] if parts[2] else None
                                host = parts[3]
                                
                                destination = RouteDestination(
                                    host=host,
                                    subset=subset,
                                    port=int(port) if port.isdigit() else None,
                                    weight=100
                                )
                                destinations.append(destination)
                    
                    if destinations:
                        model.add_route(
                            match=match_condition,
                            destinations=destinations,
                            priority=idx
                        )
                
                models.append(model)
        
        return models

