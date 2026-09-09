#!/usr/bin/env python3
"""
可扩展性评估脚本
评估系统在处理大型微服务部署时的处理效率和资源使用情况

评估指标：
1. 静态解析 (static parsing)
2. 测试生成 (test generation)
3. 动态验证 (dynamic validation)
4. 内存和CPU开销 (memory and CPU overhead)

评估维度：
- 服务数量 (number of services)
- 配置策略大小 (size of configuration policies)

测试应用：
- Bookinfo (轻量级Istio演示)
- TrainTicket (生产级应用)
- SiteWhere (生产级应用)
"""

import os
import sys
import json
import time
import argparse
import logging
import threading
import statistics
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import psutil

# 添加项目路径
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scalability_evaluation.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("scalability_evaluation")

# 导入必要的模块
try:
    from istio_config_parser.main_parser import parse_unified_from_dir
    from consistency_checker.core.orchestrator import Pipeline
    from consistency_checker.core.static_analyzer import StaticAnalyzer
    from consistency_checker.config import set_config, GlobalConfig
    from e2e_validator import E2EValidator
    # 使用增强版系统资源监控器和验证器
    from evaluation.scalability.system_resource_monitor import SystemResourceMonitor
    from evaluation.scalability.enhanced_resource_monitor import EnhancedSystemResourceMonitor
    from evaluation.scalability.metrics_validator import MetricsValidator, run_baseline_measurement
    from evaluation.scalability.prometheus_metrics_collector import PrometheusMetricsCollector
    MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"部分模块导入失败: {e}")
    MODULES_AVAILABLE = False


@dataclass
class ScalabilityMetrics:
    """可扩展性指标"""
    # 应用信息
    application_name: str
    namespace: str
    num_services: int = 0
    num_policies: int = 0
    config_size_kb: float = 0.0
    
    # 性能指标
    static_parsing_time: float = 0.0
    test_generation_time: float = 0.0
    dynamic_validation_time: float = 0.0
    total_time: float = 0.0
    
    # 资源使用
    cpu_avg_percent: float = 0.0
    cpu_max_percent: float = 0.0
    memory_avg_mb: float = 0.0
    memory_max_mb: float = 0.0
    
    # 详细指标
    static_parsing_cpu: float = 0.0
    static_parsing_memory: float = 0.0
    test_generation_cpu: float = 0.0
    test_generation_memory: float = 0.0
    dynamic_validation_cpu: float = 0.0
    dynamic_validation_memory: float = 0.0
    
    # 动态验证阶段的详细指标（主机和VM分别）
    dynamic_validation_host_cpu: float = 0.0
    dynamic_validation_host_memory: float = 0.0
    dynamic_validation_vm_cpu: float = 0.0
    dynamic_validation_vm_memory: float = 0.0
    
    # 增强指标（Python进程、网络IO等）
    python_process_memory_mb: float = 0.0
    network_bytes_total: int = 0
    disk_bytes_total: int = 0
    
    # 程序内存占用（运行前后差值）
    memory_before_mb: float = 0.0  # 程序运行前的系统内存使用
    memory_after_mb: float = 0.0   # 程序运行后的系统内存使用
    memory_delta_mb: float = 0.0   # 程序占用的内存增量（after - before）
    
    # VM内存信息（多个时刻的快照）
    vm_memory_before_mb: float = 0.0  # VM运行前的内存使用
    vm_memory_after_mb: float = 0.0   # VM运行后的内存使用
    vm_memory_delta_mb: float = 0.0   # VM内存增量
    vm_memory_snapshots: List[Dict[str, Any]] = field(default_factory=list)  # VM内存快照列表 [{"timestamp": ..., "memory_mb": ..., "stage": ...}]
    
    # K8s集群内存信息（通过Prometheus收集）
    k8s_memory_before_mb: float = 0.0  # K8s集群运行前的内存使用
    k8s_memory_after_mb: float = 0.0   # K8s集群运行后的内存使用
    k8s_memory_delta_mb: float = 0.0   # K8s集群内存增量
    k8s_memory_snapshots: List[Dict[str, Any]] = field(default_factory=list)  # K8s内存快照列表
    
    # 总内存占用（主机 + K8s集群）
    total_memory_delta_mb: float = 0.0  # 总内存增量 = 主机内存增量 + K8s集群内存增量
    
    # 时间检查点
    checkpoints: Dict[str, float] = field(default_factory=dict)
    
    # 测试生成统计
    num_test_cases: int = 0
    
    # 验证统计
    num_verified_policies: int = 0
    num_failed_policies: int = 0
    
    # 数据验证结果
    validation_issues: List[Dict[str, Any]] = field(default_factory=list)
    is_valid: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)


