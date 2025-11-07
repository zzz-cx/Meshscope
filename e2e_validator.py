#!/usr/bin/env python3
"""
MeshScope 端到端验证框架
整合所有模块，实现完整的验证流程，并记录详细的执行信息
"""
import os
import sys
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field, asdict
import logging

# 添加项目路径
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("e2e_validation.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("e2e_validation")


@dataclass
class StepResult:
    """步骤执行结果"""
    step_name: str
    step_id: str
    success: bool
    start_time: float
    end_time: float
    duration: float
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_traceback: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'step_name': self.step_name,
            'step_id': self.step_id,
            'success': self.success,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': round(self.duration, 3),
            'inputs': self.inputs,
            'outputs': self._clean_outputs_for_json(),  # 在序列化时才清理
            'error': self.error,
            'error_traceback': self.error_traceback
        }
    
    def _clean_outputs_for_json(self) -> Dict[str, Any]:
        """清理outputs用于JSON序列化"""
        if not isinstance(self.outputs, dict):
            return self.outputs
        
        cleaned = {}
        for key, value in self.outputs.items():
            # 跳过SystemIR等复杂对象
            if key == 'system_ir' and hasattr(value, '__class__') and not isinstance(value, str):
                cleaned[key] = f"<{value.__class__.__name__} object (not serialized)>"
            elif isinstance(value, (datetime,)):
                cleaned[key] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
            elif isinstance(value, dict):
                cleaned[key] = self._clean_dict_for_json(value)
            elif isinstance(value, list):
                cleaned[key] = [self._clean_dict_for_json(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, (str, int, float, bool, type(None))):
                cleaned[key] = value
            else:
                # 对于其他复杂对象，转换为字符串
                cleaned[key] = str(value)
        return cleaned
    
    def _clean_dict_for_json(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """递归清理字典"""
        cleaned = {}
        for key, value in obj.items():
            if isinstance(value, (datetime,)):
                cleaned[key] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
            elif isinstance(value, dict):
                cleaned[key] = self._clean_dict_for_json(value)
            elif isinstance(value, list):
                cleaned[key] = [self._clean_dict_for_json(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, (str, int, float, bool, type(None))):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned


@dataclass
class E2EResult:
    """端到端验证结果"""
    timestamp: str
    total_duration: float
    success: bool
    steps: List[StepResult] = field(default_factory=list)
    static_pipeline_duration: float = 0.0
    dynamic_pipeline_duration: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'total_duration': round(self.total_duration, 3),
            'success': self.success,
            'static_pipeline_duration': round(self.static_pipeline_duration, 3),
            'dynamic_pipeline_duration': round(self.dynamic_pipeline_duration, 3),
            'steps': [step.to_dict() for step in self.steps]
        }


class E2EValidator:
    """端到端验证器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.results = E2EResult(
            timestamp=datetime.now().isoformat(),
            total_duration=0.0,
            success=False
        )
        
        # 配置参数
        self.vm_host = config.get('vm_host', '192.168.92.131')
        self.vm_user = config.get('vm_user', 'root')
        self.vm_password = config.get('vm_password', '')
        self.namespace = config.get('namespace', 'default')
        self.ingress_url = config.get('ingress_url', '')
        
        # 输出目录
        self.output_dir = Path(config.get('output_dir', 'results/e2e_validation'))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 步骤计数器
        self.step_counter = 0
    
    def record_step(self, step_name: str, func, *args, **kwargs) -> StepResult:
        """记录步骤执行"""
        self.step_counter += 1
        step_id = f"step_{self.step_counter:02d}"
        
        step_result = StepResult(
            step_name=step_name,
            step_id=step_id,
            success=False,
            start_time=time.time(),
            end_time=0.0,
            duration=0.0,
            inputs={'args': str(args), 'kwargs': kwargs}
        )
        
        logger.info(f"[{step_id}] 开始执行: {step_name}")
        logger.info(f"  输入参数: {json.dumps(kwargs, indent=2, ensure_ascii=False)}")
        
        try:
            # 执行步骤
            outputs = func(*args, **kwargs)
            
            step_result.end_time = time.time()
            step_result.duration = step_result.end_time - step_result.start_time
            step_result.success = True
            
            if isinstance(outputs, dict):
                # 保存原始输出（用于步骤间传递）
                step_result.outputs = outputs.copy()
                # 清理后的输出只用于JSON序列化，不影响原始对象
                # 在保存结果时再清理
            else:
                step_result.outputs = {'result': str(outputs)}
            
            logger.info(f"[{step_id}] 执行成功: {step_name} (耗时: {step_result.duration:.3f}秒)")
            
        except Exception as e:
            step_result.end_time = time.time()
            step_result.duration = step_result.end_time - step_result.start_time
            step_result.success = False
            step_result.error = str(e)
            step_result.error_traceback = traceback.format_exc()
            
            logger.error(f"[{step_id}] 执行失败: {step_name}")
            logger.error(f"  错误: {str(e)}")
            logger.error(f"  详情:\n{step_result.error_traceback}")
            
            # 即使失败也继续执行，但记录错误
        
        self.results.steps.append(step_result)
        return step_result
    
    
    def step1_fetch_configs(self) -> Dict[str, Any]:
        """步骤1: 使用监控器获取配置"""
        # 直接导入 IstioAPI，避免通过 __init__.py 导入
        import sys
        import os
        
        # 保存原始路径
        original_path = sys.path[:]
        
        try:
            monitor_path = project_root / "istio_config_parser" / "istio_monitor"
            if str(monitor_path) not in sys.path:
                sys.path.insert(0, str(monitor_path))
            
            from istio_api import IstioAPI
            from kubernetes import client
            
            # 手动创建监控器逻辑，避免导入 IstioSidecarMonitor
            # 这里简化实现，直接使用 IstioAPI
            api = IstioAPI(
                host="localhost",
                port=8080,
                namespace="istio-system",
                use_vm=True,
                vm_host=self.vm_host,
                vm_port=22,
                vm_user=self.vm_user,
                vm_password=self.vm_password
            )
            
            # 获取控制平面配置
            control_plane_configs = {}
            try:
                # 获取 VirtualServices
                vs_list = api.get_virtual_services(namespace=self.namespace)
                if vs_list:
                    control_plane_configs['virtualservices'] = vs_list
                
                # 获取 DestinationRules
                dr_list = api.get_destination_rules(namespace=self.namespace)
                if dr_list:
                    control_plane_configs['destinationrules'] = dr_list
            except Exception as e:
                logger.warning(f"获取控制平面配置时出错: {e}")
            
            # 获取数据平面配置
            data_plane_configs = {}
            try:
                proxies = api.get_proxies()
                if proxies:
                    selected_proxy = proxies[0]
                    routes = api.get_proxy_config(selected_proxy, "routes")
                    if routes:
                        data_plane_configs['routes'] = routes
            except Exception as e:
                logger.warning(f"获取数据平面配置时出错: {e}")
            
            return {
                'config_files_fetched': len(control_plane_configs) + len(data_plane_configs),
                'control_plane_configs': control_plane_configs,
                'data_plane_configs': data_plane_configs,
                'control_plane_dir': str(project_root / "istio_config_parser/istio_monitor/istio_control_config"),
                'data_plane_dir': str(project_root / "istio_config_parser/istio_monitor/istio_sidecar_config")
            }
        finally:
            # 恢复原始路径
            sys.path[:] = original_path
    
    def step2_parse_configs(self, config_dirs: Dict[str, str]) -> Dict[str, Any]:
        """步骤2: 解析静态配置"""
        # 确保项目根目录在路径中
        import sys
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from istio_config_parser.main_parser import parse_unified_from_dir
        
        system_ir = parse_unified_from_dir(
            control_plane_dir=config_dirs['control_plane_dir'],
            data_plane_dir=config_dirs['data_plane_dir'],
            namespace=self.namespace,
            enable_parallel=True,
            max_workers=None
        )
        
        summary = system_ir.get_summary()
        
        return {
            'system_ir': system_ir,
            'summary': summary,
            'total_services': summary.get('total_services', 0),
            'consistent_services': summary.get('consistent_services', 0),
            # 注意：system_ir对象不会被序列化，只保存摘要信息
            '_system_ir_saved': True
        }
    
    def step3_generate_ir(self, system_ir) -> Dict[str, Any]:
        """步骤3: 生成IR（中间表示）"""
        # 确保项目根目录在路径中
        import sys
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from istio_config_parser.models.ir_models import SimpleIRConverter
        
        # 生成简化IR
        simple_irs_cp = SimpleIRConverter.convert_system_ir_to_simple(system_ir, "control_plane")
        simple_irs_dp = SimpleIRConverter.convert_system_ir_to_simple(system_ir, "data_plane")
        
        # 保存IR
        ir_output_file = self.output_dir / "simple_ir_output.json"
        ir_data = {
            'control_plane': [ir.to_dict() for ir in simple_irs_cp],
            'data_plane': [ir.to_dict() for ir in simple_irs_dp]
        }
        
        with open(ir_output_file, 'w', encoding='utf-8') as f:
            json.dump(ir_data, f, indent=2, ensure_ascii=False)
        
        return {
            'ir_file': str(ir_output_file),
            'control_plane_ir_count': len(simple_irs_cp),
            'data_plane_ir_count': len(simple_irs_dp),
            # 注意：system_ir对象不会被序列化，IR已保存到文件
            '_system_ir_saved': True
        }
    
    def step4_generate_orthogonal_test_cases(self, ir_data: Dict[str, Any]) -> Dict[str, Any]:
        """步骤4: 基于IR生成正交测试策略"""
        # 确保项目根目录在路径中
        import sys
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        # 需要使用原有的test_case_generator
        # 首先需要将IR转换为test_case_generator所需的格式
        
        # 这里假设我们使用现有的generator，但需要准备配置文件
        generator_dir = project_root / "istio_Dynamic_Test/generator"
        
        # 检查是否存在配置文件
        config_file = generator_dir / "istio_config.json"
        
        if not config_file.exists():
            # 需要从IR生成配置文件
            # 这里简化处理，使用现有的配置
            logger.warning("未找到istio_config.json，尝试使用现有配置")
            config_file = generator_dir / "istio_config.json"
        
        from istio_Dynamic_Test.generator.test_case_generator import TestCaseGenerator
        
        generator = TestCaseGenerator(
            config_path=str(config_file),
            service_deps_path=str(generator_dir.parent / "service_dependencies.json")
        )
        
        test_cases = generator.generate()
        
        # 保存测试矩阵
        matrix_file = self.output_dir / "output_matrix.json"
        matrix_data = {
            "global_settings": {
                "ingress_url": self.ingress_url or f"http://{self.vm_host}:30476/productpage"
            },
            "test_cases": test_cases
        }
        
        with open(matrix_file, 'w', encoding='utf-8') as f:
            json.dump(matrix_data, f, indent=2, ensure_ascii=False)
        
        return {
            'matrix_file': str(matrix_file),
            'test_cases_count': len(test_cases),
            'test_cases': test_cases
        }
    
    def step5_send_dynamic_requests(self, matrix_file: str) -> Dict[str, Any]:
        """步骤5: 发送动态请求"""
        # 确保项目根目录在路径中
        import sys
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from istio_Dynamic_Test.checker.traffic_driver import TrafficDriver
        
        ssh_config = {
            'hostname': self.vm_host,  # 注意：SSHClient使用hostname而不是host
            'username': self.vm_user,
            'password': self.vm_password
        }
        
        # 设置统一的结果目录
        results_dir = project_root / "results"
        http_results_dir = results_dir / "http_results"
        envoy_logs_dir = results_dir / "envoy_logs"
        
        # 创建目录
        http_results_dir.mkdir(parents=True, exist_ok=True)
        envoy_logs_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建TrafficDriver实例
        driver = TrafficDriver(
            matrix_file=matrix_file,
            ssh_config=ssh_config,
            namespace=self.namespace
        )
        
        # 修改driver的保存路径：覆盖其内部方法
        import os
        import json
        from datetime import datetime
        
        original_save_http_result = driver._save_http_result
        
        def new_save_http_result(case_id, http_result):
            """自定义保存HTTP结果的方法"""
            # 保存到内存
            driver.http_results[case_id] = http_result
            
            # 保存到文件（使用统一的结果目录）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{case_id}_http_result_{timestamp}.json"
            filepath = http_results_dir / filename
            
            result_data = {
                'case_id': case_id,
                'timestamp': timestamp,
                'http_result': http_result
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, indent=2, ensure_ascii=False)
            
            print(f"    💾 HTTP结果已保存到: {filepath}")
        
        # 替换保存方法
        driver._save_http_result = new_save_http_result
        
        # 修改envoy_log_collector的result_dir
        driver.envoy_log_collector.result_dir = str(envoy_logs_dir)
        
        # 执行测试
        driver.run()
        
        # 获取HTTP结果
        http_results = driver.http_results
        
        return {
            'http_results': http_results,
            'test_cases_executed': len(http_results),
            'results_dir': str(results_dir),
            'http_results_dir': str(http_results_dir),
            'envoy_logs_dir': str(envoy_logs_dir)
        }
    
    def step6_collect_logs(self, results_info: Dict[str, Any]) -> Dict[str, Any]:
        """步骤6: 收集日志数据"""
        # 如果传入的是字符串（旧格式），则使用它
        if isinstance(results_info, str):
            envoy_logs_dir = Path(results_info) / "envoy_logs"
        else:
            # 从步骤5的结果中获取envoy_logs_dir
            envoy_logs_dir = Path(results_info.get('envoy_logs_dir', project_root / "results" / "envoy_logs"))
        
        envoy_logs_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志已经在步骤5中收集了，这里只需要返回路径信息
        log_files = list(envoy_logs_dir.glob("*.log")) if envoy_logs_dir.exists() else []
        
        return {
            'logs_dir': str(envoy_logs_dir),
            'log_files': [str(f) for f in log_files],
            'log_count': len(log_files)
        }
    
    def step7_dynamic_verification(self, matrix_file: str, logs_info: Dict[str, Any]) -> Dict[str, Any]:
        """步骤7: 动态验证"""
        import sys
        import os
        
        # 添加路径
        verifier_path = project_root / "istio_Dynamic_Test" / "verifier"
        sys.path.insert(0, str(verifier_path.parent))
        
        from istio_Dynamic_Test.verifier.main_verifier import run_verification
        
        # 从logs_info中获取logs_dir
        logs_dir = logs_info.get('logs_dir', str(project_root / "results" / "envoy_logs"))
        
        # 调用验证函数
        output_dir = str(self.output_dir / "verification")
        os.makedirs(output_dir, exist_ok=True)
        
        verification_result = run_verification(
            matrix_file=matrix_file,
            log_dir=logs_dir,
            output_dir=output_dir
        )
        
        return {
            'verification_result': verification_result,
            'verification_report': output_dir
        }
    
    def step8_consistency_analysis(self, system_ir, verification_result: Dict[str, Any]) -> Dict[str, Any]:
        """步骤8: 一致性分析和可视化"""
        from consistency_checker.core.orchestrator import Pipeline
        from consistency_checker.core.static_analyzer import StaticAnalyzer
        from consistency_checker.config import set_config, GlobalConfig
        
        # 确保配置目录路径正确（使用绝对路径）
        # 重新创建配置对象，确保project_root正确
        correct_config = GlobalConfig()
        # 设置正确的project_root
        correct_config.project_root = str(project_root)
        # 设置正确的配置目录（已经是绝对路径，但需要确保project_root正确以便后续解析）
        correct_config.control_plane_config_dir = str(project_root / "istio_config_parser" / "istio_monitor" / "istio_control_config")
        correct_config.data_plane_config_dir = str(project_root / "istio_config_parser" / "istio_monitor" / "istio_sidecar_config")
        correct_config.test_matrix_file = str(self.output_dir / "output_matrix.json")
        # 设置统一的结果目录路径（使用results/而不是istio_Dynamic_Test/results/）
        correct_config.envoy_logs_dir = str(project_root / "results" / "envoy_logs")
        correct_config.http_results_dir = str(project_root / "results" / "http_results")
        # 验证结果目录指向e2e验证生成的报告目录
        correct_config.verification_dir = str(self.output_dir / "verification")
        correct_config.namespace = self.namespace
        # 设置全局配置
        set_config(correct_config)
        
        # 使用Pipeline运行完整的一致性检查
        # Pipeline会使用全局配置，但我们需要确保它使用正确的路径
        pipeline = Pipeline(namespace=self.namespace)
        
        # 强制重新初始化static_analyzer使用正确的路径
        # 因为Pipeline可能在初始化时已经创建了static_analyzer
        pipeline.static_analyzer = StaticAnalyzer(
            config_dir=correct_config.control_plane_config_dir,
            namespace=self.namespace
        )
        
        report = pipeline.run_full_pipeline()
        
        # 保存报告
        report_file = self.output_dir / f"consistency_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # 将报告转换为字典格式保存
        # 处理timestamp（可能是datetime对象）
        timestamp = report.timestamp
        if hasattr(timestamp, 'isoformat'):
            timestamp = timestamp.isoformat()
        elif isinstance(timestamp, str):
            timestamp = timestamp
        else:
            timestamp = str(timestamp)
        
        report_dict = {
            'report_id': report.report_id,
            'timestamp': timestamp,
            'consistency_check': {
                'overall_status': report.consistency_check.overall_status.value if hasattr(report.consistency_check, 'overall_status') else 'unknown',
                'consistency_rate': report.consistency_check.consistency_rate if hasattr(report.consistency_check, 'consistency_rate') else 0,
                'total_policies': report.consistency_check.total_policies if hasattr(report.consistency_check, 'total_policies') else 0,
                'verified_policies': report.consistency_check.verified_policies if hasattr(report.consistency_check, 'verified_policies') else 0
            }
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)
        
        consistency_rate = report.consistency_check.consistency_rate if hasattr(report.consistency_check, 'consistency_rate') else 0
        
        return {
            'consistency_result': report_dict,
            'report_file': str(report_file),
            'consistency_rate': consistency_rate
        }
    
    def run_full_pipeline(self) -> E2EResult:
        """运行完整流程"""
        logger.info("=" * 80)
        logger.info("开始端到端验证流程")
        logger.info("=" * 80)
        
        start_time = time.time()
        self.results.total_duration = 0.0
        
        try:
            # 静态解析全流程
            logger.info("\n" + "=" * 80)
            logger.info("阶段1: 静态解析全流程")
            logger.info("=" * 80)
            
            static_start = time.time()
            
            # 步骤1: 获取配置
            step1_result = self.record_step(
                "1.1 监控器获取配置",
                self.step1_fetch_configs
            )
            
            if not step1_result.success:
                raise Exception(f"步骤1失败: {step1_result.error}")
            
            config_dirs = step1_result.outputs
            
            # 步骤2: 解析配置
            step2_result = self.record_step(
                "1.2 解析静态配置",
                self.step2_parse_configs,
                config_dirs
            )
            
            if not step2_result.success:
                raise Exception(f"步骤2失败: {step2_result.error}")
            
            system_ir = step2_result.outputs['system_ir']
            
            # 步骤3: 生成IR
            step3_result = self.record_step(
                "1.3 生成IR中间表示",
                self.step3_generate_ir,
                system_ir
            )
            
            if not step3_result.success:
                raise Exception(f"步骤3失败: {step3_result.error}")
            
            static_end = time.time()
            self.results.static_pipeline_duration = static_end - static_start
            
            logger.info(f"\n静态解析全流程耗时: {self.results.static_pipeline_duration:.3f}秒")
            
            # 动态验证全流程
            logger.info("\n" + "=" * 80)
            logger.info("阶段2: 动态验证全流程")
            logger.info("=" * 80)
            
            dynamic_start = time.time()
            
            # 步骤4: 生成正交测试用例
            step4_result = self.record_step(
                "2.1 生成正交测试策略",
                self.step4_generate_orthogonal_test_cases,
                step3_result.outputs
            )
            
            if not step4_result.success:
                raise Exception(f"步骤4失败: {step4_result.error}")
            
            matrix_file = step4_result.outputs['matrix_file']
            
            # 步骤5: 发送动态请求
            step5_result = self.record_step(
                "2.2 发送动态请求",
                self.step5_send_dynamic_requests,
                matrix_file
            )
            
            if not step5_result.success:
                logger.warning(f"步骤5失败: {step5_result.error}，继续执行后续步骤")
            
            # 步骤6: 收集日志
            # 传递步骤5的输出信息（包含results_dir和envoy_logs_dir）
            step5_outputs = step5_result.outputs if step5_result.success else {}
            step6_result = self.record_step(
                "2.3 收集日志数据",
                self.step6_collect_logs,
                step5_outputs
            )
            
            if not step6_result.success:
                logger.warning(f"步骤6失败: {step6_result.error}，继续执行后续步骤")
            
            # 步骤7: 动态验证
            step7_result = self.record_step(
                "2.4 动态验证",
                self.step7_dynamic_verification,
                matrix_file,
                step6_result.outputs
            )
            
            if not step7_result.success:
                logger.warning(f"步骤7失败: {step7_result.error}，继续执行后续步骤")
            
            dynamic_end = time.time()
            self.results.dynamic_pipeline_duration = dynamic_end - dynamic_start
            
            logger.info(f"\n动态验证全流程耗时: {self.results.dynamic_pipeline_duration:.3f}秒")
            
            # 步骤8: 一致性分析和可视化
            logger.info("\n" + "=" * 80)
            logger.info("阶段3: 一致性分析和可视化")
            logger.info("=" * 80)
            
            verification_result = step7_result.outputs.get('verification_result', {})
            step8_result = self.record_step(
                "3.1 一致性分析和可视化",
                self.step8_consistency_analysis,
                system_ir,
                verification_result
            )
            
            if not step8_result.success:
                logger.warning(f"步骤8失败: {step8_result.error}")
            
            self.results.success = all(step.success for step in self.results.steps)
            
        except Exception as e:
            logger.error(f"端到端验证流程失败: {str(e)}")
            logger.error(traceback.format_exc())
            self.results.success = False
        
        finally:
            end_time = time.time()
            self.results.total_duration = end_time - start_time
            
            # 保存结果
            self.save_results()
            
            # 打印摘要
            self.print_summary()
    
    def save_results(self):
        """保存结果"""
        result_file = self.output_dir / f"e2e_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(self.results.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n详细结果已保存到: {result_file}")
    
    def print_summary(self):
        """打印摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("端到端验证摘要")
        logger.info("=" * 80)
        
        logger.info(f"\n总执行时间: {self.results.total_duration:.3f}秒")
        logger.info(f"执行状态: {'成功' if self.results.success else '失败'}")
        
        logger.info(f"\n静态解析全流程: {self.results.static_pipeline_duration:.3f}秒")
        logger.info(f"动态验证全流程: {self.results.dynamic_pipeline_duration:.3f}秒")
        
        logger.info("\n各步骤耗时:")
        logger.info("-" * 80)
        
        for step in self.results.steps:
            status = "✓" if step.success else "✗"
            logger.info(f"{status} [{step.step_id}] {step.step_name}: {step.duration:.3f}秒")
            if not step.success and step.error:
                logger.info(f"    错误: {step.error}")
        
        logger.info("\n" + "=" * 80)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='MeshScope 端到端验证框架',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基本用法
  python e2e_validator.py --vm-host 192.168.92.131 --vm-user root --vm-password 12345678
  
  # 指定命名空间和ingress URL
  python e2e_validator.py --vm-host 192.168.92.131 --namespace default --ingress-url http://192.168.92.131:30476/productpage
  
  # 指定输出目录
  python e2e_validator.py --vm-host 192.168.92.131 --output-dir results/my_e2e_test
        """
    )
    
    parser.add_argument('--vm-host', type=str, default='192.168.92.131',
                       help='虚拟机主机IP地址')
    parser.add_argument('--vm-user', type=str, default='root',
                       help='SSH用户名')
    parser.add_argument('--vm-password', type=str, default='12345678',
                       help='SSH密码')
    parser.add_argument('--namespace', type=str, default='default',
                       help='Kubernetes命名空间')
    parser.add_argument('--ingress-url', type=str, default='',
                       help='Ingress URL (如: http://192.168.92.131:30476/productpage)')
    parser.add_argument('--output-dir', type=str, default='results/e2e_validation',
                       help='输出目录')
    
    args = parser.parse_args()
    
    # 构建配置
    config = {
        'vm_host': args.vm_host,
        'vm_user': args.vm_user,
        'vm_password': args.vm_password,
        'namespace': args.namespace,
        'ingress_url': args.ingress_url or f"http://{args.vm_host}:30476/productpage",
        'output_dir': args.output_dir
    }
    
    # 创建验证器并运行
    validator = E2EValidator(config)
    validator.run_full_pipeline()
    
    return validator.results


if __name__ == "__main__":
    main()

