import os
import sys
import logging
import json
from typing import Dict, Any, List, Optional

# 添加项目根目录到 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from istio_config_parser.models.data_structures import (
    ControlPlaneResult,
    DataPlaneResult,
    BaseService,
    ServiceRelation,
    ServiceConfiguration
)
from istio_config_parser.traffic_management.route_parser import parse_routes
from istio_config_parser.traffic_management.canary_parser import parse_canary
from istio_config_parser.traffic_management.ratelimit_parser import parse_ratelimit
from istio_config_parser.traffic_management.service_parser import parse_services
from istio_config_parser.utils.file_utils import load_yaml_file, load_json_file
from istio_config_parser.traffic_management.circuit_breaker_parser import parse_circuit_breaker

# 新增：导入统一解析器
from istio_config_parser.parsers.unified_parser import UnifiedParser
from istio_config_parser.models.ir_models import SystemIR

logger = logging.getLogger(__name__)

def _load_config_files(config_dir: str, resource_type: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    加载指定资源类型的所有配置文件
    :param config_dir: 配置目录
    :param resource_type: 资源类型（services/virtualservices等）
    :param namespace: 可选的命名空间过滤
    :return: 配置字典
    """
    configs = {'items': []}
    resource_dir = os.path.join(config_dir, resource_type)
    
    if not os.path.exists(resource_dir):
        logger.warning(f"资源目录不存在: {resource_dir}")
        return configs
    
    try:
        # 如果指定了命名空间，只读取该命名空间的配置
        if namespace:
            ns_dir = os.path.join(resource_dir, namespace)
            if os.path.isdir(ns_dir):
                for config_file in os.listdir(ns_dir):
                    if config_file.endswith('.yaml'):
                        config_path = os.path.join(ns_dir, config_file)
                        config = load_yaml_file(config_path)
                        if config:
                            configs['items'].append(config)
        else:
            # 遍历所有命名空间目录
            for ns in os.listdir(resource_dir):
                ns_dir = os.path.join(resource_dir, ns)
                if os.path.isdir(ns_dir):
                    for config_file in os.listdir(ns_dir):
                        if config_file.endswith('.yaml'):
                            config_path = os.path.join(ns_dir, config_file)
                            config = load_yaml_file(config_path)
                            if config:
                                configs['items'].append(config)
    except Exception as e:
        logger.error(f"加载配置文件时出错: {str(e)}")
        return {'items': []}
    
    return configs

def parse_control_plane_from_dir(config_dir: str = 'istio_control_config', namespace: Optional[str] = None) -> ControlPlaneResult:
    """
    从配置目录解析控制平面配置
    :param config_dir: 配置目录
    :param namespace: 可选的命名空间过滤
    :return: 控制平面配置结果
    """
    # 初始化结果结构
    result: ControlPlaneResult = {
        'services': [],
        'serviceRelations': {},
        'configurations': {}
    }
    
    # 1. 加载相关配置
    services_config = _load_config_files(config_dir, 'services', namespace)
    vs_config = _load_config_files(config_dir, 'virtualservices', namespace)
    dr_config = _load_config_files(config_dir, 'destinationrules', namespace)
    ef_config = _load_config_files(config_dir, 'envoyfilters', namespace)
    # 2. 解析服务配置
    result['services'] = parse_services(services_config)
    
    # 3. 解析路由规则配置
    routes = parse_routes(vs_config)
    
    # 4. 解析灰度发布配置
    canary = parse_canary(dr_config, vs_config)
    # 5. 解析熔断配置
    circuit_breakers = parse_circuit_breaker(dr_config)
    
    # 6. 解析限流配置
    ratelimits = parse_ratelimit(ef_config)
    
    # 7. 合并所有服务的关系和配置
    all_services = set()
    all_services.update(routes.keys())
    all_services.update(canary.keys())
    all_services.update(ratelimits.keys())
    all_services.update(circuit_breakers.keys())

    for service in all_services:
        result['serviceRelations'][service] = {
            'incomingVirtualServices': routes.get(service, {}).get('inbound', []),
            'subsets': canary.get(service, {}).get('subsets', []),
            'rateLimit': ratelimits.get(service, []),
            'gateways': routes.get(service, {}).get('gateways', []),
            'weights': canary.get(service, {}).get('weights', {}),
            'circuitBreaker': circuit_breakers.get(service, {})
        }
        
        result['configurations'][service] = {
            'virtualServices': routes.get(service, {}).get('inbound', []),
            'destinationRules': canary.get(service, {}).get('subsets', []),
            'envoyFilters': ratelimits.get(service, []),
            'weights': canary.get(service, {}).get('weights', {}),
            'circuitBreaker': circuit_breakers.get(service, {})
        }
    
    return result

def parse_data_plane_from_dir(config_dir: str = 'istio_control_config') -> DataPlaneResult:
    """
    从配置目录解析数据平面配置
    :param config_dir: 配置目录
    :return: 数据平面配置结果
    """
    routes_json = os.path.join(config_dir, 'routes.json')
    if os.path.exists(routes_json):
        routes = load_json_file(routes_json)
        service_relations = parse_routes(routes, is_data_plane=True)
        return {'serviceRelations': service_relations}
    return {'serviceRelations': {}}


def parse_unified_from_dir(
    control_plane_dir: str = 'istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_monitor/istio_sidecar_config',
    namespace: Optional[str] = None
) -> SystemIR:
    """
    使用统一解析器从配置目录解析控制平面和数据平面配置，生成中间表示（IR）
    
    Args:
        control_plane_dir: 控制平面配置目录
        data_plane_dir: 数据平面配置目录（sidecar配置）
        namespace: 可选的命名空间过滤
        
    Returns:
        系统级IR模型
    """
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cp_dir = os.path.join(current_dir, control_plane_dir)
    dp_dir = os.path.join(current_dir, data_plane_dir)
    
    # 加载控制平面配置
    logger.info("加载控制平面配置...")
    control_plane_configs = {
        'services': _load_config_files(cp_dir, 'services', namespace),
        'virtual_services': _load_config_files(cp_dir, 'virtualservices', namespace),
        'destination_rules': _load_config_files(cp_dir, 'destinationrules', namespace),
        'envoy_filters': _load_config_files(cp_dir, 'envoyfilters', namespace)
    }
    
    # 加载数据平面配置
    logger.info("加载数据平面配置...")
    data_plane_configs = {}
    
    # 加载routes.json
    routes_file = os.path.join(dp_dir, 'routes.json')
    if os.path.exists(routes_file):
        data_plane_configs['routes'] = load_json_file(routes_file)
    
    # 加载clusters.json
    clusters_file = os.path.join(dp_dir, 'clusters.json')
    if os.path.exists(clusters_file):
        data_plane_configs['clusters'] = load_json_file(clusters_file)
    
    # 加载listeners.json
    listeners_file = os.path.join(dp_dir, 'listeners.json')
    if os.path.exists(listeners_file):
        data_plane_configs['listeners'] = load_json_file(listeners_file)
    
    # 使用统一解析器
    parser = UnifiedParser()
    system_ir = parser.parse_align_and_build_ir(control_plane_configs, data_plane_configs)
    
    return system_ir


def save_ir_to_file(system_ir: SystemIR, output_file: str):
    """
    将IR保存到文件
    
    Args:
        system_ir: 系统级IR
        output_file: 输出文件路径
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(system_ir.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info(f"IR已保存到: {output_file}")

if __name__ == "__main__":
    import argparse
    
    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 命令行参数
    parser_cli = argparse.ArgumentParser(description='Istio配置解析器')
    parser_cli.add_argument('--mode', choices=['legacy', 'unified'], default='unified',
                           help='解析模式：legacy（旧版）或 unified（统一解析器）')
    parser_cli.add_argument('--namespace', type=str, default=None,
                           help='命名空间过滤')
    parser_cli.add_argument('--output', type=str, default=None,
                           help='输出文件路径（仅unified模式）')
    args = parser_cli.parse_args()
    
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.mode == 'unified':
        print("\n" + "="*80)
        print("使用统一解析器（Unified Parser）")
        print("="*80)
        
        # 使用统一解析器
        system_ir = parse_unified_from_dir(namespace=args.namespace)
        
        # 打印摘要
        summary = system_ir.get_summary()
        print(f"\n系统级摘要:")
        print(f"  总服务数: {summary['total_services']}")
        print(f"  一致的服务: {summary['consistent_services']}")
        print(f"  不一致的服务: {summary['inconsistent_services']}")
        print(f"  一致性比例: {summary['consistency_rate']:.2%}")
        print(f"  总问题数: {summary['total_issues']}")
        print(f"  错误数: {summary['total_errors']}")
        print(f"  警告数: {summary['total_warnings']}")
        
        # 打印每个服务的详细信息
        print(f"\n服务详情:")
        for service_ir in system_ir.get_all_services():
            print(f"\n服务: {service_ir.namespace}.{service_ir.service_name}")
            print(f"  一致性状态: {service_ir.get_consistency_status().value}")
            print(f"  功能配置数: {len(service_ir.functions)}")
            
            for func_type, func_ir in service_ir.functions.items():
                print(f"\n  功能: {func_type}")
                print(f"    状态: {func_ir.consistency_status.value}")
                print(f"    错误: {func_ir.get_error_count()}")
                print(f"    警告: {func_ir.get_warning_count()}")
                
                if func_ir.has_issues():
                    print(f"    问题列表:")
                    for issue in func_ir.issues:
                        print(f"      - [{issue.severity}] {issue.field_path}")
                        print(f"        控制平面: {issue.control_plane_value}")
                        print(f"        数据平面: {issue.data_plane_value}")
                        if issue.description:
                            print(f"        描述: {issue.description}")
        
        # 如果指定了输出文件，保存IR
        if args.output:
            save_ir_to_file(system_ir, args.output)
            print(f"\n中间表示（IR）已保存到: {args.output}")
    
    else:
        print("\n" + "="*80)
        print("使用旧版解析器（Legacy Parser）")
        print("="*80)
        
        config_dir = os.path.join(current_dir, 'istio_control_config')
        
        # 示例用法
        namespace = args.namespace or "online-boutique"  # 可以指定要解析的命名空间
        control_plane = parse_control_plane_from_dir(config_dir, namespace)
        data_plane = parse_data_plane_from_dir(config_dir)
        
        # 打印控制平面配置
        print(f"\n命名空间 {namespace} 的控制平面配置：")
        for service in control_plane['services']:
            print(f"\n服务 {service['name']}:")
            print(f"  命名空间: {service['namespace']}")
            print(f"  类型: {service['type']}")
            print("  端口配置:")
            for port in service['ports']:
                print(f"    - 名称: {port['name']}")
                print(f"      端口: {port['port']}")
                print(f"      目标端口: {port['targetPort']}")
                print(f"      协议: {port['protocol']}")
            print(f"  选择器: {service['selector']}")
            print(f"  标签: {service['labels']}")
            print(f"  注解: {service['annotations']}")
            print(f"  集群IP: {service['clusterIP']}")
            print(f"  会话亲和性: {service['sessionAffinity']}")
            
            # 打印服务关系
            relations = control_plane['serviceRelations'].get(service['name'], {})
            print("\n  服务关系:")
            print("  入站路由:")
            for vs in relations.get('incomingVirtualServices', []):
                print(f"    - 名称: {vs['name']}")
                print(f"      命名空间: {vs['namespace']}")
                print(f"      规则数: {len(vs['rules'])}")
            
            print("  子集和权重:")
            # 获取所有子集
            subsets = {subset['name']: subset for subset in relations.get('subsets', [])}
            # 获取所有权重
            weights = relations.get('weights', {})
            
            # 合并显示子集和权重信息
            for subset_name, subset in subsets.items():
                print(f"    - 子集: {subset['name']}")
                print(f"      版本: {subset['version']}")
                print(f"      标签: {subset['labels']}")
                # 显示对应的权重信息
                if subset_name in weights:
                    weight_info = weights[subset_name]
                    print(f"      权重: {weight_info['weight']}")
                    print(f"      命名空间: {weight_info['namespace']}")
                else:
                    print("      权重: 未配置")
            
            print("  限流规则:")
            for limit in relations.get('rateLimit', []):
                print(f"    - 类型: {limit['type']}")
                print(f"      请求数: {limit['requests_per_unit']}")
                print(f"      时间单位: {limit['unit']}")
                print(f"      条件: {limit['conditions']}")
            
            print("  网关:")
            for gateway in relations.get('gateways', []):
                print(f"    - 名称: {gateway['name']}")
                print(f"      类型: {gateway['type']}")
                print(f"      虚拟服务: {gateway['virtualService']}")
                print(f"      命名空间: {gateway['namespace']}")
            
            print("  熔断配置:")
            # 显示全局熔断配置
            if relations.get('circuitBreaker'):
                circuit_breaker = relations['circuitBreaker']
                
                # 显示全局熔断配置
                if circuit_breaker.get('global_'):
                    print("    全局配置:")
                    global_policy = circuit_breaker['global_']
                    if global_policy and 'connectionPool' in global_policy:
                        cp = global_policy['connectionPool']
                        print("      连接池:")
                        if 'http' in cp:
                            print(f"        HTTP最大等待请求数: {cp['http'].get('http1MaxPendingRequests')}")
                            print(f"        HTTP最大请求数: {cp['http'].get('http2MaxRequests')}")
                            print(f"        每连接最大请求数: {cp['http'].get('maxRequestsPerConnection')}")
                            print(f"        最大重试次数: {cp['http'].get('maxRetries')}")
                        if 'tcp' in cp:
                            print(f"        TCP最大连接数: {cp['tcp'].get('maxConnections')}")
                            print(f"        连接超时: {cp['tcp'].get('connectTimeout')}")
                    
                    if global_policy and 'outlierDetection' in global_policy:
                        od = global_policy['outlierDetection']
                        print("      异常检测:")
                        print(f"        基础驱逐时间: {od.get('baseEjectionTime')}")
                        print(f"        连续5xx错误数: {od.get('consecutive5xxErrors')}")
                        print(f"        检测间隔: {od.get('interval')}")
                        print(f"        最大驱逐百分比: {od.get('maxEjectionPercent')}")
                        print(f"        最小健康百分比: {od.get('minHealthPercent')}")
                
                # 显示子集的熔断配置
                if circuit_breaker.get('subsets'):
                    for subset_name, subset_policy in circuit_breaker['subsets'].items():
                        # 跳过null配置
                        if subset_policy is None:
                            print(f"\n    子集 {subset_name} 配置: 未配置")
                            continue
                            
                        print(f"\n    子集 {subset_name} 配置:")
                        if subset_policy and 'connectionPool' in subset_policy:
                            cp = subset_policy['connectionPool']
                            print("      连接池:")
                            if 'http' in cp:
                                print(f"        HTTP最大等待请求数: {cp['http'].get('http1MaxPendingRequests')}")
                                print(f"        HTTP最大请求数: {cp['http'].get('http2MaxRequests')}")
                                print(f"        每连接最大请求数: {cp['http'].get('maxRequestsPerConnection')}")
                                print(f"        最大重试次数: {cp['http'].get('maxRetries')}")
                            if 'tcp' in cp:
                                print(f"        TCP最大连接数: {cp['tcp'].get('maxConnections')}")
                                print(f"        连接超时: {cp['tcp'].get('connectTimeout')}")
                        
                        if subset_policy and 'outlierDetection' in subset_policy:
                            od = subset_policy['outlierDetection']
                            print("      异常检测:")
                            print(f"        基础驱逐时间: {od.get('baseEjectionTime')}")
                            print(f"        连续5xx错误数: {od.get('consecutive5xxErrors')}")
                            print(f"        检测间隔: {od.get('interval')}")
                            print(f"        最大驱逐百分比: {od.get('maxEjectionPercent')}")
                            print(f"        最小健康百分比: {od.get('minHealthPercent')}")
        
        # 打印数据平面配置
        print("\n数据平面配置：")
        for service, relations in data_plane['serviceRelations'].items():
            print(f"\n服务 {service}:")
            print("  入站路由:")
            for route in relations.get('inbound', []):
                print(f"    - {route}")
            
            print("  出站路由:")
            for route in relations.get('outbound', []):
                print(f"    - 服务: {route['service']}")
                print(f"      端口: {route['port']}")
            
            print("  权重:")
            for subset, weight in relations.get('weights', {}).items():
                print(f"    - {subset}: {weight}") 