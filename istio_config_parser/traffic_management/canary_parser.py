import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.models.data_structures import (
    SubsetInfo,
    TrafficPolicyConfig,
    ConnectionPoolConfig,
    OutlierDetectionConfig
)

logger = logging.getLogger(__name__)

def parse_traffic_policy(policy: Dict[str, Any]) -> Optional[TrafficPolicyConfig]:
    """
    解析流量策略配置
    """
    if not policy:
        return None
        
    result = {}
    
    # 解析连接池配置
    if 'connectionPool' in policy:
        connection_pool = policy['connectionPool']
        result['connectionPool'] = {
            'http': connection_pool.get('http', {}),
            'tcp': connection_pool.get('tcp', {})
        }
    
    # 解析异常检测配置
    if 'outlierDetection' in policy:
        outlier_detection = policy['outlierDetection']
        result['outlierDetection'] = {
            'baseEjectionTime': outlier_detection.get('baseEjectionTime'),
            'consecutive5xxErrors': outlier_detection.get('consecutive5xxErrors'),
            'interval': outlier_detection.get('interval'),
            'maxEjectionPercent': outlier_detection.get('maxEjectionPercent')
        }
    
    return result if result else None

def parse_canary(dr_configs: Dict[str, Any], vs_configs: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析灰度发布（版本/权重）配置
    """
    canary = {}
    
    # 解析 DestinationRule 配置
    dr_items = dr_configs.get('items', []) if isinstance(dr_configs, dict) else dr_configs
    vs_items = vs_configs.get('items', []) if isinstance(vs_configs, dict) else vs_configs
    
    # 第一次遍历：处理 DestinationRule
    for item in dr_items:
        if item.get('kind') == 'DestinationRule':
            host = item['spec'].get('host', '')
            service_name = host.split('.')[0]
            namespace = item['metadata'].get('namespace', 'default')
            
            if service_name not in canary:
                canary[service_name] = {
                    'subsets': [],
                    'weights': {},
                    'namespace': namespace
                }
            
            # 处理子集
            subsets = item['spec'].get('subsets', [])
            for subset in subsets:
                subset_info = {
                    'name': subset['name'],
                    'version': subset['labels'].get('version'),
                    'labels': subset['labels']
                }
                canary[service_name]['subsets'].append(subset_info)
    
    # 第二次遍历：处理 VirtualService 中的权重
    for item in vs_items:
        if item.get('kind') == 'VirtualService':
            namespace = item['metadata'].get('namespace', 'default')
            for http in item['spec'].get('http', []):
                for route in http.get('route', []):
                    if 'destination' in route:
                        dest = route['destination']
                        if 'host' in dest:
                            service_name = dest['host'].split('.')[0]
                            subset = dest.get('subset')
                            weight = route.get('weight', 100)
                            
                            if service_name in canary and subset:
                                canary[service_name]['weights'][subset] = {
                                    'weight': weight,
                                    'namespace': namespace
                                }
    
    return canary 