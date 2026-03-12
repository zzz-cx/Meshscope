"""
K8s Service 解析器
解析 Kubernetes Service 配置，供 legacy 格式输出使用
"""
import logging
from typing import Dict, List, Any
from istio_config_parser.models.data_structures import BaseService

logger = logging.getLogger(__name__)


def parse_services(configs: Dict[str, Any]) -> List[BaseService]:
    """
    解析 K8s Service 配置
    返回 BaseService 列表
    """
    services: List[BaseService] = []
    items = configs.get('items', []) if isinstance(configs, dict) else configs

    for item in items:
        if item.get('kind') != 'Service':
            continue
        service_name = item['metadata'].get('name')
        if not service_name:
            continue

        ports = []
        for port in item['spec'].get('ports', []):
            ports.append({
                'name': port.get('name', ''),
                'port': port.get('port'),
                'targetPort': port.get('targetPort'),
                'protocol': port.get('protocol', 'TCP')
            })

        services.append({
            'name': service_name,
            'namespace': item['metadata'].get('namespace', 'default'),
            'type': item['spec'].get('type', 'ClusterIP'),
            'ports': ports,
            'selector': item['spec'].get('selector', {}),
            'labels': item['metadata'].get('labels', {}),
            'annotations': item['metadata'].get('annotations', {}),
            'clusterIP': item['spec'].get('clusterIP', ''),
            'sessionAffinity': item['spec'].get('sessionAffinity', 'None')
        })

    return services
