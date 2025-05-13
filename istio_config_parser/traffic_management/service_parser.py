import logging
from typing import Dict, List, Any
from istio_config_parser.models.data_structures import BaseService

logger = logging.getLogger(__name__)

def parse_services(configs: Dict[str, Any]) -> List[BaseService]:
    """
    解析服务配置
    返回结构示例：[{
        name: str,                    # 服务名称
        namespace: str,               # 命名空间
        type: str,                    # 服务类型（ClusterIP/NodePort等）
        ports: List[Dict],            # 端口配置
        selector: Dict,               # 服务选择器
        labels: Dict,                 # 标签
        annotations: Dict,            # 注解
        clusterIP: str,               # 集群IP
        sessionAffinity: str          # 会话亲和性
    }]
    """
    services: List[BaseService] = []
    items = configs.get('items', []) if isinstance(configs, dict) else configs
    
    for item in items:
        if item.get('kind') == 'Service':
            service_name = item['metadata'].get('name')
            if service_name:
                # 解析端口配置
                ports = []
                for port in item['spec'].get('ports', []):
                    port_config = {
                        'name': port.get('name', ''),
                        'port': port.get('port'),
                        'targetPort': port.get('targetPort'),
                        'protocol': port.get('protocol', 'TCP')
                    }
                    ports.append(port_config)
                
                # 构建服务配置
                service: BaseService = {
                    'name': service_name,
                    'namespace': item['metadata'].get('namespace', 'default'),
                    'type': item['spec'].get('type', 'ClusterIP'),
                    'ports': ports,
                    'selector': item['spec'].get('selector', {}),
                    'labels': item['metadata'].get('labels', {}),
                    'annotations': item['metadata'].get('annotations', {}),
                    'clusterIP': item['spec'].get('clusterIP', ''),
                    'sessionAffinity': item['spec'].get('sessionAffinity', 'None')
                }
                
                # 记录解析日志
                logger.debug(f"解析服务配置: {service_name}")
                logger.debug(f"  命名空间: {service['namespace']}")
                logger.debug(f"  类型: {service['type']}")
                logger.debug(f"  端口数: {len(ports)}")
                
                services.append(service)
    
    return services 