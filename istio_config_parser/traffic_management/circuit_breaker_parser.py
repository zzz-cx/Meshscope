import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.models.data_structures import (
    TrafficPolicyConfig,
    ConnectionPoolConfig,
    OutlierDetectionConfig,
    CircuitBreakerPolicy,
    CircuitBreakerConfig,
    HttpConnectionPool,
    TcpConnectionPool
)

logger = logging.getLogger(__name__)

def parse_connection_pool(connection_pool: Dict[str, Any]) -> Optional[ConnectionPoolConfig]:
    """
    解析连接池配置
    """
    if not connection_pool:
        return None
        
    result: ConnectionPoolConfig = {}
    
    # 解析 HTTP 连接池配置
    if 'http' in connection_pool:
        http_config = connection_pool['http']
        http_result: HttpConnectionPool = {}
        
        if 'http1MaxPendingRequests' in http_config:
            http_result['http1MaxPendingRequests'] = http_config['http1MaxPendingRequests']
        
        if 'http2MaxRequests' in http_config:
            http_result['http2MaxRequests'] = http_config['http2MaxRequests']
            
        if 'maxRequestsPerConnection' in http_config:
            http_result['maxRequestsPerConnection'] = http_config['maxRequestsPerConnection']
            
        if 'maxRetries' in http_config:
            http_result['maxRetries'] = http_config['maxRetries']
            
        if http_result:
            result['http'] = http_result
    
    # 解析 TCP 连接池配置
    if 'tcp' in connection_pool:
        tcp_config = connection_pool['tcp']
        tcp_result: TcpConnectionPool = {}
        
        if 'maxConnections' in tcp_config:
            tcp_result['maxConnections'] = tcp_config['maxConnections']
            
        if 'connectTimeout' in tcp_config:
            tcp_result['connectTimeout'] = tcp_config['connectTimeout']
            
        if tcp_result:
            result['tcp'] = tcp_result
    
    return result if result else None

def parse_outlier_detection(outlier_detection: Dict[str, Any]) -> Optional[OutlierDetectionConfig]:
    """
    解析异常检测配置
    """
    if not outlier_detection:
        return None
        
    result: OutlierDetectionConfig = {}
    
    if 'baseEjectionTime' in outlier_detection:
        result['baseEjectionTime'] = outlier_detection['baseEjectionTime']
        
    if 'consecutive5xxErrors' in outlier_detection:
        result['consecutive5xxErrors'] = outlier_detection['consecutive5xxErrors']
        
    if 'interval' in outlier_detection:
        result['interval'] = outlier_detection['interval']
        
    if 'maxEjectionPercent' in outlier_detection:
        result['maxEjectionPercent'] = outlier_detection['maxEjectionPercent']
        
    if 'minHealthPercent' in outlier_detection:
        result['minHealthPercent'] = outlier_detection['minHealthPercent']
    
    return result if result else None

def parse_circuit_breaker_policy(policy: Dict[str, Any]) -> Optional[CircuitBreakerPolicy]:
    """
    解析熔断策略配置
    """
    if not policy:
        return None
        
    result: CircuitBreakerPolicy = {}
    
    # 解析连接池配置
    if 'connectionPool' in policy:
        connection_pool = parse_connection_pool(policy['connectionPool'])
        if connection_pool:
            result['connectionPool'] = connection_pool
    
    # 解析异常检测配置
    if 'outlierDetection' in policy:
        outlier_detection = parse_outlier_detection(policy['outlierDetection'])
        if outlier_detection:
            result['outlierDetection'] = outlier_detection
    
    return result if result else None

def parse_circuit_breaker(dr_configs: Dict[str, Any]) -> Dict[str, CircuitBreakerConfig]:
    """
    解析熔断配置
    :param dr_configs: DestinationRule 配置
    :return: 熔断配置字典
    """
    circuit_breakers: Dict[str, CircuitBreakerConfig] = {}
    
    dr_items = dr_configs.get('items', []) if isinstance(dr_configs, dict) else dr_configs
    
    for item in dr_items:
        if item.get('kind') == 'DestinationRule':
            host = item['spec'].get('host', '')
            service_name = host.split('.')[0]
            
            if service_name not in circuit_breakers:
                circuit_breakers[service_name] = {
                    'global_': None,  # 全局熔断配置
                    'subsets': {}    # 子集熔断配置
                }
            
            # 解析全局熔断配置
            if 'trafficPolicy' in item['spec']:
                global_policy = parse_circuit_breaker_policy(item['spec']['trafficPolicy'])
                if global_policy:
                    circuit_breakers[service_name]['global_'] = global_policy
            
            # 解析子集熔断配置
            for subset in item['spec'].get('subsets', []):
                subset_name = subset['name']
                if 'trafficPolicy' in subset:
                    subset_policy = parse_circuit_breaker_policy(subset['trafficPolicy'])
                    circuit_breakers[service_name]['subsets'][subset_name] = subset_policy
                else:
                    # 设置为null表示没有特定配置
                    circuit_breakers[service_name]['subsets'][subset_name] = None
    
    return circuit_breakers 