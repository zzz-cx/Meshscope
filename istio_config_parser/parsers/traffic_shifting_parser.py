"""
流量迁移/灰度发布功能解析器
解析控制平面和数据平面的流量迁移配置，生成统一的TrafficShiftingFunctionModel
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.models.function_models import (
    TrafficShiftingFunctionModel, RouteDestination, FunctionType, PlaneType
)

logger = logging.getLogger(__name__)


class TrafficShiftingParser(FunctionParser):
    """流量迁移/灰度发布解析器"""
    
    def __init__(self):
        super().__init__(FunctionType.TRAFFIC_SHIFTING)
    
    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[TrafficShiftingFunctionModel]:
        """
        解析控制平面流量迁移配置（DestinationRule + VirtualService）
        
        Args:
            config: 包含DestinationRule和VirtualService的配置字典
                   格式: {'destination_rules': {...}, 'virtual_services': {...}}
            context: 上下文信息
            
        Returns:
            流量迁移功能模型列表
        """
        models = []
        
        # 分离DestinationRule和VirtualService
        dr_items = []
        vs_items = []
        
        if 'items' in config:
            items = config['items']
            dr_items = [item for item in items if item.get('kind') == 'DestinationRule']
            vs_items = [item for item in items if item.get('kind') == 'VirtualService']
        else:
            # 如果传入的是分开的配置
            dr_items = config.get('destination_rules', {}).get('items', [])
            vs_items = config.get('virtual_services', {}).get('items', [])
        
        # 第一步：从DestinationRule提取子集定义
        service_subsets: Dict[str, Dict] = {}
        
        for dr in dr_items:
            spec = dr.get('spec', {})
            namespace, name = self._extract_namespace_and_service(dr)
            
            host = spec.get('host', '')
            service_name = host.split('.')[0] if host else name
            
            if service_name not in service_subsets:
                service_subsets[service_name] = {
                    'namespace': namespace,
                    'subsets': [],
                    'raw_dr': dr
                }
            
            # 提取子集定义
            for subset in spec.get('subsets', []):
                subset_info = {
                    'name': subset.get('name'),
                    'version': subset.get('labels', {}).get('version'),
                    'labels': subset.get('labels', {})
                }
                service_subsets[service_name]['subsets'].append(subset_info)
        
        # 第二步：从VirtualService提取权重信息
        for vs in vs_items:
            spec = vs.get('spec', {})
            namespace, name = self._extract_namespace_and_service(vs)
            
            # 从hosts获取服务名
            hosts = spec.get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            
            # 处理每个HTTP路由规则
            for http_route in spec.get('http', []):
                routes = http_route.get('route', [])
                
                # 检查是否有权重分配（灰度发布的标志）
                has_weights = any(r.get('weight') for r in routes if 'weight' in r)
                
                if has_weights and len(routes) > 1:
                    # 这是一个灰度发布配置
                    for host in hosts:
                        service_name = host.split('.')[0] if host != '*' else None
                        
                        # 如果找不到服务名，从目标获取
                        if not service_name:
                            for route in routes:
                                dest = route.get('destination', {})
                                if 'host' in dest:
                                    service_name = dest['host'].split('.')[0]
                                    break
                        
                        if not service_name:
                            continue
                        
                        # 创建或获取模型
                        model = TrafficShiftingFunctionModel(
                            function_type=FunctionType.TRAFFIC_SHIFTING,
                            service_name=service_name,
                            namespace=namespace,
                            plane_type=PlaneType.CONTROL_PLANE,
                            raw_config={'virtual_service': vs}
                        )
                        
                        # 添加子集定义（如果有）
                        if service_name in service_subsets:
                            model.subsets = service_subsets[service_name]['subsets']
                            model.raw_config['destination_rule'] = service_subsets[service_name]['raw_dr']
                        
                        # 添加路由目标和权重
                        for route in routes:
                            dest = route.get('destination', {})
                            
                            destination = RouteDestination(
                                host=dest.get('host', ''),
                                subset=dest.get('subset'),
                                port=dest.get('port', {}).get('number') if isinstance(dest.get('port'), dict) else dest.get('port'),
                                weight=route.get('weight', 100)
                            )
                            model.destinations.append(destination)
                        
                        models.append(model)
        
        return models
    
    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[TrafficShiftingFunctionModel]:
        """
        解析数据平面流量迁移配置（Envoy weighted clusters）
        
        Args:
            config: Envoy routes.json 配置
            context: 上下文信息
            
        Returns:
            流量迁移功能模型列表
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
                
                # 检查路由规则中的weighted clusters
                for route in vhost.get('routes', []):
                    if 'route' not in route:
                        continue
                    
                    route_info = route['route']
                    
                    # 查找加权集群配置
                    if 'weightedClusters' in route_info:
                        clusters = route_info['weightedClusters'].get('clusters', [])
                        
                        # 只有当有多个集群时才认为是流量迁移
                        if len(clusters) > 1:
                            model = TrafficShiftingFunctionModel(
                                function_type=FunctionType.TRAFFIC_SHIFTING,
                                service_name=service_name,
                                namespace=namespace,
                                plane_type=PlaneType.DATA_PLANE,
                                raw_config={'route': route}
                            )
                            
                            # 解析每个加权集群
                            subsets_info = {}
                            
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
                                        model.destinations.append(destination)
                                        
                                        # 收集子集信息
                                        if subset and subset not in subsets_info:
                                            subsets_info[subset] = {
                                                'name': subset,
                                                'version': subset,  # 通常subset名称就是版本号
                                                'labels': {'version': subset}
                                            }
                            
                            # 添加子集定义
                            model.subsets = list(subsets_info.values())
                            
                            if model.destinations:
                                models.append(model)
        
        return models

