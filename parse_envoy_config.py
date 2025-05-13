import json
import os
import logging
import sys

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parse_envoy_config.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("parse_envoy_config")

def parse_routes_config(routes_file='istio-config/routes.json'):
    """解析路由配置文件，提取服务关系"""
    service_relations = {}
    discovered_services = set()  # 用于收集发现的所有服务
    
    try:
        logger.info(f"开始解析路由配置文件: {routes_file}")
        
        # 检查文件是否存在
        if not os.path.exists(routes_file):
            logger.error(f"路由配置文件不存在: {routes_file}")
            return None
            
        with open(routes_file, 'r') as f:
            routes_config = json.load(f)
        
        logger.info(f"成功加载路由配置，配置项数量: {len(routes_config)}")
        logger.debug(f"配置类型: {type(routes_config)}")
        
        # 转储前10行配置到日志中以便于调试
        logger.debug(f"配置文件前200个字符: {json.dumps(routes_config)[:200]}...")
        
        # 第一次遍历：收集所有服务名称
        for route_config in routes_config:
            if 'virtualHosts' not in route_config:
                continue
                
            for vhost in route_config['virtualHosts']:
                domains = vhost.get('domains', [])
                
                # 从域名中提取服务名称
                for domain in domains:
                    domain_parts = domain.split('.')
                    if domain_parts:
                        service_name = domain_parts[0]
                        if service_name and service_name != '*':  # 排除通配符
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

        logger.info(f"发现的服务: {discovered_services}")
        
        # 初始化所有发现的服务的关系结构
        for service in discovered_services:
            service_relations[service] = {
                'inbound': [],    # 入站路由
                'outbound': [],   # 出站路由
                'weights': {}     # 版本权重
            }
        
        # 遍历所有路由配置
        for i, route_config in enumerate(routes_config):
            logger.debug(f"处理路由配置项 #{i+1}")
            
            # 首先检查配置中是否有权重信息
            if 'metadata' in route_config:
                logger.debug(f"配置项 #{i+1} 包含 metadata")
                metadata = route_config.get('metadata', {})
                filter_metadata = metadata.get('filter_metadata', {})
                
                # 检查istio特定的metadata
                if 'istio' in filter_metadata:
                    istio_metadata = filter_metadata['istio']
                    logger.debug(f"Istio metadata: {istio_metadata}")
                    
                    # 检查是否有subset或version信息
                    if 'subset' in istio_metadata:
                        subset = istio_metadata['subset']
                        logger.info(f"发现subset: {subset}")
                        
                        # 尝试提取服务名称
                        service_name = None
                        if 'host' in route_config:
                            host = route_config['host']
                            service_parts = host.split('.')
                            if service_parts and service_parts[0] in discovered_services:
                                service_name = service_parts[0]
                                logger.debug(f"从host字段解析服务名: {service_name}")
                        
                        # 如果找到服务名和subset，记录权重信息
                        if service_name:
                            # 在这种情况下，我们没有明确的权重值，可以设置一个默认值或检查其他字段
                            weight = istio_metadata.get('weight', 100)  # 默认100%
                            if subset not in service_relations[service_name]['weights']:
                                service_relations[service_name]['weights'][subset] = weight
                                logger.info(f"添加服务 {service_name} 的subset {subset} 权重: {weight}")
            
            # 常规的virtualHosts解析
            if 'virtualHosts' not in route_config:
                logger.debug(f"配置项 #{i+1} 中没有 virtualHosts 字段，跳过")
                continue
                
            logger.debug(f"配置项 #{i+1} 中 virtualHosts 数量: {len(route_config['virtualHosts'])}")
                
            for j, vhost in enumerate(route_config['virtualHosts']):
                logger.debug(f"处理配置项 #{i+1} 中的 virtualHost #{j+1}")
                
                # 提取服务名称
                domains = vhost.get('domains', [])
                logger.debug(f"virtualHost #{j+1} 的 domains: {domains}")
                
                service_name = None
                for domain in domains:
                    domain_parts = domain.split('.')
                    if domain_parts and domain_parts[0] in discovered_services:
                        service_name = domain_parts[0]
                        logger.debug(f"找到目标服务: {service_name}")
                        break
                
                if not service_name:
                    logger.debug(f"virtualHost #{j+1} 中没有找到目标服务，跳过")
                    continue
                
                # 分析路由规则
                routes = vhost.get('routes', [])
                logger.debug(f"virtualHost #{j+1} 中路由规则数量: {len(routes)}")
                
                for k, route in enumerate(routes):
                    logger.debug(f"处理路由规则 #{k+1}")
                    
                    # 检查路由元数据中是否有subset信息
                    if 'metadata' in route:
                        route_metadata = route.get('metadata', {})
                        logger.debug(f"路由规则 #{k+1} 包含元数据: {route_metadata}")
                        
                        # 检查是否包含subset信息
                        for key, value in route_metadata.items():
                            if 'subset' in key.lower() or 'version' in key.lower():
                                subset = value
                                logger.info(f"从元数据解析到subset: {subset}")
                                if subset and service_name:
                                    # 这里我们同样不知道权重，设定一个默认值
                                    if subset not in service_relations[service_name]['weights']:
                                        service_relations[service_name]['weights'][subset] = 100  # 默认100%
                                        logger.info(f"从元数据添加服务 {service_name} 的subset {subset} 权重: 100")
                    
                    if 'route' not in route:
                        logger.debug(f"路由规则 #{k+1} 中没有 route 字段，跳过")
                        continue
                    
                    route_info = route['route']
                    logger.debug(f"路由信息类型: {type(route_info)}")
                    
                    # 处理加权路由
                    if 'weightedClusters' in route_info:
                        logger.debug(f"发现加权集群路由")
                        clusters = route_info['weightedClusters'].get('clusters', [])
                        logger.debug(f"加权集群数量: {len(clusters)}")
                        
                        weights = {}
                        for cluster in clusters:
                            # 输出完整集群信息以便调试
                            logger.debug(f"集群完整信息: {cluster}")
                            
                            # 从集群名称中提取版本信息
                            # 格式: outbound|9080|v2|reviews.default.svc.cluster.local
                            cluster_name = cluster['name']
                            logger.debug(f"集群名称: {cluster_name}")
                            
                            # 检查集群metadata中是否有subset信息
                            if 'metadata' in cluster:
                                cluster_metadata = cluster.get('metadata', {})
                                for key, value in cluster_metadata.items():
                                    if 'subset' in key.lower() or 'version' in key.lower():
                                        subset = value
                                        weight = cluster.get('weight', 0)
                                        logger.info(f"从集群元数据解析到subset: {subset}, 权重: {weight}")
                                        weights[subset] = weight
                            
                            # 从名称解析版本
                            parts = cluster_name.split('|')
                            if len(parts) >= 4:
                                version = parts[2]
                                weight = cluster.get('weight', 0)
                                weights[version] = weight
                                logger.debug(f"解析到版本 {version}, 权重 {weight}")
                            else:
                                logger.debug(f"无法从集群名称解析版本信息: {cluster_name}")
                                
                                # 尝试其他格式的解析
                                if '.' in cluster_name:
                                    # 可能是 service.subset.namespace 格式
                                    name_parts = cluster_name.split('.')
                                    if len(name_parts) >= 2:
                                        potential_subset = name_parts[1]
                                        if potential_subset not in ['svc', 'service', 'default', 'namespace']:
                                            logger.debug(f"尝试从另一种格式解析subset: {potential_subset}")
                                            weight = cluster.get('weight', 0)
                                            weights[potential_subset] = weight
                                
                        if weights:
                            service_relations[service_name]['weights'] = weights
                            logger.info(f"服务 {service_name} 的版本权重: {weights}")
                        else:
                            logger.warning(f"未能从加权集群中解析到任何版本权重")
                    
                    # 处理单一集群路由
                    elif 'cluster' in route_info:
                        cluster_name = route_info['cluster']
                        logger.debug(f"发现单一集群路由: {cluster_name}")
                        
                        # 检查是否包含subset信息
                        if '.' in cluster_name:
                            name_parts = cluster_name.split('.')
                            if len(name_parts) >= 2:
                                potential_subset = name_parts[1]
                                if potential_subset not in ['svc', 'service', 'default', 'namespace']:
                                    logger.debug(f"从集群名称解析potential subset: {potential_subset}")
                                    # 对于单一集群，我们没有明确的权重，假设100%
                                    if service_name and potential_subset not in service_relations[service_name]['weights']:
                                        service_relations[service_name]['weights'][potential_subset] = 100
                                        logger.info(f"添加服务 {service_name} 的subset {potential_subset} 权重: 100")
                        
                        if cluster_name.startswith('outbound|'):
                            parts = cluster_name.split('|')
                            if len(parts) >= 4:
                                target_service_fqdn = parts[3]
                                target_service = target_service_fqdn.split('.')[0]
                                logger.debug(f"目标服务FQDN: {target_service_fqdn}, 服务名: {target_service}")
                                
                                # 检查是否包含subset信息
                                if len(parts) >= 3:
                                    potential_subset = parts[2]
                                    if potential_subset not in ['v1', 'v2', 'v3']:  # 常见版本名
                                        logger.debug(f"从集群名称解析potential subset: {potential_subset}")
                                        if service_name and potential_subset not in service_relations[service_name]['weights']:
                                            service_relations[service_name]['weights'][potential_subset] = 100
                                            logger.info(f"添加服务 {service_name} 的subset {potential_subset} 权重: 100")
                                
                                if target_service in discovered_services:
                                    outbound_route = {
                                        'service': target_service,
                                        'port': parts[1]
                                    }
                                    service_relations[service_name]['outbound'].append(outbound_route)
                                    logger.info(f"添加出站路由: {service_name} -> {target_service}:{parts[1]}")
                                else:
                                    logger.debug(f"目标服务 {target_service} 不在目标服务列表中，跳过")
                            else:
                                logger.debug(f"无法从集群名称解析服务信息: {cluster_name}")
        
        # 保存分析结果
        output_dir = os.path.dirname(routes_file)
        output_file = os.path.join(output_dir, 'service-routes.json')
        
        logger.info(f"保存服务路由分析结果到 {output_file}")
        os.makedirs(output_dir, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(service_relations, f, indent=2)
        
        # 打印分析结果
        logger.info("服务路由分析结果摘要:")
        for service_name, relations in service_relations.items():
            logger.info(f"\n服务 {service_name}:")
            if relations['weights']:
                logger.info("版本权重:")
                for version, weight in relations['weights'].items():
                    logger.info(f"  {version}: {weight}%")
            if relations['outbound']:
                logger.info("出站路由:")
                for route in relations['outbound']:
                    logger.info(f"  -> {route['service']} (端口 {route['port']})")
            if not relations['weights'] and not relations['outbound']:
                logger.warning(f"服务 {service_name} 未解析到任何路由信息")
        
        logger.info(f"完成服务关系解析，共发现 {len(discovered_services)} 个服务")
        return service_relations
    
    except Exception as e:
        logger.exception(f"解析路由配置时发生错误: {e}")
        return None

def get_service_data_plane_config(service_name):
    """获取特定服务的数据平面配置"""
    logger.info(f"获取服务 {service_name} 的数据平面配置")
    service_relations = parse_routes_config()
    
    if not service_relations or service_name not in service_relations:
        logger.warning(f"未找到服务 {service_name} 的关系数据")
        return {
            'inbound': [],
            'outbound': [],
            'weights': {}
        }
    
    relations = service_relations[service_name]
    result = {
        'inbound': [],  # 暂时为空，因为入站信息需要从其他配置获取
        'outbound': [
            {
                'service': route['service'],
                'port': route['port']
            } for route in relations['outbound']
        ],
        'weights': relations['weights']
    }
    
    logger.info(f"返回服务 {service_name} 的数据平面配置: {json.dumps(result, indent=2)}")
    return result

def examine_config_file(routes_file='istio-config/routes.json'):
    """检查配置文件结构"""
    try:
        logger.info(f"检查配置文件: {routes_file}")
        
        if not os.path.exists(routes_file):
            logger.error(f"配置文件不存在: {routes_file}")
            return
            
        with open(routes_file, 'r') as f:
            routes_config = json.load(f)
            
        logger.info(f"配置文件类型: {type(routes_config)}")
        logger.info(f"配置项数量: {len(routes_config) if isinstance(routes_config, list) else '不是列表'}")
        
        # 找一下配置中所有出现了subset或version的地方
        found_subset = False
        
        # 使用递归函数深度搜索配置中的subset字段
        def find_subset_in_dict(d, path="root"):
            nonlocal found_subset
            if isinstance(d, dict):
                for k, v in d.items():
                    if 'subset' in str(k).lower() or 'version' in str(k).lower():
                        logger.info(f"在路径 {path}.{k} 处找到可能的subset/version字段: {v}")
                        found_subset = True
                    find_subset_in_dict(v, f"{path}.{k}")
            elif isinstance(d, list):
                for i, item in enumerate(d):
                    find_subset_in_dict(item, f"{path}[{i}]")
        
        # 在整个配置中搜索subset
        if isinstance(routes_config, list):
            for i, item in enumerate(routes_config):
                find_subset_in_dict(item, f"routes_config[{i}]")
        else:
            find_subset_in_dict(routes_config)
            
        if not found_subset:
            logger.warning("在整个配置中未找到任何subset或version字段")
        
        # 检查基本结构
        if isinstance(routes_config, list):
            for i, item in enumerate(routes_config[:3]):  # 只检查前三项
                logger.info(f"配置项 #{i+1} 的顶级键: {list(item.keys())}")
                
                if 'virtualHosts' in item:
                    vh_count = len(item['virtualHosts'])
                    logger.info(f"配置项 #{i+1} 包含 {vh_count} 个虚拟主机")
                    
                    # 检查第一个虚拟主机
                    if vh_count > 0:
                        vhost = item['virtualHosts'][0]
                        logger.info(f"第一个虚拟主机的键: {list(vhost.keys())}")
                        
                        if 'domains' in vhost:
                            logger.info(f"域名: {vhost['domains']}")
                        
                        if 'routes' in vhost:
                            routes_count = len(vhost['routes'])
                            logger.info(f"路由规则数量: {routes_count}")
                            
                            if routes_count > 0:
                                route = vhost['routes'][0]
                                logger.info(f"第一个路由规则的键: {list(route.keys())}")
                                
                                if 'route' in route:
                                    route_info = route['route']
                                    logger.info(f"路由信息的键: {list(route_info.keys())}")
                                    
                                    # 检查是否有weightedClusters
                                    if 'weightedClusters' in route_info:
                                        clusters = route_info['weightedClusters'].get('clusters', [])
                                        logger.info(f"第一个路由包含 {len(clusters)} 个加权集群")
                                        
                                        if clusters:
                                            logger.info(f"第一个集群: {clusters[0]}")
                                    elif 'cluster' in route_info:
                                        logger.info(f"单一集群: {route_info['cluster']}")
        else:
            logger.info(f"配置文件内容示例: {json.dumps(routes_config)[:500]}...")
            
    except Exception as e:
        logger.exception(f"检查配置文件时发生错误: {e}")

if __name__ == '__main__':
    # 检查配置文件结构
    examine_config_file()
    # 解析路由配置
    parse_routes_config() 