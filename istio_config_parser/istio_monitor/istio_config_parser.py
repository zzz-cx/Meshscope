import yaml
import json
from typing import Dict, List, Any, Optional, Union

class IstioConfigParser:
    """
    Istio 配置解析器，用于解析 Istio 配置并提取关键信息
    """
    
    def __init__(self):
        """初始化配置解析器"""
        self.services = []
        self.service_relations = {}
        self.configurations = {}
        self.subset_weights = {}
    
    def parse_yaml_files(self, service_file: str, config_file: str) -> Dict:
        """
        解析 Kubernetes 服务文件和 Istio 配置文件
        
        参数:
            service_file: Kubernetes 服务文件路径
            config_file: Istio 配置文件路径
            
        返回:
            解析结果
        """
        # 1. 解析基础服务信息
        try:
            with open(service_file, 'r', encoding='utf-8') as f:
                services_data = yaml.safe_load(f)
        except Exception as e:
            print(f"读取服务文件错误: {e}")
            return {
                'services': [],
                'serviceRelations': {},
                'configurations': {}
            }

        # 2. 解析服务列表
        self.services = []
        for item in services_data.get('items', []):
            if item.get('kind') == 'Service':
                service_name = item['metadata'].get('name')
                if service_name:
                    self.services.append({
                        'name': service_name,
                        'namespace': item['metadata'].get('namespace', 'default'),
                        'type': 'service',
                        'ports': item['spec'].get('ports', []),
                        'selector': item['spec'].get('selector', {})
                    })

        # 3. 解析 Istio 配置
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)
        except Exception as e:
            print(f"读取 Istio 配置文件错误: {e}")
            return {
                'services': self.services,
                'serviceRelations': {},
                'configurations': {}
            }

        # 4. 初始化服务关系和配置
        self._initialize_service_data()
        
        # 5. 解析 VirtualService 配置
        self._parse_virtual_services(yaml_data)
        
        # 6. 解析 DestinationRule 配置
        self._parse_destination_rules(yaml_data)
        
        # 7. 解析 EnvoyFilter 配置
        self._parse_envoy_filters(yaml_data)
        
        # 8. 返回解析结果
        return {
            'services': self.services,
            'serviceRelations': self.service_relations,
            'configurations': self.configurations
        }
    
    def _initialize_service_data(self):
        """初始化服务关系和配置数据"""
        self.service_relations = {}
        self.configurations = {}
        self.subset_weights = {}
        
        for service in self.services:
            service_name = service['name']
            if service_name not in self.service_relations:
                self.service_relations[service_name] = {
                    'incomingVirtualServices': [],
                    'subsets': [],
                    'rateLimit': {
                        'type': 'local',
                        'requests_per_unit': 3,
                        'unit': 'minute',
                        'conditions': []
                    }
                }
            if service_name not in self.configurations:
                self.configurations[service_name] = {
                    'virtualServices': [],
                    'destinationRules': [],
                    'envoyFilters': []
                }
            self.subset_weights[service_name] = {}
    
    def _parse_virtual_services(self, yaml_data: Dict):
        """
        解析 VirtualService 配置
        
        参数:
            yaml_data: YAML 数据
        """
        for item in yaml_data.get('items', []):
            if item.get('kind') == 'VirtualService':
                hosts = item['spec'].get('hosts', [])
                if not isinstance(hosts, list):
                    hosts = [hosts]
                
                for host in hosts:
                    service_name = host.split('.')[0]
                    if service_name:
                        # 添加到配置
                        if service_name not in self.configurations:
                            self.configurations[service_name] = {
                                'virtualServices': [],
                                'destinationRules': [],
                                'envoyFilters': []
                            }
                        vs_name = item['metadata'].get('name')
                        if not any(vs['metadata']['name'] == vs_name for vs in self.configurations[service_name]['virtualServices']):
                            self.configurations[service_name]['virtualServices'].append(item)
                        
                        # 提取路由权重信息
                        http_routes = item['spec'].get('http', [])
                        for route_rule in http_routes:
                            if 'route' in route_rule:
                                for route in route_rule['route']:
                                    if 'destination' in route and 'subset' in route['destination']:
                                        subset = route['destination']['subset']
                                        weight = route.get('weight', 0)
                                        self.subset_weights[service_name][subset] = weight
    
    def _parse_destination_rules(self, yaml_data: Dict):
        """
        解析 DestinationRule 配置
        
        参数:
            yaml_data: YAML 数据
        """
        for item in yaml_data.get('items', []):
            if item.get('kind') == 'DestinationRule':
                host = item['spec'].get('host', '')
                service_name = host.split('.')[0]
                
                if service_name:
                    # 添加到配置
                    if service_name not in self.configurations:
                        self.configurations[service_name] = {
                            'virtualServices': [],
                            'destinationRules': [],
                            'envoyFilters': []
                        }
                    dr_name = item['metadata'].get('name')
                    if not any(dr['metadata']['name'] == dr_name for dr in self.configurations[service_name]['destinationRules']):
                        self.configurations[service_name]['destinationRules'].append(item)
                    
                    # 添加子集信息
                    if service_name not in self.service_relations:
                        self.service_relations[service_name] = {
                            'incomingVirtualServices': [],
                            'subsets': [],
                            'rateLimit': {
                                'type': 'local',
                                'requests_per_unit': 3,
                                'unit': 'minute',
                                'conditions': []
                            }
                        }
                    # 清除现有的子集并添加新的
                    self.service_relations[service_name]['subsets'] = []
                    for subset in item['spec'].get('subsets', []):
                        subset_info = {
                            'name': subset['name'],
                            'version': subset['labels'].get('version'),
                            'labels': subset['labels'],
                            'weight': self.subset_weights.get(service_name, {}).get(subset['name'], 0)
                        }
                        self.service_relations[service_name]['subsets'].append(subset_info)
    
    def _parse_envoy_filters(self, yaml_data: Dict):
        """
        解析 EnvoyFilter 配置
        
        参数:
            yaml_data: YAML 数据
        """
        for item in yaml_data.get('items', []):
            if item.get('kind') == 'EnvoyFilter':
                workload_selector = item['spec'].get('workloadSelector', {})
                if workload_selector:
                    service_name = workload_selector.get('matchLabels', {}).get('app')
                    
                    if service_name and service_name in self.service_relations:
                        # 添加到配置
                        self.configurations[service_name]['envoyFilters'].append(item)
                        
                        # 解析限流配置
                        for patch in item['spec'].get('configPatches', []):
                            # 处理 HTTP_FILTER 配置
                            if patch.get('applyTo') == 'HTTP_FILTER':
                                patch_value = patch.get('patch', {}).get('value', {})
                                if patch_value.get('name') == 'envoy.filters.http.local_ratelimit':
                                    typed_config = patch_value.get('typed_config', {})
                                    if typed_config and '@type' in typed_config:
                                        token_bucket = typed_config.get('token_bucket', {})
                                        if token_bucket:
                                            self.service_relations[service_name]['rateLimit']['requests_per_unit'] = token_bucket.get('max_tokens')
                                            
                                            # 转换填充间隔为时间单位
                                            fill_interval = token_bucket.get('fill_interval')
                                            if fill_interval and 's' in fill_interval:
                                                seconds = int(''.join(filter(str.isdigit, fill_interval)))
                                                if seconds == 60:
                                                    self.service_relations[service_name]['rateLimit']['unit'] = 'minute'
                                                else:
                                                    self.service_relations[service_name]['rateLimit']['unit'] = f'{seconds}秒'
                            
                            # 处理 VIRTUAL_HOST 配置
                            elif patch.get('applyTo') == 'VIRTUAL_HOST':
                                patch_value = patch.get('patch', {}).get('value', {})
                                rate_limits = patch_value.get('rate_limits', [])
                                for limit in rate_limits:
                                    for action in limit.get('actions', []):
                                        if 'request_headers' in action:
                                            header = action['request_headers']
                                            # 直接添加条件
                                            self.service_relations[service_name]['rateLimit']['conditions'].append({
                                                'type': 'header',
                                                'name': header.get('header_name'),
                                                'value': header.get('descriptor_key')
                                            })
                                            print(f"添加限流条件: {service_name} - {header.get('header_name')}")
    
    def get_service_details(self, service_name: str) -> Dict:
        """
        获取特定服务的详细配置
        
        参数:
            service_name: 服务名称
            
        返回:
            服务详细配置
        """
        if service_name in self.configurations:
            details = {
                'relations': self.service_relations.get(service_name, {
                    'incomingVirtualServices': [],
                    'subsets': [],
                    'rateLimit': {
                        'type': 'local',
                        'requests_per_unit': 3,
                        'unit': 'minute',
                        'conditions': []
                    }
                }),
                'configurations': self.configurations.get(service_name, {
                    'virtualServices': [],
                    'destinationRules': [],
                    'envoyFilters': []
                })
            }
            return details
        return {
            'relations': {
                'incomingVirtualServices': [],
                'subsets': [],
                'rateLimit': {
                    'type': 'local',
                    'requests_per_unit': 3,
                    'unit': 'minute',
                    'conditions': []
                }
            },
            'configurations': {
                'virtualServices': [],
                'destinationRules': [],
                'envoyFilters': []
            }
        }
    
    def extract_rate_limits(self) -> Dict:
        """
        提取所有服务的限流配置
        
        返回:
            限流配置
        """
        rate_limits = {}
        
        for service_name, relation in self.service_relations.items():
            if 'rateLimit' in relation and relation['rateLimit']['conditions']:
                rate_limits[service_name] = relation['rateLimit']
        
        return rate_limits
    
    def extract_traffic_routing(self) -> Dict:
        """
        提取所有服务的流量路由配置
        
        返回:
            流量路由配置
        """
        routing = {}
        
        for service_name, relation in self.service_relations.items():
            if 'subsets' in relation and relation['subsets']:
                routing[service_name] = {
                    'subsets': relation['subsets']
                }
        
        return routing
    
    def extract_fault_injection(self) -> Dict:
        """
        提取所有服务的故障注入配置
        
        返回:
            故障注入配置
        """
        fault_injection = {}
        
        for service_name, config in self.configurations.items():
            for vs in config['virtualServices']:
                for http_route in vs['spec'].get('http', []):
                    if 'fault' in http_route:
                        if service_name not in fault_injection:
                            fault_injection[service_name] = []
                        
                        fault_injection[service_name].append({
                            'virtualService': vs['metadata']['name'],
                            'fault': http_route['fault']
                        })
        
        return fault_injection


# 使用示例
if __name__ == "__main__":
    parser = IstioConfigParser()
    result = parser.parse_yaml_files('online-boutique-service.yaml', 'online-boutique.yaml')
    
    print("服务数量:", len(result['services']))
    print("服务关系数量:", len(result['serviceRelations']))
    
    # 打印限流配置
    rate_limits = parser.extract_rate_limits()
    print("\n限流配置:")
    for service, config in rate_limits.items():
        print(f"服务: {service}")
        print(f"  类型: {config['type']}")
        print(f"  速率: {config['requests_per_unit']} 请求/{config['unit']}")
        print(f"  条件数量: {len(config['conditions'])}")
        for condition in config['conditions']:
            print(f"    - {condition['type']}: {condition['name']} = {condition['value']}")
    
    # 打印流量路由配置
    routing = parser.extract_traffic_routing()
    print("\n流量路由配置:")
    for service, config in routing.items():
        print(f"服务: {service}")
        for subset in config['subsets']:
            print(f"  子集: {subset['name']}, 版本: {subset['version']}, 权重: {subset['weight']}%") 