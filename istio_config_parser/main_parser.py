import os
import sys
import logging
import json
from typing import Dict, Any, List, Optional
import warnings

# 添加项目根目录到 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 统一解析器和模型（推荐使用）
from istio_config_parser.parsers.unified_parser import UnifiedParser
from istio_config_parser.parsers.model_exporter import ModelExporter
from istio_config_parser.models.ir_models import SystemIR
from istio_config_parser.utils.file_utils import load_yaml_file, load_json_file

# 旧版解析器（保留用于向后兼容）
try:
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
    from istio_config_parser.traffic_management.circuit_breaker_parser import parse_circuit_breaker
    LEGACY_AVAILABLE = True
except ImportError:
    LEGACY_AVAILABLE = False
    warnings.warn("旧版解析器模块不可用，仅支持统一解析器模式")

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
    从配置目录解析控制平面配置（旧版，已废弃）
    
    .. deprecated:: 1.0.0
        使用 :func:`parse_unified_from_dir` 替代，它提供了更完整的语义聚合和一致性验证。
    
    :param config_dir: 配置目录
    :param namespace: 可选的命名空间过滤
    :return: 控制平面配置结果
    """
    warnings.warn(
        "parse_control_plane_from_dir() 已废弃，请使用 parse_unified_from_dir() 代替",
        DeprecationWarning,
        stacklevel=2
    )
    
    if not LEGACY_AVAILABLE:
        raise RuntimeError("旧版解析器不可用，请使用 parse_unified_from_dir()")
    
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
    从配置目录解析数据平面配置（旧版，已废弃）
    
    .. deprecated:: 1.0.0
        使用 :func:`parse_unified_from_dir` 替代，它提供了更完整的语义聚合和一致性验证。
    
    :param config_dir: 配置目录
    :return: 数据平面配置结果
    """
    warnings.warn(
        "parse_data_plane_from_dir() 已废弃，请使用 parse_unified_from_dir() 代替",
        DeprecationWarning,
        stacklevel=2
    )
    
    if not LEGACY_AVAILABLE:
        raise RuntimeError("旧版解析器不可用，请使用 parse_unified_from_dir()")
    
    routes_json = os.path.join(config_dir, 'routes.json')
    if os.path.exists(routes_json):
        routes = load_json_file(routes_json)
        service_relations = parse_routes(routes, is_data_plane=True)
        return {'serviceRelations': service_relations}
    return {'serviceRelations': {}}