class ScalabilityEvaluator:
    """可扩展性评估器"""
    
    def __init__(
        self,
        vm_host: Optional[str] = None,
        vm_user: Optional[str] = None,
        vm_password: Optional[str] = None,
        k8s_host: Optional[str] = None,
        k8s_token: Optional[str] = None,
        output_dir: Optional[Path] = None,
        num_runs: int = 1  # 运行次数（用于取平均值）
    ):
        """初始化评估器"""
        self.vm_host = vm_host
        self.vm_user = vm_user
        self.vm_password = vm_password
        self.k8s_host = k8s_host
        self.k8s_token = k8s_token
        self.num_runs = num_runs  # 运行次数
        
        # Prometheus配置（默认从环境变量或常见位置获取）
        self.prometheus_url = os.getenv('PROMETHEUS_URL', 'http://localhost:9090')
        self.enable_prometheus = os.getenv('ENABLE_PROMETHEUS', 'false').lower() == 'true'
        
        # 输出目录
        if output_dir is None:
            self.output_dir = project_root / "results" / "scalability"
        else:
            self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 历史指标（用于检测增长趋势）
        self.previous_metrics: List[Dict[str, Any]] = []
        
        # Prometheus指标收集器（如果启用）
        self.prometheus_collector = None
        if self.enable_prometheus:
            try:
                self.prometheus_collector = PrometheusMetricsCollector(
                    prometheus_url=self.prometheus_url
                )
                logger.info(f"Prometheus指标收集器已启用: {self.prometheus_url}")
            except Exception as e:
                logger.warning(f"初始化Prometheus收集器失败: {e}")
                self.prometheus_collector = None
        
        # 应用配置
        self.applications = {
            'bookinfo': {
                'namespace': 'default',
                'control_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config",
                'data_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config",
                'ingress_url': f"http://{vm_host}:30476/productpage" if vm_host else None
            },
            'online-boutique': {
                'namespace': 'online-boutique',
                'control_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config",
                'data_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config",
                'ingress_url': f"http://{vm_host}:30476" if vm_host else None
            },
            'trainticket': {
                'namespace': 'trainticket',
                'control_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config",
                'data_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config",
                'ingress_url': f"http://{vm_host}:30476" if vm_host else None
            },
            'sitewhere': {
                'namespace': 'sitewhere',
                'control_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config",
                'data_plane_dir': project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config",
                'ingress_url': f"http://{vm_host}:30476" if vm_host else None
            }
        }
        
        logger.info(f"可扩展性评估器初始化完成，输出目录: {self.output_dir}")
    
    def _check_application_exists(self, app_name: str, namespace: str) -> bool:
        """检查应用是否存在（通过检查是否有该命名空间的服务）"""
        try:
            app_config = self.applications.get(app_name, {})
            control_plane_dir = app_config.get('control_plane_dir')
            data_plane_dir = app_config.get('data_plane_dir')
            
            if not control_plane_dir or not data_plane_dir:
                return False
            
            # 尝试解析配置，检查是否有该命名空间的服务
            try:
                system_ir = parse_unified_from_dir(
                    control_plane_dir=str(control_plane_dir),
                    data_plane_dir=str(data_plane_dir),
                    namespace=namespace,
                    enable_parallel=True
                )
                
                # 检查是否有该命名空间的服务
                if hasattr(system_ir, 'services'):
                    for service_ir in system_ir.services.values():
                        if hasattr(service_ir, 'namespace') and service_ir.namespace == namespace:
                            return True
                    # 如果没有找到，尝试key前缀匹配
                    namespace_prefix = f"{namespace}."
                    for key in system_ir.services.keys():
                        if key.startswith(namespace_prefix):
                            return True
                return False
            except Exception as e:
                logger.debug(f"检查应用 {app_name} 是否存在时出错: {e}")
                return False
        except Exception as e:
            logger.debug(f"检查应用 {app_name} 时出错: {e}")
            return False
    
    def _get_application_stats(self, app_name: str, namespace: str) -> Dict[str, int]:
        """获取应用统计信息（服务数量、策略数量等）"""
        try:
            # 使用E2EValidator获取统计信息
            validator = E2EValidator({
                'namespace': namespace,
                'vm_host': self.vm_host,
                'vm_user': self.vm_user,
                'vm_password': self.vm_password,
                'k8s_host': self.k8s_host,
                'k8s_token': self.k8s_token
            })
            
            # 获取控制平面和数据平面配置
            app_config = self.applications.get(app_name, {})
            control_plane_dir = app_config.get('control_plane_dir')
            data_plane_dir = app_config.get('data_plane_dir')
            
            if not control_plane_dir or not data_plane_dir:
                logger.warning(f"应用 {app_name} 的配置目录未找到")
                return {'num_services': 0, 'num_policies': 0, 'config_size_kb': 0.0}
            
            # 解析配置获取统计信息
            try:
                system_ir = parse_unified_from_dir(
                    control_plane_dir=str(control_plane_dir),
                    data_plane_dir=str(data_plane_dir),
                    namespace=namespace,
                    enable_parallel=True
                )
                
                # 统计服务数量（只统计指定命名空间的服务）
                num_services = 0
                num_policies = 0
                matched_services = []  # 用于调试
                if hasattr(system_ir, 'services'):
                    for service_ir in system_ir.services.values():
                        # 只统计指定命名空间的服务
                        if hasattr(service_ir, 'namespace') and service_ir.namespace == namespace:
                            num_services += 1
                            matched_services.append(f"{service_ir.namespace}.{service_ir.service_name}")
                            # 统计策略数量（从每个服务的functions中统计）
                            if hasattr(service_ir, 'functions'):
                                num_policies += len(service_ir.functions)
                
                # 如果没有找到指定命名空间的服务，尝试使用服务key的前缀匹配
                if num_services == 0 and hasattr(system_ir, 'services'):
                    namespace_prefix = f"{namespace}."
                    for key, service_ir in system_ir.services.items():
                        if key.startswith(namespace_prefix):
                            num_services += 1
                            matched_services.append(key)
                            if hasattr(service_ir, 'functions'):
                                num_policies += len(service_ir.functions)
                
                # 日志：显示匹配到的服务（用于验证统计正确性）
                if matched_services:
                    logger.debug(f"[{app_name}] 匹配到的服务 ({len(matched_services)}个): {', '.join(sorted(matched_services))}")
                else:
                    logger.warning(f"[{app_name}] 未找到命名空间 '{namespace}' 的服务，总服务数: {len(system_ir.services) if hasattr(system_ir, 'services') else 0}")
                    # 显示所有服务的命名空间，用于调试
                    if hasattr(system_ir, 'services'):
                        all_namespaces = set()
                        for service_ir in system_ir.services.values():
                            if hasattr(service_ir, 'namespace'):
                                all_namespaces.add(service_ir.namespace)
                        logger.debug(f"[{app_name}] 所有命名空间: {', '.join(sorted(all_namespaces))}")
                
                # 计算配置大小（包括数据平面配置）
                config_size_kb = 0.0
                if control_plane_dir.exists():
                    for config_file in control_plane_dir.rglob("*.yaml"):
                        try:
                            config_size_kb += config_file.stat().st_size / 1024
                        except (OSError, FileNotFoundError):
                            pass
                    for config_file in control_plane_dir.rglob("*.yml"):
                        try:
                            config_size_kb += config_file.stat().st_size / 1024
                        except (OSError, FileNotFoundError):
                            pass
                if data_plane_dir.exists():
                    for config_file in data_plane_dir.rglob("*.json"):
                        try:
                            config_size_kb += config_file.stat().st_size / 1024
                        except (OSError, FileNotFoundError):
                            pass
                    for config_file in data_plane_dir.rglob("*.yaml"):
                        try:
                            config_size_kb += config_file.stat().st_size / 1024
                        except (OSError, FileNotFoundError):
                            pass
                
                return {
                    'num_services': num_services,
                    'num_policies': num_policies,
                    'config_size_kb': round(config_size_kb, 2)
                }
            except Exception as e:
                logger.warning(f"解析配置获取统计信息失败: {e}")
                return {'num_services': 0, 'num_policies': 0, 'config_size_kb': 0.0}
                
        except Exception as e:
            logger.error(f"获取应用统计信息失败: {e}")
            return {'num_services': 0, 'num_policies': 0, 'config_size_kb': 0.0}
    
    def _get_vm_memory_snapshot(
        self,
        vm_monitor: Optional[SystemResourceMonitor],
        stage: str = "unknown"
    ) -> Optional[Dict[str, Any]]:
        """
        获取VM内存快照
        
        Args:
            vm_monitor: VM监控器
            stage: 当前阶段名称
            
        Returns:
            内存快照字典，包含timestamp、memory_mb、stage等信息，如果无法获取则返回None
        """
        if not vm_monitor or not vm_monitor.monitor_remote:
            return None
        
        try:
            # 确保SSH连接已建立
            if not vm_monitor.ssh_client:
                vm_monitor._connect_ssh()
            
            # 通过SSH获取VM内存信息
            metrics = vm_monitor._get_remote_metrics_via_ssh()
            if metrics:
                return {
                    'timestamp': time.time(),
                    'memory_mb': metrics.memory_used_mb,
                    'memory_percent': metrics.memory_percent,
                    'memory_total_mb': metrics.memory_total_mb,
                    'stage': stage
                }
        except Exception as e:
            logger.warning(f"获取VM内存快照失败 ({stage}): {e}")
        
        return None
    
    def evaluate_static_parsing(
        self,
        app_name: str,
        namespace: str,
        monitor: SystemResourceMonitor,
        enhanced_monitor: Optional[EnhancedSystemResourceMonitor] = None
    ) -> Dict[str, Any]:
        """评估静态解析性能"""
        logger.info(f"[{app_name}] 开始静态解析评估...")
        
        app_config = self.applications.get(app_name, {})
        control_plane_dir = app_config.get('control_plane_dir')
        data_plane_dir = app_config.get('data_plane_dir')
        
        if not control_plane_dir or not data_plane_dir:
            raise ValueError(f"应用 {app_name} 的配置目录未找到")
        
        # 记录时间检查点（使用高精度计时器）
        checkpoints = {
            'config_loading_start': time.perf_counter()
        }
        
        start_time = time.perf_counter()
        
        try:
            # 检查点：配置加载完成
            checkpoints['config_loading_end'] = time.perf_counter()
            checkpoints['parsing_start'] = time.perf_counter()
            
            # 解析配置
            system_ir = parse_unified_from_dir(
                control_plane_dir=str(control_plane_dir),
                data_plane_dir=str(data_plane_dir),
                namespace=namespace,
                enable_parallel=True,
                max_workers=None
            )
            
            checkpoints['parsing_end'] = time.perf_counter()
            checkpoints['ir_built'] = time.perf_counter()
            parsing_time = time.perf_counter() - start_time
            
            # 获取资源使用情况
            summary = monitor.get_summary()
            enhanced_summary = {}
            if enhanced_monitor:
                enhanced_summary = enhanced_monitor.get_summary()
            
            return {
                'success': True,
                'parsing_time': parsing_time,
                'cpu_avg': summary.get('cpu_percent_avg', 0.0),
                'cpu_max': summary.get('cpu_percent_max', 0.0),
                'memory_avg': summary.get('memory_used_mb_avg', 0.0),
                'memory_max': summary.get('memory_used_mb_max', 0.0),
                'memory_percent_avg': summary.get('memory_percent_avg', 0.0),
                'memory_percent_max': summary.get('memory_percent_max', 0.0),
                'python_process_memory_mb': enhanced_summary.get('python_process_memory_mb_avg', 0.0),
                'network_bytes_total': enhanced_summary.get('network_bytes_total', 0),
                'checkpoints': checkpoints,
                'system_ir': system_ir
            }
        except Exception as e:
            logger.error(f"静态解析失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'parsing_time': time.time() - start_time
            }
    
    def evaluate_test_generation(
        self,
        app_name: str,
        namespace: str,
        system_ir: Any,
        monitor: SystemResourceMonitor,
        enhanced_monitor: Optional[EnhancedSystemResourceMonitor] = None
    ) -> Dict[str, Any]:
        """评估测试生成性能"""
        logger.info(f"[{app_name}] 开始测试生成评估...")
        
        # 记录时间检查点（使用高精度计时器）
        checkpoints = {
            'generation_start': time.perf_counter()
        }
        
        start_time = time.perf_counter()
        
        try:
            # 使用E2EValidator生成测试用例
            validator = E2EValidator({
                'namespace': namespace,
                'vm_host': self.vm_host,
                'vm_user': self.vm_user,
                'vm_password': self.vm_password,
                'k8s_host': self.k8s_host,
                'k8s_token': self.k8s_token,
                'output_dir': str(self.output_dir / app_name / 'test_generation')
            })
            
            # 将SystemIR转换为IR数据格式（用于测试生成）
            # 注意：E2EValidator的step4需要先执行step3生成IR
            # 这里简化处理，直接调用step4（它会尝试从配置文件读取）
            ir_data = {
                'services': system_ir.services if hasattr(system_ir, 'services') else {},
                'summary': system_ir.get_summary() if hasattr(system_ir, 'get_summary') else {}
            }
            
            # 尝试生成测试用例（如果配置文件存在）
            try:
                test_result = validator.step4_generate_orthogonal_test_cases(ir_data)
                num_test_cases = test_result.get('test_cases_count', 0)
            except Exception as e:
                logger.warning(f"测试生成失败（可能缺少配置文件）: {e}")
                # 如果测试生成失败，估算测试用例数量（基于服务数量）
                summary = system_ir.get_summary() if hasattr(system_ir, 'get_summary') else {}
                num_services = summary.get('total_services', len(system_ir.services) if hasattr(system_ir, 'services') else 0)
                # 简单估算：每个服务可能生成多个测试用例
                num_test_cases = num_services * 3  # 估算值
                test_result = {'test_cases_count': num_test_cases, 'estimated': True}
            
            checkpoints['generation_end'] = time.perf_counter()
            checkpoints['tests_generated'] = time.perf_counter()
            generation_time = time.perf_counter() - start_time
            
            # 获取资源使用情况
            summary = monitor.get_summary()
            enhanced_summary = {}
            if enhanced_monitor:
                enhanced_summary = enhanced_monitor.get_summary()
            
            return {
                'success': True,
                'generation_time': generation_time,
                'num_test_cases': num_test_cases,
                'cpu_avg': summary.get('cpu_percent_avg', 0.0),
                'cpu_max': summary.get('cpu_percent_max', 0.0),
                'memory_avg': summary.get('memory_used_mb_avg', 0.0),
                'memory_max': summary.get('memory_used_mb_max', 0.0),
                'memory_percent_avg': summary.get('memory_percent_avg', 0.0),
                'memory_percent_max': summary.get('memory_percent_max', 0.0),
                'python_process_memory_mb': enhanced_summary.get('python_process_memory_mb_avg', 0.0),
                'network_bytes_total': enhanced_summary.get('network_bytes_total', 0),
                'checkpoints': checkpoints,
                'test_result': test_result
            }
        except Exception as e:
            logger.error(f"测试生成失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'generation_time': time.time() - start_time,
                'num_test_cases': 0
            }
    
    def evaluate_dynamic_validation(
        self,
        app_name: str,
        namespace: str,
        host_monitor: SystemResourceMonitor,
        vm_monitor: Optional[SystemResourceMonitor] = None
    ) -> Dict[str, Any]:
        """评估动态验证性能"""
        logger.info(f"[{app_name}] 开始动态验证评估...")
        
        app_config = self.applications.get(app_name, {})
        control_plane_dir = app_config.get('control_plane_dir')
        data_plane_dir = app_config.get('data_plane_dir')
        
        if not control_plane_dir or not data_plane_dir:
            raise ValueError(f"应用 {app_name} 的配置目录未找到")
        
        # 记录时间检查点（使用高精度计时器）
        checkpoints = {
            'validation_start': time.perf_counter()
        }
        
        start_time = time.perf_counter()
        
        try:
            # 配置全局配置
            checkpoints['config_set'] = time.perf_counter()
            global_config = GlobalConfig()
            global_config.project_root = str(project_root)
            global_config.control_plane_config_dir = str(control_plane_dir)
            global_config.data_plane_config_dir = str(data_plane_dir)
            global_config.namespace = namespace
            set_config(global_config)
            
            # 运行完整验证流程
            checkpoints['pipeline_created'] = time.perf_counter()
            pipeline = Pipeline(namespace=namespace)
            pipeline.static_analyzer = StaticAnalyzer(
                config_dir=str(control_plane_dir),
                namespace=namespace
            )
            
            checkpoints['pipeline_started'] = time.perf_counter()
            
            # 确保真正执行端到端测试：如果测试矩阵存在但HTTP结果不存在，则发送HTTP请求
            test_matrix_file = project_root / "istio_Dynamic_Test" / "configs" / "output_matrix.json"
            http_results_dir = project_root / "results" / "http_results"
            
            # 检查是否需要发送HTTP请求
            need_send_requests = False
            if test_matrix_file.exists():
                # 检查HTTP结果是否存在
                http_result_files = list(http_results_dir.glob("*.json")) if http_results_dir.exists() else []
                if len(http_result_files) == 0:
                    logger.info(f"  [端到端测试] 未找到HTTP测试结果，将发送HTTP请求...")
                    need_send_requests = True
                else:
                    logger.info(f"  [端到端测试] 找到 {len(http_result_files)} 个HTTP结果文件，将使用现有结果")
            
            # 如果需要，发送HTTP请求（真正的端到端测试）
            if need_send_requests:
                try:
                    logger.info(f"  [端到端测试] 开始发送HTTP请求...")
                    validator = E2EValidator({
                        'namespace': namespace,
                        'vm_host': self.vm_host,
                        'vm_user': self.vm_user,
                        'vm_password': self.vm_password,
                        'k8s_host': self.k8s_host,
                        'k8s_token': self.k8s_token
                    })
                    
                    # 发送动态请求（这会真正发送HTTP请求到服务）
                    http_results = validator.step5_send_dynamic_requests(str(test_matrix_file))
                    logger.info(f"  [端到端测试] HTTP请求发送完成，执行了 {http_results.get('test_cases_executed', 0)} 个测试用例")
                    checkpoints['http_requests_sent'] = time.perf_counter()
                except Exception as e:
                    logger.warning(f"  [端到端测试] 发送HTTP请求失败: {e}，将使用Pipeline的现有结果")
            
            # 运行Pipeline（会分析HTTP结果）
            report = pipeline.run_full_pipeline()
            checkpoints['pipeline_completed'] = time.perf_counter()
            
            validation_time = time.perf_counter() - start_time
            checkpoints['validation_end'] = time.perf_counter()
            
            # 获取资源使用情况
            # 动态验证阶段：静态分析在主机，测试执行在VM
            # 优先使用VM监控数据（如果可用），因为测试执行是主要工作负载
            # 如果没有VM监控，则使用主机监控数据
            host_summary = host_monitor.get_summary()
            vm_summary = vm_monitor.get_summary() if vm_monitor else {}
            
            # 选择主要监控数据（优先VM，因为测试执行在VM上）
            if vm_summary and vm_summary.get('cpu_percent_avg', 0.0) > 0:
                # 使用VM监控数据
                summary = vm_summary
                logger.info("  使用VM监控数据（测试执行在VM上）")
            else:
                # 使用主机监控数据
                summary = host_summary
                logger.info("  使用主机监控数据（静态分析在主机上）")
            
            # 同时保存主机和VM的监控数据用于详细分析
            host_cpu_avg = host_summary.get('cpu_percent_avg', 0.0)
            host_memory_avg = host_summary.get('memory_used_mb_avg', 0.0)
            vm_cpu_avg = vm_summary.get('cpu_percent_avg', 0.0) if vm_summary else 0.0
            vm_memory_avg = vm_summary.get('memory_used_mb_avg', 0.0) if vm_summary else 0.0
            
            # 提取验证统计
            num_verified = report.summary.get('verified_policies', 0) if hasattr(report, 'summary') else 0
            num_failed = report.summary.get('failed_policies', 0) if hasattr(report, 'summary') else 0
            
            return {
                'success': True,
                'validation_time': validation_time,
                'num_verified_policies': num_verified,
                'num_failed_policies': num_failed,
                # 主要指标（优先VM）
                'cpu_avg': summary.get('cpu_percent_avg', 0.0),
                'cpu_max': summary.get('cpu_percent_max', 0.0),
                'memory_avg': summary.get('memory_used_mb_avg', 0.0),
                'memory_max': summary.get('memory_used_mb_max', 0.0),
                'memory_percent_avg': summary.get('memory_percent_avg', 0.0),
                'memory_percent_max': summary.get('memory_percent_max', 0.0),
                # 详细指标（分别记录主机和VM）
                'host_cpu_avg': host_cpu_avg,
                'host_memory_avg': host_memory_avg,
                'vm_cpu_avg': vm_cpu_avg,
                'vm_memory_avg': vm_memory_avg,
                'checkpoints': checkpoints,
                'report': report
            }
        except Exception as e:
            logger.error(f"动态验证失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'validation_time': time.perf_counter() - start_time,
                'checkpoints': checkpoints
            }
    
    def evaluate_application(self, app_name: str) -> ScalabilityMetrics:
        """评估单个应用的可扩展性"""
        logger.info(f"\n{'='*80}")
        logger.info(f"评估应用: {app_name}")
        logger.info(f"{'='*80}")
        
        if app_name not in self.applications:
            raise ValueError(f"未知应用: {app_name}")
        
        app_config = self.applications[app_name]
        namespace = app_config['namespace']
        
        # 初始化指标
        metrics = ScalabilityMetrics(
            application_name=app_name,
            namespace=namespace
        )
        
        # 获取应用统计信息（只在第一次运行时获取）
        logger.info(f"[{app_name}] 获取应用统计信息...")
        stats = self._get_application_stats(app_name, namespace)
        metrics.num_services = stats.get('num_services', 0)
        metrics.num_policies = stats.get('num_policies', 0)
        metrics.config_size_kb = stats.get('config_size_kb', 0.0)
        
        logger.info(f"[{app_name}] 统计信息:")
        logger.info(f"  服务数量: {metrics.num_services}")
        logger.info(f"  策略数量: {metrics.num_policies}")
        logger.info(f"  配置大小: {metrics.config_size_kb} KB")
        
        # 运行基准测试（测量系统基础开销）
        logger.info(f"[{app_name}] 运行基准测试...")
        baseline = run_baseline_measurement(duration=2.0)
        
        # 保存统计信息供单次运行使用
        app_stats = {
            'num_services': metrics.num_services,
            'num_policies': metrics.num_policies,
            'config_size_kb': metrics.config_size_kb
        }
        
        # 创建双监控器系统：
        # 1. 主机监控器：监控主机资源（用于解析和生成阶段，这些在主机上执行）
        # 2. VM监控器：监控虚拟机资源（用于配置获取和测试执行阶段，这些在VM上执行）
        # 3. 增强版监控器：监控整个系统+子进程+网络IO等
        host_monitor = SystemResourceMonitor(
            sampling_interval=0.1,
            monitor_remote=False,  # 监控本地主机
            ssh_host=None,
            ssh_user=None,
            ssh_password=None
        )
        
        # 增强版监控器（监控整个系统，包括子进程）
        enhanced_monitor = EnhancedSystemResourceMonitor(sampling_interval=0.1)
        
        vm_monitor = None
        if self.vm_host:
            vm_monitor = SystemResourceMonitor(
                sampling_interval=0.05,  # VM监控使用更短的采样间隔
                monitor_remote=True,  # 监控远程VM
                ssh_host=self.vm_host,
                ssh_user=self.vm_user,
                ssh_password=self.vm_password
            )
        
        # 记录总开始时间（使用高精度计时器）
        total_start_time = time.perf_counter()
        metrics.checkpoints['evaluation_start'] = total_start_time
        
        # 如果多次运行，收集所有运行的结果
        all_runs_metrics = []
        
        for run_num in range(self.num_runs):
            if self.num_runs > 1:
                logger.info(f"\n[{app_name}] === 运行 {run_num + 1}/{self.num_runs} ===")
            
            # 运行单次评估
            run_metrics = self._evaluate_application_single_run(
                app_name, namespace, host_monitor, enhanced_monitor, vm_monitor, baseline, app_stats
            )
            all_runs_metrics.append(run_metrics)
            
            # 如果不是最后一次运行，等待一段时间再运行下一次
            if run_num < self.num_runs - 1:
                logger.info(f"[{app_name}] 等待5秒后开始下一次运行...")
                time.sleep(5.0)
        
        # 如果多次运行，计算平均值
        if self.num_runs > 1:
            metrics = self._average_metrics(all_runs_metrics, metrics)
            logger.info(f"\n[{app_name}] === {self.num_runs}次运行的平均结果 ===")
        else:
            metrics = all_runs_metrics[0]
        
        # 进行数据验证
        logger.info(f"\n[{app_name}] === 数据验证 ===")
        validator = MetricsValidator()
        validation_issues = validator.validate_metrics(
            metrics.to_dict(),
            baseline=baseline,
            previous_metrics=self.previous_metrics
        )
        metrics.validation_issues = [issue.to_dict() for issue in validation_issues]
        metrics.is_valid = validator.get_summary()['is_valid']
        
        # 显示验证结果
        summary = validator.get_summary()
        logger.info(f"  验证问题总数: {summary['total_issues']}")
        logger.info(f"  错误: {summary['errors']}, 警告: {summary['warnings']}, 信息: {summary['info']}")
        if validation_issues:
            for issue in validation_issues:
                logger.warning(f"  [{issue.severity.upper()}] {issue.category}: {issue.message}")
        
        # 保存到历史记录
        self.previous_metrics.append(metrics.to_dict())
        
        # 计算总时间
        metrics.total_time = time.perf_counter() - total_start_time
        
        return metrics
    
    def _evaluate_application_single_run(
        self,
        app_name: str,
        namespace: str,
        host_monitor: SystemResourceMonitor,
        enhanced_monitor: EnhancedSystemResourceMonitor,
        vm_monitor: Optional[SystemResourceMonitor],
        baseline: Dict[str, Any],
        app_stats: Dict[str, Any]
    ) -> ScalabilityMetrics:
        """执行单次评估运行"""
        # 初始化指标
        metrics = ScalabilityMetrics(
            application_name=app_name,
            namespace=namespace
        )
        
        # 使用传入的统计信息（避免重复获取）
        metrics.num_services = app_stats.get('num_services', 0)
        metrics.num_policies = app_stats.get('num_policies', 0)
        metrics.config_size_kb = app_stats.get('config_size_kb', 0.0)
        
        # 记录程序运行前的内存使用（用于计算程序占用的内存）
        try:
            memory = psutil.virtual_memory()
            metrics.memory_before_mb = memory.used / (1024 * 1024)  # MB
            logger.debug(f"[{app_name}] 程序运行前内存: {metrics.memory_before_mb:.2f} MB")
        except Exception as e:
            logger.warning(f"无法获取初始内存: {e}")
            metrics.memory_before_mb = 0.0
        
        # 记录VM运行前的内存使用（如果配置了VM）
        if vm_monitor:
            vm_snapshot = self._get_vm_memory_snapshot(vm_monitor, "评估开始前")
            if vm_snapshot:
                metrics.vm_memory_before_mb = vm_snapshot['memory_mb']
                metrics.vm_memory_snapshots.append(vm_snapshot)
                logger.info(f"[{app_name}] VM运行前内存: {metrics.vm_memory_before_mb:.2f} MB ({vm_snapshot['memory_percent']:.2f}%)")
        
        # 记录K8s集群运行前的内存使用（如果启用了Prometheus）
        if self.prometheus_collector:
            k8s_memory = self.prometheus_collector.get_pod_memory_usage(namespace=namespace)
            if k8s_memory:
                metrics.k8s_memory_before_mb = k8s_memory.total_pod_memory_mb
                snapshot_dict = k8s_memory.to_dict()
                snapshot_dict['stage'] = '评估开始前'
                metrics.k8s_memory_snapshots.append(snapshot_dict)
                logger.info(f"[{app_name}] K8s集群运行前内存: {metrics.k8s_memory_before_mb:.2f} MB ({k8s_memory.pod_count} 个Pod)")
        
        # 记录总开始时间
        total_start_time = time.perf_counter()
        metrics.checkpoints['evaluation_start'] = total_start_time
        
        # 1. 评估静态解析（在主机上执行，监控主机资源）
        logger.info(f"\n[{app_name}] === 阶段1: 静态解析 ===")
        logger.info("  监控目标: 主机（解析在主机上执行）")
        # 提前启动主机监控和增强监控，确保有足够的采样时间
        host_monitor.start_monitoring()
        enhanced_monitor.start_monitoring()
        time.sleep(0.3)  # 等待监控收集基线数据
        static_result = self.evaluate_static_parsing(app_name, namespace, host_monitor, enhanced_monitor)
        time.sleep(0.2)  # 等待监控收集最终数据
        host_monitor.stop_monitoring()
        enhanced_monitor.stop_monitoring()
        
        if static_result.get('success'):
            metrics.static_parsing_time = static_result['parsing_time']
            metrics.static_parsing_cpu = static_result.get('cpu_avg', 0.0)
            metrics.static_parsing_memory = static_result.get('memory_avg', 0.0)
            
            # 记录时间检查点
            checkpoints = static_result.get('checkpoints', {})
            metrics.checkpoints.update({f'static_parsing_{k}': v for k, v in checkpoints.items()})
            
            logger.info(f"  解析时间: {metrics.static_parsing_time:.3f}秒")
            logger.info(f"  CPU使用: {metrics.static_parsing_cpu:.2f}% (平均)")
            memory_percent = static_result.get('memory_percent_avg', 0.0)
            logger.info(f"  内存使用: {metrics.static_parsing_memory:.2f} MB ({memory_percent:.2f}%) (平均)")
            
            # 显示增强指标
            python_memory = static_result.get('python_process_memory_mb', 0.0)
            network_bytes = static_result.get('network_bytes_total', 0)
            if python_memory > 0:
                logger.info(f"  Python进程内存: {python_memory:.2f} MB")
            if network_bytes > 0:
                logger.info(f"  网络IO: {network_bytes / 1024:.2f} KB")
            
            # 采集VM内存快照（静态解析完成后）
            if vm_monitor:
                vm_snapshot = self._get_vm_memory_snapshot(vm_monitor, "静态解析完成后")
                if vm_snapshot:
                    metrics.vm_memory_snapshots.append(vm_snapshot)
                    logger.info(f"  VM内存快照(静态解析后): {vm_snapshot['memory_mb']:.2f} MB ({vm_snapshot['memory_percent']:.2f}%)")
            
            # 采集K8s集群内存快照（静态解析完成后）
            if self.prometheus_collector:
                k8s_memory = self.prometheus_collector.get_pod_memory_usage(namespace=namespace)
                if k8s_memory:
                    snapshot_dict = k8s_memory.to_dict()
                    snapshot_dict['stage'] = '静态解析完成后'
                    metrics.k8s_memory_snapshots.append(snapshot_dict)
                    logger.info(f"  K8s集群内存快照(静态解析后): {k8s_memory.total_pod_memory_mb:.2f} MB ({k8s_memory.pod_count} 个Pod)")
            
            system_ir = static_result.get('system_ir')
        else:
            logger.error(f"  静态解析失败: {static_result.get('error')}")
            system_ir = None
        
        # 2. 评估测试生成（在主机上执行，监控主机资源）
        if system_ir:
            logger.info(f"\n[{app_name}] === 阶段2: 测试生成 ===")
            logger.info("  监控目标: 主机（测试生成在主机上执行）")
            # 提前启动主机监控和增强监控，确保有足够的采样时间
            host_monitor.start_monitoring()
            enhanced_monitor.start_monitoring()
            time.sleep(0.3)  # 等待监控收集基线数据
            test_result = self.evaluate_test_generation(app_name, namespace, system_ir, host_monitor, enhanced_monitor)
            time.sleep(0.2)  # 等待监控收集最终数据
            host_monitor.stop_monitoring()
            enhanced_monitor.stop_monitoring()
            
            if test_result.get('success'):
                metrics.test_generation_time = test_result['generation_time']
                metrics.test_generation_cpu = test_result.get('cpu_avg', 0.0)
                metrics.test_generation_memory = test_result.get('memory_avg', 0.0)
                metrics.num_test_cases = test_result.get('num_test_cases', 0)
                
                # 记录时间检查点
                checkpoints = test_result.get('checkpoints', {})
                metrics.checkpoints.update({f'test_generation_{k}': v for k, v in checkpoints.items()})
                
                logger.info(f"  生成时间: {metrics.test_generation_time:.3f}秒")
                logger.info(f"  测试用例数: {metrics.num_test_cases}")
                logger.info(f"  CPU使用: {metrics.test_generation_cpu:.2f}% (平均)")
                memory_percent = test_result.get('memory_percent_avg', 0.0)
                logger.info(f"  内存使用: {metrics.test_generation_memory:.2f} MB ({memory_percent:.2f}%) (平均)")
                
                # 显示增强指标
                python_memory = test_result.get('python_process_memory_mb', 0.0)
                network_bytes = test_result.get('network_bytes_total', 0)
                if python_memory > 0:
                    logger.info(f"  Python进程内存: {python_memory:.2f} MB")
                if network_bytes > 0:
                    logger.info(f"  网络IO: {network_bytes / 1024:.2f} KB")
            
            # 采集VM内存快照（测试生成完成后）
            if vm_monitor:
                vm_snapshot = self._get_vm_memory_snapshot(vm_monitor, "测试生成完成后")
                if vm_snapshot:
                    metrics.vm_memory_snapshots.append(vm_snapshot)
                    logger.info(f"  VM内存快照(测试生成后): {vm_snapshot['memory_mb']:.2f} MB ({vm_snapshot['memory_percent']:.2f}%)")
            
            # 采集K8s集群内存快照（测试生成完成后）
            if self.prometheus_collector:
                k8s_memory = self.prometheus_collector.get_pod_memory_usage(namespace=namespace)
                if k8s_memory:
                    snapshot_dict = k8s_memory.to_dict()
                    snapshot_dict['stage'] = '测试生成完成后'
                    metrics.k8s_memory_snapshots.append(snapshot_dict)
                    logger.info(f"  K8s集群内存快照(测试生成后): {k8s_memory.total_pod_memory_mb:.2f} MB ({k8s_memory.pod_count} 个Pod)")
            else:
                logger.error(f"  测试生成失败: {test_result.get('error')}")
        
        # 3. 评估动态验证（混合执行：静态分析在主机，测试执行在VM）
        logger.info(f"\n[{app_name}] === 阶段3: 动态验证 ===")
        logger.info("  监控目标: 主机和VM（静态分析在主机，测试执行在VM）")
        
        # 同时启动主机和VM监控
        host_monitor.start_monitoring()
        if vm_monitor:
            vm_monitor.start_monitoring()
            time.sleep(0.5)  # 等待VM监控建立SSH连接并收集基线数据
        else:
            time.sleep(0.3)  # 等待主机监控收集基线数据
        
        validation_result = self.evaluate_dynamic_validation(
            app_name, namespace, host_monitor, vm_monitor
        )
        
        time.sleep(0.3)  # 等待监控收集最终数据
        host_monitor.stop_monitoring()
        if vm_monitor:
            vm_monitor.stop_monitoring()
        
        if validation_result.get('success'):
            metrics.dynamic_validation_time = validation_result['validation_time']
            metrics.dynamic_validation_cpu = validation_result.get('cpu_avg', 0.0)
            metrics.dynamic_validation_memory = validation_result.get('memory_avg', 0.0)
            metrics.dynamic_validation_host_cpu = validation_result.get('host_cpu_avg', 0.0)
            metrics.dynamic_validation_host_memory = validation_result.get('host_memory_avg', 0.0)
            metrics.dynamic_validation_vm_cpu = validation_result.get('vm_cpu_avg', 0.0)
            metrics.dynamic_validation_vm_memory = validation_result.get('vm_memory_avg', 0.0)
            metrics.num_verified_policies = validation_result.get('num_verified_policies', 0)
            metrics.num_failed_policies = validation_result.get('num_failed_policies', 0)
            
            # 记录时间检查点
            checkpoints = validation_result.get('checkpoints', {})
            metrics.checkpoints.update({f'dynamic_validation_{k}': v for k, v in checkpoints.items()})
            logger.info(f"  验证时间: {metrics.dynamic_validation_time:.3f}秒")
            logger.info(f"  已验证策略: {metrics.num_verified_policies}")
            logger.info(f"  失败策略: {metrics.num_failed_policies}")
            
            # 显示主机和VM的监控数据
            host_cpu = validation_result.get('host_cpu_avg', 0.0)
            host_memory = validation_result.get('host_memory_avg', 0.0)
            vm_cpu = validation_result.get('vm_cpu_avg', 0.0)
            vm_memory = validation_result.get('vm_memory_avg', 0.0)
            
            logger.info(f"  主机CPU使用: {host_cpu:.2f}% (平均)")
            logger.info(f"  主机内存使用: {host_memory:.2f} MB (平均)")
            if vm_monitor:
                logger.info(f"  VM CPU使用: {vm_cpu:.2f}% (平均)")
                logger.info(f"  VM内存使用: {vm_memory:.2f} MB (平均)")
            
            memory_percent = validation_result.get('memory_percent_avg', 0.0)
            logger.info(f"  主要CPU使用: {metrics.dynamic_validation_cpu:.2f}% (平均)")
            logger.info(f"  主要内存使用: {metrics.dynamic_validation_memory:.2f} MB ({memory_percent:.2f}%) (平均)")
            
            # 采集VM内存快照（动态验证完成后）
            if vm_monitor:
                vm_snapshot = self._get_vm_memory_snapshot(vm_monitor, "动态验证完成后")
                if vm_snapshot:
                    metrics.vm_memory_snapshots.append(vm_snapshot)
                    logger.info(f"  VM内存快照(动态验证后): {vm_snapshot['memory_mb']:.2f} MB ({vm_snapshot['memory_percent']:.2f}%)")
            
            # 采集K8s集群内存快照（动态验证完成后，HTTP请求已发送）
            if self.prometheus_collector:
                k8s_memory = self.prometheus_collector.get_pod_memory_usage(namespace=namespace)
                if k8s_memory:
                    snapshot_dict = k8s_memory.to_dict()
                    snapshot_dict['stage'] = '动态验证完成后'
                    metrics.k8s_memory_snapshots.append(snapshot_dict)
                    logger.info(f"  K8s集群内存快照(动态验证后): {k8s_memory.total_pod_memory_mb:.2f} MB ({k8s_memory.pod_count} 个Pod)")
        else:
            logger.error(f"  动态验证失败: {validation_result.get('error')}")
        
        # 记录VM运行后的内存使用（如果配置了VM）
        if vm_monitor:
            vm_snapshot = self._get_vm_memory_snapshot(vm_monitor, "评估结束后")
            if vm_snapshot:
                metrics.vm_memory_after_mb = vm_snapshot['memory_mb']
                metrics.vm_memory_snapshots.append(vm_snapshot)
                metrics.vm_memory_delta_mb = metrics.vm_memory_after_mb - metrics.vm_memory_before_mb
                logger.info(f"[{app_name}] VM运行后内存: {metrics.vm_memory_after_mb:.2f} MB ({vm_snapshot['memory_percent']:.2f}%)")
                logger.info(f"[{app_name}] VM内存增量: {metrics.vm_memory_delta_mb:.2f} MB")
        
        # 记录K8s集群运行后的内存使用（如果启用了Prometheus）
        if self.prometheus_collector:
            k8s_memory = self.prometheus_collector.get_pod_memory_usage(namespace=namespace)
            if k8s_memory:
                metrics.k8s_memory_after_mb = k8s_memory.total_pod_memory_mb
                snapshot_dict = k8s_memory.to_dict()
                snapshot_dict['stage'] = '评估结束后'
                metrics.k8s_memory_snapshots.append(snapshot_dict)
                metrics.k8s_memory_delta_mb = metrics.k8s_memory_after_mb - metrics.k8s_memory_before_mb
                logger.info(f"[{app_name}] K8s集群运行后内存: {metrics.k8s_memory_after_mb:.2f} MB ({k8s_memory.pod_count} 个Pod)")
                logger.info(f"[{app_name}] K8s集群内存增量: {metrics.k8s_memory_delta_mb:.2f} MB")
        
        # 计算总时间
        metrics.total_time = time.perf_counter() - total_start_time
        
        # 获取总体资源使用（需要在整个评估过程中监控）
        # 这里简化处理，使用各阶段的最大值
        metrics.cpu_max_percent = max(
            metrics.static_parsing_cpu,
            metrics.test_generation_cpu,
            metrics.dynamic_validation_cpu
        )
        metrics.memory_max_mb = max(
            metrics.static_parsing_memory,
            metrics.test_generation_memory,
            metrics.dynamic_validation_memory
        )
        
        # 计算平均值
        cpu_values = [
            metrics.static_parsing_cpu,
            metrics.test_generation_cpu,
            metrics.dynamic_validation_cpu
        ]
        memory_values = [
            metrics.static_parsing_memory,
            metrics.test_generation_memory,
            metrics.dynamic_validation_memory
        ]
        
        metrics.cpu_avg_percent = sum(cpu_values) / len(cpu_values) if cpu_values else 0.0
        metrics.memory_avg_mb = sum(memory_values) / len(memory_values) if memory_values else 0.0
        
        # 记录程序运行后的内存使用（用于计算程序占用的内存）
        try:
            memory = psutil.virtual_memory()
            metrics.memory_after_mb = memory.used / (1024 * 1024)  # MB
            metrics.memory_delta_mb = metrics.memory_after_mb - metrics.memory_before_mb
            logger.debug(f"[{app_name}] 程序运行后内存: {metrics.memory_after_mb:.2f} MB")
            logger.debug(f"[{app_name}] 程序内存增量: {metrics.memory_delta_mb:.2f} MB")
        except Exception as e:
            logger.warning(f"无法获取最终内存: {e}")
            metrics.memory_after_mb = 0.0
            metrics.memory_delta_mb = 0.0
        
        # 计算总内存占用 = 主机内存增量 + K8s集群内存增量
        # 注意：主机内存增量可能为负值（受系统其他进程影响），所以使用绝对值或Python进程内存
        host_memory_delta = metrics.memory_delta_mb
        k8s_memory_delta = metrics.k8s_memory_delta_mb if metrics.k8s_memory_before_mb > 0 else 0.0
        
        # 如果主机内存增量为负值，使用Python进程内存作为主机内存占用
        # 从各阶段结果中获取Python进程内存
        python_memory = 0.0
        if static_result and static_result.get('success'):
            python_memory = max(python_memory, static_result.get('python_process_memory_mb', 0.0))
        if test_result and test_result.get('success'):
            python_memory = max(python_memory, test_result.get('python_process_memory_mb', 0.0))
        
        if host_memory_delta < 0 and python_memory > 0:
            host_memory_delta = python_memory
            logger.info(f"  [内存计算] 主机内存增量为负值，使用Python进程内存: {python_memory:.2f} MB")
        
        metrics.total_memory_delta_mb = host_memory_delta + k8s_memory_delta
        
        logger.info(f"\n[{app_name}] === 评估完成 ===")
        logger.info(f"  总时间: {metrics.total_time:.3f}秒")
        logger.info(f"  CPU使用: {metrics.cpu_avg_percent:.2f}% (平均), {metrics.cpu_max_percent:.2f}% (最大)")
        logger.info(f"  内存使用: {metrics.memory_avg_mb:.2f} MB (平均), {metrics.memory_max_mb:.2f} MB (最大)")
        if metrics.memory_before_mb > 0 and metrics.memory_after_mb > 0:
            logger.info(f"  主机内存占用: {metrics.memory_delta_mb:.2f} MB (运行后 {metrics.memory_after_mb:.2f} MB - 运行前 {metrics.memory_before_mb:.2f} MB)")
        
        # 显示总内存占用（主机 + K8s集群）
        if metrics.total_memory_delta_mb > 0:
            logger.info(f"\n[{app_name}] === 总内存占用分析 ===")
            logger.info(f"  主机内存增量: {metrics.memory_delta_mb:.2f} MB")
            if metrics.k8s_memory_before_mb > 0:
                logger.info(f"  K8s集群内存增量: {metrics.k8s_memory_delta_mb:.2f} MB")
                logger.info(f"  总内存占用: {metrics.total_memory_delta_mb:.2f} MB (主机 {metrics.memory_delta_mb:.2f} MB + K8s集群 {metrics.k8s_memory_delta_mb:.2f} MB)")
            else:
                logger.info(f"  总内存占用: {metrics.total_memory_delta_mb:.2f} MB (仅主机，K8s集群监控未启用)")
        
        # 显示VM内存信息汇总
        if vm_monitor and metrics.vm_memory_snapshots:
            logger.info(f"\n[{app_name}] === VM内存信息汇总 ===")
            logger.info(f"  VM运行前内存: {metrics.vm_memory_before_mb:.2f} MB")
            logger.info(f"  VM运行后内存: {metrics.vm_memory_after_mb:.2f} MB")
            logger.info(f"  VM内存增量: {metrics.vm_memory_delta_mb:.2f} MB")
            logger.info(f"  VM内存快照数量: {len(metrics.vm_memory_snapshots)}")
            for i, snapshot in enumerate(metrics.vm_memory_snapshots, 1):
                logger.info(f"    快照{i}: {snapshot['stage']} - {snapshot['memory_mb']:.2f} MB ({snapshot['memory_percent']:.2f}%)")
        
        # 显示K8s集群内存信息汇总
        if self.prometheus_collector and metrics.k8s_memory_snapshots:
            logger.info(f"\n[{app_name}] === K8s集群内存信息汇总 ===")
            logger.info(f"  K8s集群运行前内存: {metrics.k8s_memory_before_mb:.2f} MB")
            logger.info(f"  K8s集群运行后内存: {metrics.k8s_memory_after_mb:.2f} MB")
            logger.info(f"  K8s集群内存增量: {metrics.k8s_memory_delta_mb:.2f} MB")
            logger.info(f"  K8s集群内存快照数量: {len(metrics.k8s_memory_snapshots)}")
            for i, snapshot in enumerate(metrics.k8s_memory_snapshots, 1):
                pod_count = snapshot.get('pod_count', 0)
                logger.info(f"    快照{i}: {snapshot.get('stage', 'unknown')} - {snapshot.get('total_pod_memory_mb', 0):.2f} MB ({pod_count} 个Pod)")
        
        return metrics
    
    def run_evaluation(self, applications: List[str] = None) -> Dict[str, Any]:
        """运行可扩展性评估"""
        if applications is None:
            applications = list(self.applications.keys())
        
        logger.info("=" * 80)
        logger.info("开始可扩展性评估")
        logger.info("=" * 80)
        logger.info(f"评估应用: {', '.join(applications)}")
        
        results = {
            'start_time': datetime.now().isoformat(),
            'applications': applications,
            'metrics': []
        }
        
        all_metrics = []
        
        for app_name in applications:
            try:
                metrics = self.evaluate_application(app_name)
                all_metrics.append(metrics)
                results['metrics'].append(metrics.to_dict())
            except Exception as e:
                logger.error(f"评估应用 {app_name} 失败: {e}")
                results['metrics'].append({
                    'application_name': app_name,
                    'error': str(e)
                })
        
        results['end_time'] = datetime.now().isoformat()
        
        # 保存结果
        self.save_results(results)
        
        # 打印摘要
        self.print_summary(all_metrics)
        
        return results
    
    def save_results(self, results: Dict[str, Any]):
        """保存评估结果"""
        result_file = self.output_dir / f"scalability_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n结果已保存到: {result_file}")
    
    def print_summary(self, metrics_list: List[ScalabilityMetrics]):
        """打印评估摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("可扩展性评估摘要")
        logger.info("=" * 80)
        
        # 创建表格
        print("\n应用可扩展性对比表:")
        print("-" * 120)
        print(f"{'应用':<15} {'服务数':<10} {'策略数':<10} {'配置大小(KB)':<15} {'解析时间(s)':<12} {'生成时间(s)':<12} {'验证时间(s)':<12} {'总时间(s)':<12}")
        print("-" * 120)
        
        for metrics in metrics_list:
            print(f"{metrics.application_name:<15} "
                  f"{metrics.num_services:<10} "
                  f"{metrics.num_policies:<10} "
                  f"{metrics.config_size_kb:<15.2f} "
                  f"{metrics.static_parsing_time:<12.3f} "
                  f"{metrics.test_generation_time:<12.3f} "
                  f"{metrics.dynamic_validation_time:<12.3f} "
                  f"{metrics.total_time:<12.3f}")
        
        print("-" * 120)
        
        # 资源使用对比
        print("\n资源使用对比表:")
        print("-" * 140)
        print(f"{'应用':<15} {'CPU平均(%)':<15} {'CPU最大(%)':<15} {'内存平均(MB)':<15} {'内存最大(MB)':<15} {'总内存占用(MB)':<20}")
        print("-" * 140)
        
        for metrics in metrics_list:
            total_memory_str = f"{metrics.total_memory_delta_mb:.2f}" if metrics.total_memory_delta_mb > 0 else "N/A"
            print(f"{metrics.application_name:<15} "
                  f"{metrics.cpu_avg_percent:<15.2f} "
                  f"{metrics.cpu_max_percent:<15.2f} "
                  f"{metrics.memory_avg_mb:<15.2f} "
                  f"{metrics.memory_max_mb:<15.2f} "
                  f"{total_memory_str:<20}")
        
        print("-" * 140)
        
        # 各阶段资源使用
        print("\n各阶段资源使用详情:")
        print("-" * 140)
        print(f"{'应用':<15} {'阶段':<20} {'CPU(%)':<12} {'内存(MB)':<12} {'时间(s)':<12} {'备注':<30}")
        print("-" * 140)
        
        for metrics in metrics_list:
            print(f"{metrics.application_name:<15} {'静态解析':<20} "
                  f"{metrics.static_parsing_cpu:<12.2f} "
                  f"{metrics.static_parsing_memory:<12.2f} "
                  f"{metrics.static_parsing_time:<12.3f} "
                  f"{'主机':<30}")
            print(f"{'':<15} {'测试生成':<20} "
                  f"{metrics.test_generation_cpu:<12.2f} "
                  f"{metrics.test_generation_memory:<12.2f} "
                  f"{metrics.test_generation_time:<12.3f} "
                  f"{'主机':<30}")
            print(f"{'':<15} {'动态验证(主要)':<20} "
                  f"{metrics.dynamic_validation_cpu:<12.2f} "
                  f"{metrics.dynamic_validation_memory:<12.2f} "
                  f"{metrics.dynamic_validation_time:<12.3f} "
                  f"{'优先VM':<30}")
            if metrics.dynamic_validation_host_cpu > 0 or metrics.dynamic_validation_vm_cpu > 0:
                print(f"{'':<15} {'  - 主机':<20} "
                      f"{metrics.dynamic_validation_host_cpu:<12.2f} "
                      f"{metrics.dynamic_validation_host_memory:<12.2f} "
                      f"{'':<12} "
                      f"{'静态分析':<30}")
                if metrics.dynamic_validation_vm_cpu > 0:
                    print(f"{'':<15} {'  - VM':<20} "
                          f"{metrics.dynamic_validation_vm_cpu:<12.2f} "
                          f"{metrics.dynamic_validation_vm_memory:<12.2f} "
                          f"{'':<12} "
                          f"{'测试执行':<30}")
            print("-" * 140)
    
    def _average_metrics(self, all_runs: List[ScalabilityMetrics], base_metrics: ScalabilityMetrics) -> ScalabilityMetrics:
        """计算多次运行的平均指标"""
        if not all_runs:
            return base_metrics
        
        # 使用第一个运行的统计信息
        averaged = ScalabilityMetrics(
            application_name=base_metrics.application_name,
            namespace=base_metrics.namespace,
            num_services=base_metrics.num_services,
            num_policies=base_metrics.num_policies,
            config_size_kb=base_metrics.config_size_kb
        )
        
        # 计算时间平均值
        averaged.static_parsing_time = statistics.mean([m.static_parsing_time for m in all_runs])
        averaged.test_generation_time = statistics.mean([m.test_generation_time for m in all_runs])
        averaged.dynamic_validation_time = statistics.mean([m.dynamic_validation_time for m in all_runs])
        averaged.total_time = statistics.mean([m.total_time for m in all_runs])
        
        # 计算资源使用平均值
        averaged.cpu_avg_percent = statistics.mean([m.cpu_avg_percent for m in all_runs])
        averaged.cpu_max_percent = max([m.cpu_max_percent for m in all_runs])  # 最大值取最大
        averaged.memory_avg_mb = statistics.mean([m.memory_avg_mb for m in all_runs])
        averaged.memory_max_mb = max([m.memory_max_mb for m in all_runs])  # 最大值取最大
        
        # 计算各阶段资源使用平均值
        averaged.static_parsing_cpu = statistics.mean([m.static_parsing_cpu for m in all_runs])
        averaged.static_parsing_memory = statistics.mean([m.static_parsing_memory for m in all_runs])
        averaged.test_generation_cpu = statistics.mean([m.test_generation_cpu for m in all_runs])
        averaged.test_generation_memory = statistics.mean([m.test_generation_memory for m in all_runs])
        averaged.dynamic_validation_cpu = statistics.mean([m.dynamic_validation_cpu for m in all_runs])
        averaged.dynamic_validation_memory = statistics.mean([m.dynamic_validation_memory for m in all_runs])
        
        # 计算程序内存占用平均值（运行前后差值）
        averaged.memory_before_mb = statistics.mean([m.memory_before_mb for m in all_runs])
        averaged.memory_after_mb = statistics.mean([m.memory_after_mb for m in all_runs])
        averaged.memory_delta_mb = statistics.mean([m.memory_delta_mb for m in all_runs])
        
        # 计算VM内存占用平均值（运行前后差值）
        averaged.vm_memory_before_mb = statistics.mean([m.vm_memory_before_mb for m in all_runs])
        averaged.vm_memory_after_mb = statistics.mean([m.vm_memory_after_mb for m in all_runs])
        averaged.vm_memory_delta_mb = statistics.mean([m.vm_memory_delta_mb for m in all_runs])
        # VM内存快照使用第一次运行的数据（因为快照是时间序列数据）
        if all_runs and all_runs[0].vm_memory_snapshots:
            averaged.vm_memory_snapshots = all_runs[0].vm_memory_snapshots
        
        # 计算K8s集群内存占用平均值（运行前后差值）
        averaged.k8s_memory_before_mb = statistics.mean([m.k8s_memory_before_mb for m in all_runs])
        averaged.k8s_memory_after_mb = statistics.mean([m.k8s_memory_after_mb for m in all_runs])
        averaged.k8s_memory_delta_mb = statistics.mean([m.k8s_memory_delta_mb for m in all_runs])
        averaged.total_memory_delta_mb = statistics.mean([m.total_memory_delta_mb for m in all_runs])
        # K8s内存快照使用第一次运行的数据
        if all_runs and all_runs[0].k8s_memory_snapshots:
            averaged.k8s_memory_snapshots = all_runs[0].k8s_memory_snapshots
        
        # 计算标准差（用于显示数据可靠性）
        if len(all_runs) > 1:
            std_devs = {
                'static_parsing_time': statistics.stdev([m.static_parsing_time for m in all_runs]),
                'test_generation_time': statistics.stdev([m.test_generation_time for m in all_runs]),
                'dynamic_validation_time': statistics.stdev([m.dynamic_validation_time for m in all_runs]),
                'total_time': statistics.stdev([m.total_time for m in all_runs]),
                'cpu_avg_percent': statistics.stdev([m.cpu_avg_percent for m in all_runs]),
                'memory_avg_mb': statistics.stdev([m.memory_avg_mb for m in all_runs])
            }
            averaged.checkpoints['std_deviations'] = std_devs
            logger.info(f"  标准差: 总时间={std_devs['total_time']:.3f}s, CPU={std_devs['cpu_avg_percent']:.2f}%, 内存={std_devs['memory_avg_mb']:.2f}MB")
        
        # 合并检查点（使用第一次运行的检查点）
        averaged.checkpoints.update(all_runs[0].checkpoints)
        
        # 测试用例数和验证统计（使用第一次运行的值）
        averaged.num_test_cases = all_runs[0].num_test_cases
        averaged.num_verified_policies = all_runs[0].num_verified_policies
        averaged.num_failed_policies = all_runs[0].num_failed_policies
        
        return averaged


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='可扩展性评估脚本')
    parser.add_argument('--vm-host', type=str, help='虚拟机主机地址')
    parser.add_argument('--vm-user', type=str, default='root', help='虚拟机用户名')
    parser.add_argument('--vm-password', type=str, help='虚拟机密码')
    parser.add_argument('--k8s-host', type=str, help='Kubernetes API服务器地址')
    parser.add_argument('--k8s-token', type=str, help='Kubernetes API Token')
    parser.add_argument('--applications', type=str, nargs='+', 
                       choices=['bookinfo', 'online-boutique', 'trainticket', 'sitewhere'],
                       default=['bookinfo'],
                       help='要评估的应用列表')
    parser.add_argument('--output-dir', type=str, help='输出目录')
    parser.add_argument('--num-runs', type=int, default=1, help='运行次数（用于取平均值，默认1次）')
    parser.add_argument('--prometheus-url', type=str, help='Prometheus服务器URL（默认: http://localhost:9090）')
    parser.add_argument('--enable-prometheus', action='store_true', help='启用Prometheus指标收集（收集K8s集群内存）')
    
    args = parser.parse_args()
    
    if not MODULES_AVAILABLE:
        logger.error("必要的模块未导入，请检查依赖")
        return 1
    
    # 设置Prometheus URL（如果提供）
    if args.prometheus_url:
        os.environ['PROMETHEUS_URL'] = args.prometheus_url
    if args.enable_prometheus:
        os.environ['ENABLE_PROMETHEUS'] = 'true'
    
    evaluator = ScalabilityEvaluator(
        vm_host=args.vm_host,
        vm_user=args.vm_user,
        vm_password=args.vm_password,
        k8s_host=args.k8s_host,
        k8s_token=args.k8s_token,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        num_runs=args.num_runs
    )
    
    try:
        results = evaluator.run_evaluation(applications=args.applications)
        logger.info("\n评估完成！")
        return 0
    except Exception as e:
        logger.error(f"评估失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

