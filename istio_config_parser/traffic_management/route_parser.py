import logging
from typing import Dict, List, Any
from istio_config_parser.models.data_structures import (
    DataPlaneServiceRelation,
    ServiceRelation,
    RouteRule,
    GatewayInfo,
    DataPlaneRoute
)

logger = logging.getLogger(__name__)

def parse_routes(configs: Dict[str, Any], is_data_plane: bool = False) -> Dict[str, Any]:
    """
    解析路由规则
    is_data_plane: 是否为数据平面配置
    """
    if is_data_plane:
        return parse_data_plane_routes(configs)
    return parse_control_plane_routes(configs)

def parse_data_plane_routes(configs: List[Dict[str, Any]]) -> Dict[str, DataPlaneServiceRelation]:
    """
    解析数据平面路由配置
    返回结构示例：{service_name: {inbound: [], outbound: [], weights: {}}}
    """
    service_relations: Dict[str, DataPlaneServiceRelation] = {}
    discovered_services = set()
    
    # 第一次遍历：收集所有服务名称
    for route_config in configs:
        if 'virtualHosts' not in route_config:
            continue
            
        for vhost in route_config['virtualHosts']:
            domains = vhost.get('domains', [])
            
            # 从域名中提取服务名称
            for domain in domains:
                domain_parts = domain.split('.')
                if domain_parts:
                    service_name = domain_parts[0]
                    if service_name and service_name != '*':
                        discovered_services.add(service_name)
                        
            # 从路由规则中提取目标服务
            for route in vhost.get('routes', []):
                if 'route' in route:
                    route_info = route['route']
                    
                    # 检查单一集群
                    if 'cluster' in route_info:
                        cluster_name = route_info['cluster']
                        if '|' in cluster_name:
                            parts = cluster_name.split('|')
                            if len(parts) >= 4:
                                service_name = parts[3].split('.')[0]
                                discovered_services.add(service_name)
                    
                    # 检查加权集群
                    elif 'weightedClusters' in route_info:
                        clusters = route_info['weightedClusters'].get('clusters', [])
                        for cluster in clusters:
                            cluster_name = cluster.get('name', '')
                            if '|' in cluster_name:
                                parts = cluster_name.split('|')
                                if len(parts) >= 4:
                                    service_name = parts[3].split('.')[0]
                                    discovered_services.add(service_name)
    
    # 初始化服务关系结构
    for service in discovered_services:
        service_relations[service] = {
            'inbound': [],    # 入站路由
            'outbound': [],   # 出站路由
            'weights': {}     # 版本权重
        }
    
    # 第二次遍历：解析路由规则
    for route_config in configs:
        if 'virtualHosts' not in route_config:
            continue
            
        # 检查metadata中的权重信息
        if 'metadata' in route_config:
            metadata = route_config.get('metadata', {})
            filter_metadata = metadata.get('filter_metadata', {})
            
            if 'istio' in filter_metadata:
                istio_metadata = filter_metadata['istio']
                if 'subset' in istio_metadata:
                    subset = istio_metadata['subset']
                    service_name = None
                    
                    if 'host' in route_config:
                        host = route_config['host']
                        service_parts = host.split('.')
                        if service_parts and service_parts[0] in discovered_services:
                            service_name = service_parts[0]
                            
                    if service_name:
                        weight = istio_metadata.get('weight', 100)
                        service_relations[service_name]['weights'][subset] = weight
        
        # 解析virtualHosts
        for vhost in route_config['virtualHosts']:
            domains = vhost.get('domains', [])
            service_name = None
            
            # 获取服务名
            for domain in domains:
                domain_parts = domain.split('.')
                if domain_parts and domain_parts[0] in discovered_services:
                    service_name = domain_parts[0]
                    break
            
            if not service_name:
                continue
            
            # 分析路由规则
            for route in vhost.get('routes', []):
                if 'route' not in route:
                    continue
                
                route_info = route['route']
                
                # 处理加权路由
                if 'weightedClusters' in route_info:
                    clusters = route_info['weightedClusters'].get('clusters', [])
                    weights = {}
                    
                    for cluster in clusters:
                        cluster_name = cluster['name']
                        
                        # 从集群metadata中提取subset信息
                        if 'metadata' in cluster:
                            cluster_metadata = cluster.get('metadata', {})
                            for key, value in cluster_metadata.items():
                                if 'subset' in key.lower() or 'version' in key.lower():
                                    subset = value
                                    weight = cluster.get('weight', 0)
                                    weights[subset] = weight
                        
                        # 从集群名称解析版本
                        parts = cluster_name.split('|')
                        if len(parts) >= 4:
                            version = parts[2]
                            weight = cluster.get('weight', 0)
                            weights[version] = weight
                    
                    if weights:
                        service_relations[service_name]['weights'].update(weights)
                
                # 处理单一集群路由
                elif 'cluster' in route_info:
                    cluster_name = route_info['cluster']
                    
                    if cluster_name.startswith('outbound|'):
                        parts = cluster_name.split('|')
                        if len(parts) >= 4:
                            target_service_fqdn = parts[3]
                            target_service = target_service_fqdn.split('.')[0]
                            
                            if target_service in discovered_services:
                                outbound_route = {
                                    'service': target_service,
                                    'port': parts[1]
                                }
                                service_relations[service_name]['outbound'].append(outbound_route)
    
    return service_relations