def parse_unified_from_dir(
    control_plane_dir: str = 'istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_monitor/istio_sidecar_config',
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None
) -> SystemIR:
    """
    使用统一解析器从配置目录解析控制平面和数据平面配置，生成中间表示（IR）
    
    这是推荐的解析方法，提供以下优势：
    - 语义聚合：自动聚合相关配置（如VirtualService + DestinationRule）
    - 双平面统一：使用统一的FunctionModel表示控制平面和数据平面
    - 一致性验证：自动检测配置不一致问题
    - 完整的IR：生成包含所有配置信息的中间表示
    - 并行处理：支持多线程并行解析不同配置类型，提高效率
    
    Args:
        control_plane_dir: 控制平面配置目录（相对于当前文件）
        data_plane_dir: 数据平面配置目录（sidecar配置，相对于当前文件）
        namespace: 可选的命名空间过滤
        enable_parallel: 是否启用并行处理（默认True）
        max_workers: 最大工作线程数，None表示自动计算
        
    Returns:
        SystemIR: 系统级中间表示，包含所有服务的配置和一致性状态
        
    Example:
        >>> system_ir = parse_unified_from_dir(namespace='online-boutique')
        >>> summary = system_ir.get_summary()
        >>> print(f"一致性比例: {summary['consistency_rate']:.2%}")
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
        logger.info(f"已加载路由配置: {routes_file}")
    else:
        logger.warning(f"未找到路由配置文件: {routes_file}")
    
    # 加载clusters.json
    clusters_file = os.path.join(dp_dir, 'clusters.json')
    if os.path.exists(clusters_file):
        data_plane_configs['clusters'] = load_json_file(clusters_file)
        logger.info(f"已加载集群配置: {clusters_file}")
    else:
        logger.warning(f"未找到集群配置文件: {clusters_file}")
    
    # 加载listeners.json
    listeners_file = os.path.join(dp_dir, 'listeners.json')
    if os.path.exists(listeners_file):
        data_plane_configs['listeners'] = load_json_file(listeners_file)
        logger.info(f"已加载监听器配置: {listeners_file}")
    else:
        logger.warning(f"未找到监听器配置文件: {listeners_file}")
    
    # 使用统一解析器
    logger.info("开始解析和对齐配置...")
    parser = UnifiedParser(enable_parallel=enable_parallel, max_workers=max_workers)
    system_ir = parser.parse_align_and_build_ir(control_plane_configs, data_plane_configs)
    
    logger.info("解析完成")
    return system_ir


def parse_and_export_models(
    control_plane_dir: str = 'istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_monitor/istio_sidecar_config',
    output_dir: str = 'models_output',
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None
) -> Dict[str, str]:
    """
    解析配置并导出独立的建模文件
    
    此函数是 parse_unified_from_dir 的扩展版本，不仅生成IR，
    还会导出控制平面和数据平面的独立模型文件，便于后续分析和可视化。
    
    Args:
        control_plane_dir: 控制平面配置目录
        data_plane_dir: 数据平面配置目录
        output_dir: 输出目录
        namespace: 可选的命名空间过滤
        
    Returns:
        Dict[str, str]: 导出文件路径字典，包含：
            - control_plane_file: 控制平面模型文件
            - data_plane_file: 数据平面模型文件
            - comparison_file: 对比文件
            - visualization_file: 可视化数据文件
            
    Example:
        >>> files = parse_and_export_models(namespace='online-boutique')
        >>> print(f"控制平面模型: {files['control_plane_file']}")
    """
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cp_dir = os.path.join(current_dir, control_plane_dir)
    dp_dir = os.path.join(current_dir, data_plane_dir)
    out_dir = os.path.join(current_dir, output_dir)
    
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
    
    routes_file = os.path.join(dp_dir, 'routes.json')
    if os.path.exists(routes_file):
        data_plane_configs['routes'] = load_json_file(routes_file)
    
    clusters_file = os.path.join(dp_dir, 'clusters.json')
    if os.path.exists(clusters_file):
        data_plane_configs['clusters'] = load_json_file(clusters_file)
    
    listeners_file = os.path.join(dp_dir, 'listeners.json')
    if os.path.exists(listeners_file):
        data_plane_configs['listeners'] = load_json_file(listeners_file)
    
    # 使用统一解析器
    logger.info("开始解析配置...")
    parser = UnifiedParser(enable_parallel=enable_parallel, max_workers=max_workers)
    exported_files = parser.parse_and_export(
        control_plane_configs, 
        data_plane_configs, 
        output_dir=out_dir
    )
    
    logger.info(f"模型文件已导出到: {out_dir}")
    return exported_files


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
    parser_cli = argparse.ArgumentParser(
        description='Istio配置统一解析器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 解析并生成IR（默认，并行处理）
  python main_parser.py
  
  # 解析特定命名空间
  python main_parser.py --namespace online-boutique
  
  # 保存IR到文件
  python main_parser.py --output my_ir.json
  
  # 导出模型文件（推荐）
  python main_parser.py --export --output-dir models_output
  
  # 禁用并行处理（使用串行）
  python main_parser.py --no-parallel
  
  # 指定最大工作线程数
  python main_parser.py --max-workers 4
  
  # 使用旧版解析器（已废弃）
  python main_parser.py --mode legacy --namespace online-boutique
        """
    )
    parser_cli.add_argument('--mode', choices=['legacy', 'unified'], default='unified',
                           help='解析模式：legacy（旧版，已废弃）或 unified（统一解析器，推荐）')
    parser_cli.add_argument('--namespace', type=str, default=None,
                           help='命名空间过滤（可选）')
    parser_cli.add_argument('--output', type=str, default=None,
                           help='输出IR文件路径（unified模式）')
    parser_cli.add_argument('--export', action='store_true',
                           help='导出独立的模型文件（控制平面/数据平面/可视化）')
    parser_cli.add_argument('--output-dir', type=str, default='models_output',
                           help='模型文件输出目录（与--export一起使用）')
    parser_cli.add_argument('--summary', action='store_true', default=True,
                           help='显示摘要信息（默认开启）')
    parser_cli.add_argument('--details', action='store_true',
                           help='显示详细的服务和功能信息')
    parser_cli.add_argument('--control-plane-dir', type=str, 
                           default='istio_monitor/istio_control_config',
                           help='控制平面配置目录')
    parser_cli.add_argument('--data-plane-dir', type=str,
                           default='istio_monitor/istio_sidecar_config',
                           help='数据平面配置目录')
    parser_cli.add_argument('--no-parallel', action='store_true',
                           help='禁用并行处理（使用串行处理）')
    parser_cli.add_argument('--max-workers', type=int, default=None,
                           help='最大工作线程数（默认自动计算）')
    args = parser_cli.parse_args()
    
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.mode == 'unified':
        # 解析并行处理选项
        enable_parallel = not args.no_parallel
        max_workers = args.max_workers
        
        print("\n" + "="*80)
        print("Istio配置统一解析器（Unified Parser）")
        print("="*80)
        print(f"控制平面目录: {args.control_plane_dir}")
        print(f"数据平面目录: {args.data_plane_dir}")
        if args.namespace:
            print(f"命名空间过滤: {args.namespace}")
        print(f"并行处理: {'启用' if enable_parallel else '禁用'}")
        if enable_parallel and max_workers:
            print(f"最大工作线程: {max_workers}")
        print("="*80)
        
        # 如果使用导出模式
        if args.export:
            print("\n[模式] 解析并导出模型文件")
            print("-"*80)
            
            exported_files = parse_and_export_models(
                control_plane_dir=args.control_plane_dir,
                data_plane_dir=args.data_plane_dir,
                output_dir=args.output_dir,
                namespace=args.namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
            
            print("\n[成功] 模型文件已导出:")
            for file_type, file_path in exported_files.items():
                print(f"  - {file_type}: {file_path}")
            
            print(f"\n[提示] 可以使用以下方式查看可视化:")
            print(f"  cd {os.path.dirname(exported_files.get('visualization_file', args.output_dir))}")
            print(f"  python -m http.server 8080")
            print(f"  # 然后在浏览器访问: http://localhost:8080/visualization_demo.html")
        
        else:
            # 标准模式：生成IR
            print("\n[模式] 解析并生成中间表示（IR）")
            print("-"*80)
            
            system_ir = parse_unified_from_dir(
                control_plane_dir=args.control_plane_dir,
                data_plane_dir=args.data_plane_dir,
                namespace=args.namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
            
            # 打印摘要
            if args.summary:
                print("\n[系统级摘要]")
                print("-"*80)
                summary = system_ir.get_summary()
                print(f"总服务数:       {summary['total_services']}")
                print(f"一致的服务:     {summary['consistent_services']} ({summary['consistent_services']/max(summary['total_services'],1)*100:.1f}%)")
                print(f"不一致的服务:   {summary['inconsistent_services']} ({summary['inconsistent_services']/max(summary['total_services'],1)*100:.1f}%)")
                print(f"一致性比例:     {summary['consistency_rate']:.2%}")
                print(f"总问题数:       {summary['total_issues']}")
                print(f"  - 错误:       {summary['total_errors']}")
                print(f"  - 警告:       {summary['total_warnings']}")
            
            # 打印详细信息
            if args.details:
                print("\n[服务详情]")
                print("-"*80)
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
                print(f"\n[保存] 中间表示（IR）已保存到: {args.output}")
            
            print("\n[提示] 使用 --export 参数可导出独立的模型文件用于可视化")
    
    else:
        print("\n" + "="*80)
        print("使用旧版解析器（Legacy Parser）- 已废弃")
        print("="*80)
        print("[警告] 旧版解析器已废弃，建议使用 --mode unified")
        print("[警告] 旧版解析器不支持语义聚合和一致性验证")
        print("="*80)
        
        if not LEGACY_AVAILABLE:
            print("\n[错误] 旧版解析器模块不可用")
            print("[提示] 请使用 --mode unified 模式")
            sys.exit(1)
        
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