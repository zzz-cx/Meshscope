#!/usr/bin/env python3
"""
Istio一致性验证和可视化系统 - 主入口

统一的命令行界面，支持完整流水线、单独模块执行和Web服务
"""

import os
import sys
import argparse
import logging
from typing import Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from consistency_checker.config import get_config, load_config_from_file
from consistency_checker.core.orchestrator import Pipeline


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """配置日志"""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=handlers
    )


def run_full_pipeline(namespace: str):
    """运行完整的一致性验证流水线"""
    logger = logging.getLogger(__name__)
    logger.info("启动完整流水线")
    
    pipeline = Pipeline(namespace=namespace)
    report = pipeline.run_full_pipeline()
    
    logger.info(f"\n{'='*80}")
    logger.info(f"流水线执行成功！")
    logger.info(f"报告ID: {report.report_id}")
    logger.info(f"一致性状态: {report.consistency_check.overall_status.value if report.consistency_check else 'N/A'}")
    logger.info(f"一致性率: {report.consistency_check.consistency_rate:.2%}" if report.consistency_check else "N/A")
    logger.info(f"{'='*80}\n")
    
    return report


def run_static_only(namespace: str):
    """仅运行静态分析"""
    logger = logging.getLogger(__name__)
    logger.info("启动静态分析模式")
    
    pipeline = Pipeline(namespace=namespace)
    result = pipeline.run_static_only()
    
    logger.info(f"\n静态分析完成：")
    logger.info(f"  服务数: {result['summary']['total_services']}")
    logger.info(f"  策略数: {result['summary']['total_policies']}")
    logger.info(f"  配置边: {result['summary']['total_edges']}")
    
    return result


def run_consistency_only(namespace: str):
    """仅运行一致性检查"""
    logger = logging.getLogger(__name__)
    logger.info("启动一致性检查模式")
    
    pipeline = Pipeline(namespace=namespace)
    report = pipeline.run_consistency_check_only()
    
    logger.info(f"\n一致性检查完成：")
    logger.info(f"  一致性率: {report.consistency_check.consistency_rate:.2%}")
    logger.info(f"  不一致性: {len(report.consistency_check.inconsistencies)}")
    
    return report


def start_web_server(port: int = 8080, namespace: str = "default"):
    """启动Web可视化服务器"""
    logger = logging.getLogger(__name__)
    logger.info(f"启动Web可视化服务器: http://localhost:{port}")
    
    try:
        from consistency_checker.web.server import WebServer
        server = WebServer(port=port, namespace=namespace)
        server.run()
    except ImportError as e:
        logger.error(f"Web服务器模块未找到: {e}")
        logger.info("提示: 请确保安装了Flask: pip install flask")
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Istio一致性验证和可视化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 运行完整流水线
  python -m consistency_checker.main --mode full --namespace online-boutique
  
  # 仅运行静态分析
  python -m consistency_checker.main --mode static --namespace online-boutique
  
  # 仅运行一致性检查
  python -m consistency_checker.main --mode consistency --namespace online-boutique
  
  # 启动Web可视化界面
  python -m consistency_checker.main --mode web --port 8080
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["full", "static", "consistency", "web"],
        default="full",
        help="运行模式: full(完整流水线), static(仅静态分析), consistency(仅一致性检查), web(Web服务器)"
    )
    
    parser.add_argument(
        "--namespace",
        type=str,
        default="default",
        help="Kubernetes命名空间 (默认: default)"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="配置文件路径 (JSON格式)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)"
    )
    
    parser.add_argument(
        "--log-file",
        type=str,
        help="日志文件路径"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web服务器端口 (默认: 8080)"
    )
    
    args = parser.parse_args()
    
    # 配置日志
    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger(__name__)
    
    # 加载配置
    if args.config:
        logger.info(f"从文件加载配置: {args.config}")
        load_config_from_file(args.config)
    
    config = get_config()
    logger.info(f"使用配置: 项目根目录={config.project_root}")
    
    # 根据模式执行
    try:
        if args.mode == "full":
            run_full_pipeline(args.namespace)
        elif args.mode == "static":
            run_static_only(args.namespace)
        elif args.mode == "consistency":
            run_consistency_only(args.namespace)
        elif args.mode == "web":
            start_web_server(args.port, args.namespace)
        
        logger.info("✅ 任务执行成功")
        
    except Exception as e:
        logger.error(f"❌ 任务执行失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()


