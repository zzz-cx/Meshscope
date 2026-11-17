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


def _vs_ref_from_route(route: Dict[str, Any]) -> Optional[tuple]:
    """从 Envoy route metadata 抽出 (namespace, virtual_service_name)。"""
    cfg_path = (route.get('metadata') or {}).get('filter_metadata') or {}
    cfg_path = (cfg_path.get('istio') or {}).get('config') or ''
    if '/virtual-service/' not in cfg_path:
        return None
    parts = cfg_path.split('/virtual-service/')
    if len(parts) != 2:
        return None
    vs_name = (parts[1].split('/')[0] or parts[1]).strip()
    ns_part = 'default'
    if '/namespaces/' in parts[0]:
        ns_part = parts[0].split('/namespaces/')[-1].split('/')[0] or 'default'
    if not vs_name:
        return None
    return ns_part, vs_name


def _envoy_headers_to_istio(headers: Any) -> Dict[str, Any]:
    """Envoy headers 列表 → Istio {name: {exact|prefix|regex: value}}。"""
    if isinstance(headers, dict):
        return headers
    if not isinstance(headers, list):
        return {}
    out: Dict[str, Any] = {}
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = item.get('name')
        if not name:
            continue
        sm = item.get('string_match') or item.get('stringMatch') or {}
        if not isinstance(sm, dict):
            sm = {}
        if 'exact' in sm:
            out[name] = {'exact': sm['exact']}
        elif 'prefix' in sm:
            out[name] = {'prefix': sm['prefix']}
        elif sm.get('regex') or sm.get('safe_regex') or sm.get('safeRegex'):
            rg = sm.get('regex') or (sm.get('safe_regex') or sm.get('safeRegex') or {}).get('regex')
            out[name] = {'regex': rg}
        elif item.get('exact_match') or item.get('exactMatch'):
            out[name] = {'exact': item.get('exact_match') or item.get('exactMatch')}
        elif item.get('prefix_match') or item.get('prefixMatch'):
            out[name] = {'prefix': item.get('prefix_match') or item.get('prefixMatch')}
    return out


def _envoy_uri(match: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(match, dict):
        return None
    if 'prefix' in match:
        # Envoy 未写 match 时默认 prefix=/，与 Istio 缺 match（全匹配）等价
        if match['prefix'] in ('/', ''):
            return None
        return {'prefix': match['prefix']}
    if 'path' in match:
        return {'exact': match['path']}
    if 'safe_regex' in match or 'safeRegex' in match:
        rg = match.get('safe_regex') or match.get('safeRegex') or {}
        return {'regex': rg.get('regex') if isinstance(rg, dict) else rg}
    return None


def _destinations_from_route_action(route_info: Dict[str, Any]) -> List[RouteDestination]:
    destinations: List[RouteDestination] = []
    wc = route_info.get('weightedClusters') or route_info.get('weighted_clusters') or {}
    clusters = wc.get('clusters', []) if isinstance(wc, dict) else []
    if clusters:
        for cluster in clusters:
            cluster_name = cluster.get('name', '')
            weight = cluster.get('weight', 0)
            dest = _destination_from_cluster_name(cluster_name, weight)
            if dest:
                destinations.append(dest)
        return destinations
    cluster_name = route_info.get('cluster')
    if cluster_name:
        dest = _destination_from_cluster_name(cluster_name, 100)
        if dest:
            destinations.append(dest)
    return destinations


def _destination_from_cluster_name(cluster_name: str, weight: int) -> Optional[RouteDestination]:
    if not cluster_name or '|' not in cluster_name:
        return None
    parts = cluster_name.split('|')
    if len(parts) < 4:
        return None
    port = parts[1]
    subset = parts[2] if parts[2] else None
    host = parts[3]
    return RouteDestination(
        host=host,
        subset=subset,
        port=int(port) if str(port).isdigit() else None,
        weight=weight,
    )


def _fill_routes(model: RoutingFunctionModel, routes: List[Dict[str, Any]]) -> None:
    for idx, route in enumerate(routes):
        if 'route' not in route:
            continue
        route_info = route['route']
        match_condition = None
        if 'match' in route:
            match = route['match'] or {}
            headers = _envoy_headers_to_istio(match.get('headers', {}))
            match_condition = MatchCondition(
                headers=headers,
                uri=_envoy_uri(match),
                method=match.get('method'),
            )
        destinations = _destinations_from_route_action(route_info)
        if destinations:
            model.add_route(match=match_condition, destinations=destinations, priority=idx)


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
            vhosts = route_config.get('virtualHosts') or route_config.get('virtual_hosts')
            if not vhosts:
                continue
            
            for vhost in vhosts:
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
                
                # Gateway 入口 vhost domains=["*"] 会混入多个 VirtualService。
                # 按 route metadata 拆开，才能对上 Sdecl 里 host=* 时用 VS 名做的 service 键。
                if domains and domains[0] == '*':
                    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
                    for route in vhost.get('routes', []):
                        ref = _vs_ref_from_route(route)
                        key = ref or ('default', 'unknown')
                        grouped.setdefault(key, []).append(route)
                    for (ns, vs_name), routes in grouped.items():
                        model = RoutingFunctionModel(
                            function_type=FunctionType.ROUTING,
                            service_name=vs_name,
                            namespace=ns,
                            plane_type=PlaneType.DATA_PLANE,
                            hosts=domains,
                            raw_config={'virtual_service': vs_name, 'namespace': ns, 'vhost': vhost.get('name')},
                        )
                        _fill_routes(model, routes)
                        models.append(model)
                    continue

                model = RoutingFunctionModel(
                    function_type=FunctionType.ROUTING,
                    service_name=service_name,
                    namespace=namespace,
                    plane_type=PlaneType.DATA_PLANE,
                    hosts=domains,
                    raw_config=vhost
                )
                _fill_routes(model, vhost.get('routes', []))
                models.append(model)
        
        return models