def parse_control_plane_routes(configs: Dict[str, Any]) -> Dict[str, ServiceRelation]:
    """
    解析控制平面路由配置
    返回结构示例：{service_name: {inbound: [], outbound: [], gateways: []}}
    """
    routes: Dict[str, ServiceRelation] = {}
    items = configs.get('items', []) if isinstance(configs, dict) else configs
    
    # 第一次遍历：收集所有服务名称
    discovered_services = set()
    virtual_services_with_gateways = []
    
    for item in items:
        if item.get('kind') == 'VirtualService':
            namespace = item['metadata'].get('namespace', 'default')
            vs_name = item['metadata']['name']
            
            # 记录带有gateway的VirtualService
            if 'gateways' in item['spec']:
                virtual_services_with_gateways.append(item)
            
            # 从hosts中提取服务名
            hosts = item['spec'].get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            for host in hosts:
                if host and host != '*':
                    service_name = host.split('.')[0]
                    discovered_services.add((service_name, namespace))
                    
            # 从路由目的地提取服务名
            for http in item['spec'].get('http', []):
                for route in http.get('route', []):
                    if 'destination' in route:
                        dest = route['destination']
                        if 'host' in dest:
                            service_name = dest['host'].split('.')[0]
                            discovered_services.add((service_name, namespace))
    
    # 初始化服务路由结构
    for service_name, namespace in discovered_services:
        routes[service_name] = {
            'inbound': [],    # 入站路由
            'outbound': [],   # 出站路由
            'gateways': [],   # 网关配置
            'namespace': namespace
        }
    
    # 第二次遍历：解析路由规则
    for item in items:
        if item.get('kind') == 'VirtualService':
            vs_name = item['metadata']['name']
            namespace = item['metadata'].get('namespace', 'default')
            gateways = item['spec'].get('gateways', [])
            if not isinstance(gateways, list):
                gateways = [gateways]
            
            # 处理每个服务
            hosts = item['spec'].get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            
            # 获取虚拟服务中定义的目标服务
            target_services = set()
            for http in item['spec'].get('http', []):
                for route in http.get('route', []):
                    if 'destination' in route:
                        dest = route['destination']
                        if 'host' in dest:
                            service_name = dest['host'].split('.')[0]
                            target_services.add(service_name)
            
            # 处理hosts和目标服务
            for host in hosts:
                service_name = None
                if host != '*':
                    service_name = host.split('.')[0]
                
                # 处理主机为特定服务的情况
                if service_name and service_name in routes:
                    # 添加入站路由
                    routes[service_name]['inbound'].append({
                        'name': vs_name,
                        'namespace': namespace,
                        'rules': item['spec'].get('http', [])
                    })
                    
                    # 添加网关信息
                    for gateway in gateways:
                        gateway_info = {
                            'name': gateway,
                            'type': 'ingress',
                            'virtualService': vs_name,
                            'namespace': namespace
                        }
                        # 检查是否已存在相同网关
                        if not any(g['name'] == gateway and g['virtualService'] == vs_name 
                                for g in routes[service_name]['gateways']):
                            routes[service_name]['gateways'].append(gateway_info)
                    
                # 处理主机为通配符但有目标服务的情况
                elif host == '*' and target_services:
                    for target_service in target_services:
                        if target_service in routes:
                            # 添加入站路由
                            if not any(r['name'] == vs_name for r in routes[target_service]['inbound']):
                                routes[target_service]['inbound'].append({
                                    'name': vs_name,
                                    'namespace': namespace,
                                    'rules': item['spec'].get('http', [])
                                })
                            
                            # 添加网关信息
                            for gateway in gateways:
                                gateway_info = {
                                    'name': gateway,
                                    'type': 'ingress',
                                    'virtualService': vs_name,
                                    'namespace': namespace
                                }
                                # 检查是否已存在相同网关
                                if not any(g['name'] == gateway and g['virtualService'] == vs_name 
                                        for g in routes[target_service]['gateways']):
                                    routes[target_service]['gateways'].append(gateway_info)
                
                # 处理出站路由
                for service_name in routes:
                    for http in item['spec'].get('http', []):
                        for route in http.get('route', []):
                            if 'destination' in route:
                                dest = route['destination']
                                if 'host' in dest:
                                    target_service = dest['host'].split('.')[0]
                                    if target_service in routes and service_name != target_service:
                                        outbound_route = {
                                            'service': target_service,
                                            'port': dest.get('port', {}).get('number', 80),
                                            'subset': dest.get('subset'),
                                            'namespace': namespace
                                        }
                                        if outbound_route not in routes[service_name]['outbound']:
                                            routes[service_name]['outbound'].append(outbound_route)
    
    return routes 