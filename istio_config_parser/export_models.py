"""
独立建模文件导出脚本
生成控制平面和数据平面的独立建模文件，用于对比和可视化
"""
import os
import sys
import logging
import argparse
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from istio_config_parser.parsers.unified_parser import UnifiedParser
from istio_config_parser.utils.file_utils import load_json_file

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_configs_from_dir(
    control_plane_dir: str,
    data_plane_dir: str
) -> tuple:
    """从目录加载配置"""
    
    # 加载控制平面配置
    logger.info("加载控制平面配置...")
    from istio_config_parser.main_parser import _load_config_files
    
    current_dir = Path(__file__).parent
    cp_dir = current_dir / control_plane_dir
    dp_dir = current_dir / data_plane_dir
    
    control_plane_configs = {
        'services': _load_config_files(str(cp_dir), 'services'),
        'virtual_services': _load_config_files(str(cp_dir), 'virtualservices'),
        'destination_rules': _load_config_files(str(cp_dir), 'destinationrules'),
        'envoy_filters': _load_config_files(str(cp_dir), 'envoyfilters')
    }
    
    # 加载数据平面配置
    logger.info("加载数据平面配置...")
    data_plane_configs = {}
    
    routes_file = dp_dir / 'routes.json'
    if routes_file.exists():
        data_plane_configs['routes'] = load_json_file(str(routes_file))
    
    clusters_file = dp_dir / 'clusters.json'
    if clusters_file.exists():
        data_plane_configs['clusters'] = load_json_file(str(clusters_file))
    
    listeners_file = dp_dir / 'listeners.json'
    if listeners_file.exists():
        data_plane_configs['listeners'] = load_json_file(str(listeners_file))
    
    return control_plane_configs, data_plane_configs


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='导出Istio配置的控制平面和数据平面建模文件'
    )
    parser.add_argument(
        '--control-plane-dir',
        default='istio_monitor/istio_control_config',
        help='控制平面配置目录'
    )
    parser.add_argument(
        '--data-plane-dir',
        default='istio_monitor/istio_sidecar_config',
        help='数据平面配置目录'
    )
    parser.add_argument(
        '--output-dir',
        default='models_output',
        help='输出目录'
    )
    parser.add_argument(
        '--namespace',
        help='过滤特定命名空间（可选）'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print(" "*25 + "Istio配置建模导出工具")
    print("="*80 + "\n")
    
    # 加载配置
    try:
        control_plane_configs, data_plane_configs = load_configs_from_dir(
            args.control_plane_dir,
            args.data_plane_dir
        )
        
        logger.info("配置加载完成")
        
    except Exception as e:
        logger.error(f"加载配置失败: {str(e)}")
        return 1
    
    # 执行解析和导出
    try:
        logger.info("开始解析和导出...")
        
        parser_instance = UnifiedParser()
        exported_files = parser_instance.parse_and_export(
            control_plane_configs,
            data_plane_configs,
            output_dir=args.output_dir
        )
        
        # 显示结果
        print("\n" + "="*80)
        print("导出完成！")
        print("="*80)
        print(f"\n生成的文件：")
        print(f"  [1] 控制平面建模: {exported_files['control_plane_file']}")
        print(f"  [2] 数据平面建模: {exported_files['data_plane_file']}")
        print(f"  [3] 对比视图:     {exported_files['comparison_file']}")
        print(f"  [4] 可视化数据:   {exported_files['visualization_file']}")
        
        # 显示统计信息
        import json
        
        with open(exported_files['control_plane_file'], 'r', encoding='utf-8') as f:
            cp_data = json.load(f)
        
        with open(exported_files['data_plane_file'], 'r', encoding='utf-8') as f:
            dp_data = json.load(f)
        
        with open(exported_files['comparison_file'], 'r', encoding='utf-8') as f:
            comparison_data = json.load(f)
        
        print(f"\n统计信息：")
        print(f"  控制平面:")
        print(f"    - 服务数: {cp_data['summary']['total_services']}")
        print(f"    - 配置数: {cp_data['summary']['total_functions']}")
        print(f"    - 功能分布: {cp_data['summary']['functions_by_type']}")
        
        print(f"\n  数据平面:")
        print(f"    - 服务数: {dp_data['summary']['total_services']}")
        print(f"    - 配置数: {dp_data['summary']['total_functions']}")
        print(f"    - 功能分布: {dp_data['summary']['functions_by_type']}")
        
        print(f"\n  对比结果:")
        comp_summary = comparison_data['summary']
        print(f"    - 总服务数: {comp_summary['total_services']}")
        print(f"    - 完全匹配: {comp_summary['matched_services']}")
        print(f"    - 仅控制平面: {comp_summary['cp_only_services']}")
        print(f"    - 仅数据平面: {comp_summary['dp_only_services']}")
        
        print(f"\n" + "="*80)
        print("建模文件可用于:")
        print("  1. 一致性验证和对比分析")
        print("  2. 配置可视化展示")
        print("  3. 故障诊断和调试")
        print("  4. 配置审计和合规检查")
        print("="*80 + "\n")
        
        return 0
        
    except Exception as e:
        logger.error(f"解析和导出失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

