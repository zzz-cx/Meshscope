import yaml
import os

def parse_yaml_files(service_file, config_file):
    # 1. 解析基础服务信息
    try:
        with open(service_file, 'r') as f:
            services_data = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading service file: {e}")
        return {
            'services': [],
            'serviceRelations': {},
            'configurations': {}
        }

    # 2. 解析服务列表
    services = []
    for item in services_data.get('items', []):
        if item.get('kind') == 'Service':
            service_name = item['metadata'].get('name')
            if service_name:
                services.append({
                    'name': service_name,
                    'namespace': item['metadata'].get('namespace', 'default'),
                    'type': 'service',
                    'ports': item['spec'].get('ports', []),
                    'selector': item['spec'].get('selector', {})
                })

    # 3. 解析服务配置和关系
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
            # 调试：打印YAML文件内容
            print(f"加载的YAML文件: {config_file}")
            print(f"YAML文件中有 {len(yaml_data.get('items', []))} 个资源项")
    except Exception as e:
        print(f"Error reading config file: {e}")
        return {
            'services': services,
            'serviceRelations': {},
            'configurations': {}
        }

    # 4. 解析服务关系和配置
    service_relations = {}
    configurations = {}
    subset_weights = {}  # 存储所有服务的子集权重
    service_aliases = {}  # 存储服务名称的别名映射，处理不同格式的服务名称

    # 初始化所有服务的关系和配置，确保包含所有服务
    service_names = set()
    for service in services:
        service_name = service['name']
        service_names.add(service_name)
        if service_name not in service_relations:
            service_relations[service_name] = {
                'incomingVirtualServices': [],
                'subsets': [],
                'rateLimit': [],  # 添加限流配置字段
                'gateways': []    # 添加网关配置字段
            }
        if service_name not in configurations:
            configurations[service_name] = {
                'virtualServices': [],
                'destinationRules': [],
                'envoyFilters': []  # 添加 EnvoyFilter 配置
            }
        subset_weights[service_name] = {}
        
        # 添加服务别名以处理不同格式的服务名
        service_aliases[service_name] = service_name
        service_aliases[f"{service_name}.{service['namespace']}"] = service_name
        service_aliases[f"{service_name}.{service['namespace']}.svc"] = service_name
        service_aliases[f"{service_name}.{service['namespace']}.svc.cluster.local"] = service_name

    # 检查是否有可能缺失的服务名，使用YAML文件中发现的进行补充
    for item in yaml_data.get('items', []):
        # 处理VirtualService
        if item.get('kind') == 'VirtualService':
            vs_name = item['metadata'].get('name')
            # 尝试从名称推断服务名
            if vs_name not in service_names:
                service_aliases[vs_name] = vs_name
                if vs_name not in service_relations:
                    service_relations[vs_name] = {'incomingVirtualServices': [], 'subsets': [], 'rateLimit': [], 'gateways': []}
                if vs_name not in configurations:
                    configurations[vs_name] = {'virtualServices': [], 'destinationRules': [], 'envoyFilters': []}
                subset_weights[vs_name] = {}
                
            # 从host中提取服务
            hosts = item['spec'].get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            for host in hosts:
                if not host:  # 跳过空值
                    continue
                base_service = host.split('.')[0]  # 基本服务名
                if base_service and base_service not in service_aliases:
                    service_aliases[host] = base_service
                    if base_service not in service_relations:
                        service_relations[base_service] = {'incomingVirtualServices': [], 'subsets': [], 'rateLimit': [], 'gateways': []}
                    if base_service not in configurations:
                        configurations[base_service] = {'virtualServices': [], 'destinationRules': [], 'envoyFilters': []}
                    subset_weights[base_service] = {}
                    
            # 特别处理：从路由目的地提取服务
            if 'http' in item['spec']:
                for route_rule in item['spec']['http']:
                    if 'route' in route_rule:
                        for route in route_rule['route']:
                            if 'destination' in route:
                                dest = route['destination']
                                if 'host' in dest:
                                    dest_host = dest['host']
                                    base_service = dest_host.split('.')[0]
                                    if base_service and base_service not in service_aliases:
                                        service_aliases[dest_host] = base_service
                                        if base_service not in service_relations:
                                            service_relations[base_service] = {'incomingVirtualServices': [], 'subsets': [], 'rateLimit': [], 'gateways': []}
                                        if base_service not in configurations:
                                            configurations[base_service] = {'virtualServices': [], 'destinationRules': [], 'envoyFilters': []}
                                        subset_weights[base_service] = {}
        
        # 处理DestinationRule
        elif item.get('kind') == 'DestinationRule':
            host = item['spec'].get('host', '')
            base_service = host.split('.')[0]  # 基本服务名
            if base_service and base_service not in service_aliases:
                service_aliases[host] = base_service
                if base_service not in service_relations:
                    service_relations[base_service] = {'incomingVirtualServices': [], 'subsets': [], 'rateLimit': [], 'gateways': []}
                if base_service not in configurations:
                    configurations[base_service] = {'virtualServices': [], 'destinationRules': [], 'envoyFilters': []}
                subset_weights[base_service] = {}

    # 打印发现的所有服务和别名
    print("\n服务名称映射:")
    for alias, service in service_aliases.items():
        print(f"  {alias} -> {service}")

    # 首先处理 VirtualService 来获取权重信息
    print("\n处理 VirtualService 配置:")
    for item in yaml_data.get('items', []):
        if item.get('kind') == 'VirtualService':
            vs_name = item['metadata'].get('name')
            print(f"找到 VirtualService: {vs_name}")
            
            # 添加网关处理逻辑
            gateways = item['spec'].get('gateways', [])
            if not isinstance(gateways, list):
                gateways = [gateways]
            
            print(f"  VirtualService {vs_name} 的 gateways: {gateways}")
            
            # 尝试确定此VirtualService对应的服务
            target_services = set()
            
            # 1. 从hosts中提取
            hosts = item['spec'].get('hosts', [])
            if not isinstance(hosts, list):
                hosts = [hosts]
            
            for host in hosts:
                if not host:  # 跳过空值
                    continue
                    
                # 尝试找到对应的服务名
                service_name = None
                if host in service_aliases:
                    service_name = service_aliases[host]
                else:
                    # 尝试基本匹配
                    base_name = host.split('.')[0]
                    if base_name in service_aliases:
                        service_name = service_aliases[base_name]
                
                if service_name:
                    target_services.add(service_name)
                    print(f"  从host {host} 映射到服务: {service_name}")
            
            # 2. 特殊情况：hosts为空，从VirtualService名称推断
            if not target_services and vs_name in service_aliases:
                service_name = service_aliases[vs_name]
                target_services.add(service_name)
                print(f"  从VirtualService名称 {vs_name} 映射到服务: {service_name}")
            
            # 3. 特殊情况：从http.route.destination中提取
            http_routes = item['spec'].get('http', [])
            
            # 如果还没找到目标服务，尝试从路由目的地提取
            route_services = set()
            dest_service_weights = {}  # 按服务存储权重信息
            
            for route_rule in http_routes:
                if 'route' in route_rule:
                    routes = route_rule['route']
                    print(f"  HTTP路由目的地数量: {len(routes)}")
                    
                    # 检查每个路由目的地
                    for route in routes:
                        if 'destination' in route:
                            dest = route['destination']
                            dest_host = dest.get('host', '')
                            
                            # 尝试找到目的地服务
                            dest_service = None
                            if dest_host in service_aliases:
                                dest_service = service_aliases[dest_host]
                            else:
                                # 尝试基本匹配
                                base_name = dest_host.split('.')[0]
                                if base_name in service_aliases:
                                    dest_service = service_aliases[base_name]
                            
                            print(f"  目的地host: {dest_host}, 映射到服务: {dest_service}")
                            
                            if dest_service:
                                route_services.add(dest_service)
                                
                                # 如果目标服务还不明确，则从路由中提取
                                if not target_services:
                                    target_services.add(dest_service)
                                
                                # 处理权重信息
                                subset = dest.get('subset')
                                if subset:
                                    weight = route.get('weight', 100)  # 默认权重为100
                                    print(f"  服务 {dest_service} 的 subset {subset} 权重: {weight}")
                                    
                                    # 确保目标服务的权重信息已初始化
                                    if dest_service not in subset_weights:
                                        subset_weights[dest_service] = {}
                                    
                                    subset_weights[dest_service][subset] = weight
            
            # 将VirtualService添加到所有目标服务的配置中
            for service_name in target_services:
                if service_name and service_name in configurations:
                    if not any(vs['metadata']['name'] == vs_name for vs in configurations[service_name]['virtualServices']):
                        configurations[service_name]['virtualServices'].append(item)
                        print(f"  将VirtualService {vs_name} 添加到服务 {service_name} 的配置中")

                    # 将网关信息添加到目标服务的关系中
                    for gateway in gateways:
                        if gateway not in [g['name'] for g in service_relations[service_name]['gateways']]:
                            gateway_info = {
                                'name': gateway,
                                'type': 'ingress',  # 默认为入口网关
                                'virtualService': vs_name
                            }
                            service_relations[service_name]['gateways'].append(gateway_info)
                            print(f"  将网关 {gateway} 添加到服务 {service_name} 的配置中")

    # 然后处理 DestinationRule 并应用权重
    print("\n处理 DestinationRule 配置:")
    for item in yaml_data.get('items', []):
        if item.get('kind') == 'DestinationRule':
            dr_name = item['metadata'].get('name')
            print(f"找到 DestinationRule: {dr_name}")
            
            host = item['spec'].get('host', '')
            
            # 尝试找到对应的服务名
            service_name = None
            if host in service_aliases:
                service_name = service_aliases[host]
            else:
                # 尝试基本匹配
                base_name = host.split('.')[0]
                if base_name in service_aliases:
                    service_name = service_aliases[base_name]
            
            print(f"  从 host {host} 映射到服务: {service_name}")
            
            if service_name:
                # 添加到配置
                if not any(dr['metadata']['name'] == dr_name for dr in configurations[service_name]['destinationRules']):
                    configurations[service_name]['destinationRules'].append(item)
                
                # 添加子集信息
                # 清除现有的子集并添加新的
                service_relations[service_name]['subsets'] = []
                
                subsets = item['spec'].get('subsets', [])
                print(f"  子集数量: {len(subsets)}")
                
                for subset in subsets:
                    subset_name = subset['name']
                    # 确保有权重信息
                    if service_name not in subset_weights:
                        subset_weights[service_name] = {}
                    
                    subset_weight = subset_weights.get(service_name, {}).get(subset_name, 0)
                    
                    print(f"  服务 {service_name} 的 subset {subset_name} 权重: {subset_weight}")
                    
                    subset_info = {
                        'name': subset_name,
                        'version': subset['labels'].get('version'),
                        'labels': subset['labels'],
                        'weight': subset_weight  # 从预先收集的权重中获取
                    }
                    service_relations[service_name]['subsets'].append(subset_info)

    # 解析 EnvoyFilter 配置
    print("\n处理 EnvoyFilter 配置:")
    for item in yaml_data.get('items', []):
        if item.get('kind') == 'EnvoyFilter':
            ef_name = item['metadata'].get('name')
            print(f"找到 EnvoyFilter: {ef_name}")
            
            workload_selector = item['spec'].get('workloadSelector', {})
            if workload_selector and 'labels' in workload_selector:
                app_label = workload_selector['labels'].get('app')
                
                # 尝试找到对应的服务名
                service_name = None
                if app_label in service_aliases:
                    service_name = service_aliases[app_label]
                
                print(f"  从 label app={app_label} 映射到服务: {service_name}")
                
                if service_name and service_name in service_relations:
                    # 解析限流配置
                    rate_limit = {
                        'type': 'local',
                        'requests_per_unit': None,
                        'unit': None,
                        'conditions': []
                    }
                    
                    # 提取限流规则
                    for patch in item['spec'].get('configPatches', []):
                        if patch.get('applyTo') == 'HTTP_FILTER':
                            patch_value = patch.get('patch', {}).get('value', {})
                            if patch_value.get('name') == 'envoy.filters.http.local_ratelimit':
                                typed_config = patch_value.get('typed_config', {})
                                if typed_config and '@type' in typed_config:
                                    token_bucket = typed_config.get('token_bucket', {})
                                    if token_bucket:
                                        rate_limit['requests_per_unit'] = token_bucket.get('max_tokens')
                                        
                                        # 转换填充间隔为时间单位
                                        fill_interval = token_bucket.get('fill_interval')
                                        if fill_interval and 's' in fill_interval:
                                            seconds = int(''.join(filter(str.isdigit, fill_interval)))
                                            if seconds == 60:
                                                rate_limit['unit'] = 'minute'
                                            else:
                                                rate_limit['unit'] = f'{seconds}秒'
                        
                        elif patch.get('applyTo') == 'VIRTUAL_HOST':
                            patch_value = patch.get('patch', {}).get('value', {})
                            rate_limits = patch_value.get('rate_limits', [])
                            for limit in rate_limits:
                                for action in limit.get('actions', []):
                                    if 'request_headers' in action:
                                        header = action['request_headers']
                                        rate_limit['conditions'].append({
                                            'type': 'header',
                                            'name': header.get('header_name'),
                                            'value': header.get('descriptor_key')
                                        })
                    
                    # 只有当成功解析到限流规则时才保存
                    if rate_limit['requests_per_unit'] is not None and rate_limit['unit'] is not None:
                        service_relations[service_name]['rateLimit'].append(rate_limit)
                        configurations[service_name]['envoyFilters'].append(item)
                        print(f"  添加限流规则: {rate_limit}")

    # 打印调试信息，查看权重值
    print("\n最终服务子集权重:")
    for service_name in service_relations:
        if service_relations[service_name]['subsets']:
            print(f"Service {service_name} subset weights:")
            for subset in service_relations[service_name]['subsets']:
                print(f"  {subset['name']}: {subset['weight']}%")

    return {
        'services': services,
        'serviceRelations': service_relations,
        'configurations': configurations
    }

def get_service_details(service_name):
    """获取特定服务的详细配置"""
    data = parse_yaml_files('online-boutique-service.yaml', 'online-boutique.yaml')
    
    if service_name in data['configurations']:
        details = {
            'relations': data['serviceRelations'].get(service_name, {
                'incomingVirtualServices': [],
                'subsets': [],
                'gateways': []  # 添加网关字段
            }),
            'configurations': data['configurations'].get(service_name, {
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
            'gateways': []  # 添加网关字段
        },
        'configurations': {
            'virtualServices': [],
            'destinationRules': [],
            'envoyFilters': []
        }
    }

# 如果直接运行此文件，则执行示例解析
if __name__ == "__main__":
    # 检查文件是否存在
    service_file = 'online-boutique-service.yaml'
    config_file = 'online-boutique.yaml'
    
    if not os.path.exists(service_file):
        print(f"警告: 服务定义文件 {service_file} 不存在")
    else:
        print(f"服务定义文件 {service_file} 存在")
        
    if not os.path.exists(config_file):
        print(f"警告: 配置文件 {config_file} 不存在")
    else:
        print(f"配置文件 {config_file} 存在")
    
    # 执行解析
    parse_yaml_files(service_file, config_file)