"""
模型导出器
将解析后的功能模型导出为独立的控制平面和数据平面建模文件
"""
import json
import logging
from typing import Dict, List, Any
from pathlib import Path
from istio_config_parser.models.function_models import AnyFunctionModel, PlaneType

logger = logging.getLogger(__name__)


class ModelExporter:
    """模型导出器 - 生成独立的建模文件"""
    
    @staticmethod
    def export_models(
        control_plane_models: Dict[str, List[AnyFunctionModel]],
        data_plane_models: Dict[str, List[AnyFunctionModel]],
        output_dir: str = "."
    ) -> Dict[str, str]:
        """
        导出控制平面和数据平面的建模文件
        
        Args:
            control_plane_models: 控制平面功能模型字典 {function_type: [models]}
            data_plane_models: 数据平面功能模型字典 {function_type: [models]}
            output_dir: 输出目录
            
        Returns:
            {
                'control_plane_file': '...',
                'data_plane_file': '...'
            }
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 导出控制平面
        cp_file = output_path / "control_plane_models.json"
        cp_data = ModelExporter._organize_models(control_plane_models)
        with open(cp_file, 'w', encoding='utf-8') as f:
            json.dump(cp_data, f, indent=2, ensure_ascii=False)
        logger.info(f"控制平面建模已导出到: {cp_file}")
        
        # 导出数据平面
        dp_file = output_path / "data_plane_models.json"
        dp_data = ModelExporter._organize_models(data_plane_models)
        with open(dp_file, 'w', encoding='utf-8') as f:
            json.dump(dp_data, f, indent=2, ensure_ascii=False)
        logger.info(f"数据平面建模已导出到: {dp_file}")
        
        # 生成对比视图
        comparison_file = output_path / "model_comparison.json"
        comparison_data = ModelExporter._generate_comparison(cp_data, dp_data)
        with open(comparison_file, 'w', encoding='utf-8') as f:
            json.dump(comparison_data, f, indent=2, ensure_ascii=False)
        logger.info(f"对比视图已导出到: {comparison_file}")
        
        return {
            'control_plane_file': str(cp_file),
            'data_plane_file': str(dp_file),
            'comparison_file': str(comparison_file)
        }
    
    @staticmethod
    def _organize_models(models_dict: Dict[str, List[AnyFunctionModel]]) -> Dict[str, Any]:
        """
        按服务组织模型
        
        Returns:
            {
                'services': {
                    'namespace.service_name': {
                        'function_type1': {...},
                        'function_type2': {...}
                    }
                },
                'summary': {...}
            }
        """
        services = {}
        
        # 按服务聚合
        for func_type, model_list in models_dict.items():
            for model in model_list:
                service_key = f"{model.namespace}.{model.service_name}"
                
                if service_key not in services:
                    services[service_key] = {
                        'service_name': model.service_name,
                        'namespace': model.namespace,
                        'functions': {}
                    }
                
                # 添加功能配置
                services[service_key]['functions'][func_type] = model.to_dict()
        
        # 生成摘要
        summary = {
            'total_services': len(services),
            'total_functions': sum(len(s['functions']) for s in services.values()),
            'functions_by_type': {}
        }
        
        # 统计每种功能的数量
        for service in services.values():
            for func_type in service['functions'].keys():
                if func_type not in summary['functions_by_type']:
                    summary['functions_by_type'][func_type] = 0
                summary['functions_by_type'][func_type] += 1
        
        return {
            'summary': summary,
            'services': services
        }
    
    @staticmethod
    def _generate_comparison(
        cp_data: Dict[str, Any],
        dp_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成控制平面和数据平面的对比视图
        
        Returns:
            {
                'summary': {...},
                'services': {
                    'namespace.service_name': {
                        'control_plane': {...},
                        'data_plane': {...},
                        'matched_functions': [...],
                        'cp_only_functions': [...],
                        'dp_only_functions': [...]
                    }
                }
            }
        """
        cp_services = cp_data['services']
        dp_services = dp_data['services']
        
        all_services = set(cp_services.keys()) | set(dp_services.keys())
        
        comparison = {
            'summary': {
                'total_services': len(all_services),
                'cp_services': len(cp_services),
                'dp_services': len(dp_services),
                'matched_services': len(set(cp_services.keys()) & set(dp_services.keys())),
                'cp_only_services': len(set(cp_services.keys()) - set(dp_services.keys())),
                'dp_only_services': len(set(dp_services.keys()) - set(cp_services.keys()))
            },
            'services': {}
        }
        
        for service_key in sorted(all_services):
            cp_service = cp_services.get(service_key)
            dp_service = dp_services.get(service_key)
            
            service_comparison = {}
            
            if cp_service and dp_service:
                # 两边都有
                cp_funcs = set(cp_service['functions'].keys())
                dp_funcs = set(dp_service['functions'].keys())
                
                service_comparison = {
                    'status': 'matched',
                    'control_plane': cp_service,
                    'data_plane': dp_service,
                    'matched_functions': sorted(list(cp_funcs & dp_funcs)),
                    'cp_only_functions': sorted(list(cp_funcs - dp_funcs)),
                    'dp_only_functions': sorted(list(dp_funcs - cp_funcs))
                }
            elif cp_service:
                # 仅控制平面
                service_comparison = {
                    'status': 'control_plane_only',
                    'control_plane': cp_service,
                    'data_plane': None,
                    'functions': sorted(list(cp_service['functions'].keys()))
                }
            else:
                # 仅数据平面
                service_comparison = {
                    'status': 'data_plane_only',
                    'control_plane': None,
                    'data_plane': dp_service,
                    'functions': sorted(list(dp_service['functions'].keys()))
                }
            
            comparison['services'][service_key] = service_comparison
        
        return comparison
    
    @staticmethod
    def export_for_visualization(
        control_plane_models: Dict[str, List[AnyFunctionModel]],
        data_plane_models: Dict[str, List[AnyFunctionModel]],
        output_file: str = "visualization_data.json"
    ):
        """
        导出用于可视化的数据格式
        
        生成适合前端可视化的简化数据结构
        """
        cp_data = ModelExporter._organize_models(control_plane_models)
        dp_data = ModelExporter._organize_models(data_plane_models)
        
        # 生成可视化数据
        viz_data = {
            'metadata': {
                'cp_services': cp_data['summary']['total_services'],
                'dp_services': dp_data['summary']['total_services'],
                'timestamp': None  # 可以添加时间戳
            },
            'nodes': [],  # 服务节点
            'edges': [],  # 服务间关系
            'config_comparison': []  # 配置对比
        }
        
        # 生成节点
        all_services = set(cp_data['services'].keys()) | set(dp_data['services'].keys())
        
        for service_key in all_services:
            namespace, service_name = service_key.split('.', 1)
            
            has_cp = service_key in cp_data['services']
            has_dp = service_key in dp_data['services']
            
            node = {
                'id': service_key,
                'service_name': service_name,
                'namespace': namespace,
                'has_control_plane': has_cp,
                'has_data_plane': has_dp,
                'status': 'matched' if (has_cp and has_dp) else ('cp_only' if has_cp else 'dp_only')
            }
            
            if has_cp:
                node['cp_functions'] = list(cp_data['services'][service_key]['functions'].keys())
            
            if has_dp:
                node['dp_functions'] = list(dp_data['services'][service_key]['functions'].keys())
            
            viz_data['nodes'].append(node)
        
        # 从路由配置中提取边（服务间关系）
        for service_key, service_data in cp_data['services'].items():
            if 'routing' in service_data['functions']:
                routing = service_data['functions']['routing']
                for route in routing.get('routes', []):
                    for dest in route.get('destinations', []):
                        target_host = dest['host']
                        target_service = target_host.split('.')[0]
                        
                        edge = {
                            'source': service_key,
                            'target': f"{service_data['namespace']}.{target_service}",
                            'type': 'routing',
                            'weight': dest.get('weight', 100)
                        }
                        viz_data['edges'].append(edge)
        
        # 保存
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(viz_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"可视化数据已导出到: {output_file}")
        
        return output_file

