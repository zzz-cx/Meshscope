#!/usr/bin/env python3
"""
端到端评估器
完整测试：配置解析 → 静态分析 → 流量测试 → 动态分析 → 一致性检查
"""

import os
import sys
import json
import time
import logging
import glob
import json
import io
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

# 导入配置解析器
from istio_config_parser.istio_monitor.istio_config_parser import IstioConfigParser
from istio_config_parser.istio_monitor.istio_sidecar_monitor import IstioSidecarMonitor
from istio_config_parser.main_parser import parse_control_plane_from_dir
from istio_config_parser.utils.file_utils import load_yaml_file

# 导入一致性检查器
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.models.data_models import (
    ConsistencyResult,
    InconsistencyAnnotation,
    SeverityLevel
)
from consistency_checker.config import get_config

# 导入流量测试模块
from istio_Dynamic_Test.internal.pipeline import DynamicTester
from istio_Dynamic_Test.internal.testcase.generators import TestCaseGenerator
from istio_Dynamic_Test.internal.models import TestSuite
from istio_Dynamic_Test.internal.validation import run_verification, analyze_single_case


class E2EEvaluator:
    """端到端评估器 - 测试完整的检测流程"""
    
    def __init__(self, config_file: str = None):
        """初始化评估器"""
        self.config = self._load_config(config_file)
        self.logger = self._setup_logging()
        self.results = {
            "start_time": datetime.now().isoformat(),
            "test_results": [],
            "pipeline_metrics": {},
            "summary": {}
        }
        
        # 初始化配置解析器和监控器（其他组件在需要时创建）
        self.config_parser = IstioConfigParser()
        self.monitor = None  # 监控器在需要时创建
        
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        if config_file and os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 从全局配置获取默认值
        global_config = get_config()
        default_fetch_output = os.path.join(project_root, "results", "monitoring")
        return {
            "ssh_host": os.getenv("SSH_HOST") or global_config.ssh_host,
            "ssh_user": os.getenv("SSH_USER") or global_config.ssh_user,
            "ssh_password": os.getenv("SSH_PASSWORD") or global_config.ssh_password,
            "k8s_host": os.getenv("K8S_HOST") or global_config.k8s_host or global_config.ssh_host,
            "k8s_token": os.getenv("K8S_TOKEN") or global_config.k8s_token or "",
            "default_namespace": global_config.namespace,
            "test_cases_dir": os.path.join(project_root, "evaluation", "e2e", "test_cases"),
            "output_dir": os.path.join(project_root, "evaluation", "e2e", "results"),
            "fetch_output_dir": default_fetch_output,
            "enable_traffic_test": True,
            "enable_dynamic_analysis": True
        }
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('e2e_evaluator')
        logger.setLevel(logging.INFO)
        
        # 文件处理器
        log_file = f"e2e_evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # 格式化器
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)
        
        return logger

    def _generate_test_matrix(self, test_case: Dict[str, Any], matrix_path: Path) -> Dict[str, Any]:
        """根据最新控制平面配置生成测试矩阵。"""
        traffic_config = test_case.get('traffic_config', {})
        generator_config = traffic_config.get('generator_config', {})
        fetch_result = test_case.get('_fetch_result', {})

        control_plane_dir = generator_config.get('control_plane_dir') or fetch_result.get('control_plane_dir')
        if control_plane_dir and not os.path.isabs(control_plane_dir):
            control_plane_dir = str((project_root / control_plane_dir).resolve())

        if not control_plane_dir or not os.path.exists(control_plane_dir):
            raise Exception("自动生成测试矩阵失败：未找到控制平面配置目录，请确认监控器已成功拉取配置。")

        service_deps_path = generator_config.get('service_deps')
        if service_deps_path:
            if not os.path.isabs(service_deps_path):
                service_deps_path = str((project_root / service_deps_path).resolve())
            if not os.path.exists(service_deps_path):
                self.logger.warning(f"  Service dependency 文件不存在: {service_deps_path}，将忽略依赖映射。")
                service_deps_path = None

        ingress_url = generator_config.get('ingress_url') or traffic_config.get('ingress_url')
        if not ingress_url:
            raise Exception("自动生成测试矩阵需要配置 ingress_url。")

        generator = TestCaseGenerator(control_plane_dir, service_deps_path)
        test_cases = generator.generate()
        if not test_cases:
            raise Exception("自动生成的测试矩阵为空，请检查集群配置是否包含可测试的策略。")

        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "global_settings": {
                "ingress_url": ingress_url
            },
            "test_cases": test_cases
        }

        with matrix_path.open('w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"  Generated latest test matrix at {matrix_path} (cases: {len(test_cases)})")
        return {
            "matrix_file": str(matrix_path),
            "case_count": len(test_cases)
        }
    
    def run_e2e_test(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Run complete end-to-end test"""
        test_id = test_case.get('test_id', 'unknown')
        self.logger.info(f"=" * 80)
        self.logger.info(f"Starting E2E Test: {test_id} - {test_case.get('name', 'Unnamed')}")
        self.logger.info(f"=" * 80)
        
        result = {
            "test_id": test_id,
            "name": test_case.get('name', ''),
            "start_time": datetime.now().isoformat(),
            "stages": {},
            "overall_success": False,
            "errors": []
        }
        
        start_time = time.time()
        
        try:
            # Stage 0: Fetch real configs from cluster (if enabled)
            if test_case.get('fetch_from_cluster'):
                self.logger.info(f"[Stage 0/5] Fetching Real Configurations")
                fetch_result = self._stage0_fetch_configs(test_case)
                result["stages"]["0_fetch"] = fetch_result
                # Save fetch_result for later stages
                test_case['_fetch_result'] = fetch_result
                
                if not fetch_result["success"]:
                    self.logger.warning(f"Config fetch failed: {fetch_result.get('error')}, using existing configs")
            
            # Stage 1: Configuration Parsing
            self.logger.info(f"[Stage 1/5] Configuration Parsing")
            parsing_result = self._stage1_parse_configs(test_case)
            result["stages"]["1_parsing"] = parsing_result
            
            if not parsing_result["success"]:
                raise Exception(f"Configuration parsing failed: {parsing_result.get('error')}")
            
            # Stage 2: Static Analysis
            self.logger.info(f"[Stage 2/5] Static Analysis")
            static_result = self._stage2_static_analysis(parsing_result)
            result["stages"]["2_static_analysis"] = static_result
            if static_result and not static_result.get("skipped"):
                self.logger.info(
                    f"  Static analysis time: {static_result.get('execution_time', 0):.2f}s"
                )
            
            # Stage 3: Traffic Testing (optional)
            traffic_result = None
            if test_case.get("enable_traffic_test") and test_case.get("traffic_config"):
                self.logger.info(f"[Stage 3/5] Traffic Testing")
                traffic_result = self._stage3_traffic_test(test_case)
                result["stages"]["3_traffic_test"] = traffic_result
            else:
                self.logger.info(f"[Stage 3/5] Traffic Testing - Skipped")
                result["stages"]["3_traffic_test"] = {"skipped": True}
            
            # Stage 4: Dynamic Analysis (optional)
            dynamic_result = None
            if test_case.get("enable_dynamic_analysis") and traffic_result and traffic_result.get("success"):
                self.logger.info(f"[Stage 4/5] Dynamic Analysis")
                dynamic_result = self._stage4_dynamic_analysis(test_case, traffic_result)
                result["stages"]["4_dynamic_analysis"] = dynamic_result
                if dynamic_result and not dynamic_result.get("skipped"):
                    self.logger.info(
                        f"  Dynamic analysis time: {dynamic_result.get('execution_time', 0):.2f}s"
                    )
            else:
                self.logger.info(f"[Stage 4/5] Dynamic Analysis - Skipped")
                result["stages"]["4_dynamic_analysis"] = {"skipped": True}
            
            # Stage 5: Consistency Check
            self.logger.info(f"[Stage 5/5] Consistency Check")
            consistency_result = self._stage5_consistency_check(
                static_result, 
                dynamic_result
            )
            result["stages"]["5_consistency_check"] = consistency_result

            # 统计阶段延迟
            stages_info = result["stages"]
            static_latency = 0.0
            for key in ("1_parsing", "2_static_analysis"):
                stage_info = stages_info.get(key, {})
                if stage_info and not stage_info.get("skipped"):
                    static_latency += stage_info.get("execution_time", 0.0)

            dynamic_latency = 0.0
            for key in ("3_traffic_test", "4_dynamic_analysis"):
                stage_info = stages_info.get(key, {})
                if stage_info and not stage_info.get("skipped"):
                    dynamic_latency += stage_info.get("execution_time", 0.0)

            result["static_latency"] = static_latency
            result["dynamic_latency"] = dynamic_latency
            self.logger.info(f"  Static latency (Stage 1+2): {static_latency:.2f}s")
            self.logger.info(f"  Dynamic latency (Stage 3+4): {dynamic_latency:.2f}s")
            
            # Validate results
            result["overall_success"] = self._validate_results(
                test_case, 
                static_result, 
                dynamic_result, 
                consistency_result
            )
            
        except Exception as e:
            self.logger.error(f"E2E test failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            result["errors"].append(str(e))
            result["overall_success"] = False
        
        finally:
            result["execution_time"] = time.time() - start_time
            result["end_time"] = datetime.now().isoformat()
            
            # Clean up temporary config directory if used
            try:
                if not test_case.get('use_structured_configs'):
                    temp_config_dir = os.path.join(project_root, "evaluation", "e2e", "temp_configs")
                    if os.path.exists(temp_config_dir):
                        import shutil
                        shutil.rmtree(temp_config_dir)
            except Exception as e:
                self.logger.warning(f"Failed to clean temp directory: {str(e)}")
        
        self.logger.info(f"E2E test completed: {test_id}, Result: {'SUCCESS' if result['overall_success'] else 'FAILED'}")
        self.logger.info(f"Total time: {result['execution_time']:.2f}s")
        
        return result
    
    def _stage0_fetch_configs(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 0: Fetch real configs from cluster"""
        stage_start = time.time()
        
        try:
            # Get cluster connection config
            cluster_config = test_case.get('cluster_config', {})
            vm_host = cluster_config.get('vm_host', self.config.get('ssh_host'))
            vm_user = cluster_config.get('vm_user', self.config.get('ssh_user', 'root'))
            vm_password = cluster_config.get('vm_password', self.config.get('ssh_password'))
            k8s_host = cluster_config.get('k8s_host', self.config.get('k8s_host'))
            k8s_token = cluster_config.get('k8s_token', self.config.get('k8s_token'))
            namespace = cluster_config.get('namespace', self.config.get('default_namespace', 'default'))
            fetch_output_dir = cluster_config.get('output_dir', self.config.get('fetch_output_dir'))
            if not fetch_output_dir:
                raise Exception("Fetch output directory 未配置")
            fetch_output_dir = os.path.abspath(fetch_output_dir)
            sidecar_output_dir = cluster_config.get(
                'sidecar_output_dir',
                os.path.join(fetch_output_dir, "sidecar")
            )
            
            if not vm_host:
                raise Exception("Cluster connection info (vm_host) not provided")
            
            self.logger.info(f"  Connecting to cluster: {vm_host}")
            self.logger.info(f"  Namespace: {namespace}")
            
            # Create config output directory
            sidecar_dir = os.path.abspath(sidecar_output_dir)
            os.makedirs(sidecar_dir, exist_ok=True)
            control_plane_dir = os.path.join(os.path.dirname(sidecar_dir), "istio_control_config")
            os.makedirs(control_plane_dir, exist_ok=True)
            config_output_dir = os.path.dirname(sidecar_dir)
            
            # 创建监控器
            self.monitor = IstioSidecarMonitor(
                interval=3600,  # 1小时（不会actual等待）
                output_dir=sidecar_dir,
                namespace=namespace,
                config_types=["routes", "clusters", "listeners"],
                use_vm=True,
                vm_host=vm_host,
                vm_port=22,
                vm_user=vm_user,
                vm_password=vm_password,
                k8s_host=k8s_host,
                k8s_token=k8s_token
            )
            
            # Fetch configs immediately
            self.logger.info(f"  Fetching Istio configurations...")
            changes = self.monitor.update_now()
            
            self.logger.info(f"  Config fetch completed:")
            self.logger.info(f"    - Control plane config dir: {control_plane_dir}")
            self.logger.info(f"    - Data plane config dir: {sidecar_dir}")
            self.logger.info(f"    - Config changes: {len(changes)}")
            
            # Check if configs were fetched successfully
            has_control_plane = os.path.exists(control_plane_dir) and os.path.isdir(control_plane_dir) and len(os.listdir(control_plane_dir)) > 0
            has_sidecar = os.path.exists(sidecar_dir) and os.path.isdir(sidecar_dir) and len(os.listdir(sidecar_dir)) > 0
            
            self.logger.info(f"  Config fetch result:")
            self.logger.info(f"    - Control plane: {'SUCCESS' if has_control_plane else 'FAILED (K8s token may be required)'}")
            self.logger.info(f"    - Data plane: {'SUCCESS' if has_sidecar else 'FAILED'}")
            
            # If data plane config available, record using sidecar dir to continue
            config_dir_to_use = control_plane_dir if has_control_plane else None
            
            return {
                "success": has_control_plane or has_sidecar,  # 至少一个SUCCESS就继续
                "control_plane_dir": control_plane_dir,
                "sidecar_dir": sidecar_dir,
                "config_output_dir": config_output_dir,
                "changes_count": len(changes),
                "has_control_plane": has_control_plane,
                "has_sidecar": has_sidecar,
                "config_dir_to_use": config_dir_to_use,
                "execution_time": time.time() - stage_start,
                "namespace": namespace,
                "vm_host": vm_host
            }
            
        except Exception as e:
            self.logger.error(f"  Config fetch from cluster failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start
            }
    
    def _stage1_parse_configs(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 1: Configuration Parsing"""
        stage_start = time.time()
        
        try:
            # Priority 1: Use already fetched config directory
            if test_case.get('use_fetched_configs'):
                fetched_configs_dir = test_case.get('fetched_configs_dir', 'evaluation/e2e/fetched_configs/istio_control_config')
                config_dir = os.path.join(project_root, fetched_configs_dir) if not os.path.isabs(fetched_configs_dir) else fetched_configs_dir
                
                if os.path.exists(config_dir):
                    self.logger.info(f"  Using fetched config directory: {config_dir}")
                    return {
                        "success": True,
                        "config_dir": config_dir,
                        "config_source": "fetched_configs",
                        "execution_time": time.time() - stage_start
                    }
                else:
                    self.logger.warning(f"  Config directory not found: {config_dir}")
                    raise Exception(f"Config directory not found: {config_dir}")
            
            # 优先2: 使用从集群获取的配置
            if test_case.get('fetch_from_cluster'):
                fetch_result = test_case.get('_fetch_result', {})
                
                if fetch_result.get('success'):
                    # Prefer control plane config
                    if fetch_result.get('has_control_plane'):
                        control_plane_dir = fetch_result.get('control_plane_dir')
                        if control_plane_dir and os.path.exists(control_plane_dir):
                            self.logger.info(f"  Using control plane config from cluster: {control_plane_dir}")
                            return {
                                "success": True,
                                "config_dir": control_plane_dir,
                                "config_source": "cluster_control_plane",
                                "execution_time": time.time() - stage_start
                            }
                    # If only data plane config available, try using it
                    if fetch_result.get('has_sidecar') and not fetch_result.get('has_control_plane'):
                        sidecar_dir = fetch_result.get('sidecar_dir')
                        self.logger.info(f"  Only data plane config fetched, skipping static analysis")
                        self.logger.info(f"  Data plane config directory: {sidecar_dir}")
                        return {
                            "success": True,
                            "config_dir": None,  # No control plane config
                            "sidecar_dir": sidecar_dir,
                            "config_source": "cluster_sidecar_only",
                            "skip_static_analysis": True,  # Mark skip static analysis
                            "execution_time": time.time() - stage_start
                        }
            
            # Check if using structured config directory
            if test_case.get('use_structured_configs'):
                config_source_dir = test_case.get('config_source_dir', 'configs_with_structure')
                source_dir = os.path.join(project_root, "evaluation", "e2e", config_source_dir)
                
                if os.path.exists(source_dir):
                    self.logger.info(f"  Using structured config directory: {config_source_dir}")
                    # Use source directory directly, no copy needed
                    return {
                        "success": True,
                        "config_dir": source_dir,
                        "config_source": "local",
                        "config_count": -1,  # Indicates using directory
                        "execution_time": time.time() - stage_start
                    }
                else:
                    raise Exception(f"Structured config directory not found: {source_dir}")
            
            # Original logic: process individual config files
            config_files = test_case.get('config_files', [])
            
            # Ensure config directory exists
            configs_dir = os.path.join(project_root, "evaluation", "e2e", "configs")
            if not os.path.exists(configs_dir):
                os.makedirs(configs_dir, exist_ok=True)
            
            # Copy config files to temp directory (StaticAnalyzer needs directory path)
            temp_config_dir = os.path.join(project_root, "evaluation", "e2e", "temp_configs")
            if os.path.exists(temp_config_dir):
                import shutil
                shutil.rmtree(temp_config_dir)
            os.makedirs(temp_config_dir, exist_ok=True)
            
            parsed_count = 0
            for config_file in config_files:
                config_path = os.path.join(configs_dir, config_file)
                
                if os.path.exists(config_path):
                    self.logger.info(f"  Copying config file: {config_file}")
                    import shutil
                    dest_path = os.path.join(temp_config_dir, config_file)
                    shutil.copy(config_path, dest_path)
                    parsed_count += 1
                else:
                    self.logger.warning(f"  Config file not found: {config_path}")
            
            return {
                "success": parsed_count > 0,
                "config_dir": temp_config_dir,
                "config_count": parsed_count,
                "execution_time": time.time() - stage_start
            }
            
        except Exception as e:
            self.logger.error(f"  Config parsing failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start
            }
    
    def _stage2_static_analysis(self, parsing_result: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 2: Static Analysis"""
        stage_start = time.time()
        
        try:
            if parsing_result.get("skip_static_analysis"):
                self.logger.info("  Static analysis skipped (no control plane configs available)")
                return {
                    "success": True,
                    "skipped": True,
                    "execution_time": time.time() - stage_start
                }

            config_dir = parsing_result.get('config_dir')
            if not config_dir:
                raise Exception("config directory路径缺失")
            
            self.logger.info(f"  Running static analyzer... (config directory: {config_dir})")
            static_analyzer = StaticAnalyzer(config_dir=config_dir)
            analysis_result = static_analyzer.analyze()
            
            # analyze() 返回字典
            inconsistencies = analysis_result.get('plane_consistency_issues', [])
            has_issues = len(inconsistencies) > 0
            summary = analysis_result.get('summary', {})
            static_policies = analysis_result.get('static_policies', [])
            service_nodes = analysis_result.get('service_nodes', [])
            
            self.logger.info(f"  Static analysis completed:")
            self.logger.info(f"    - Services: {summary.get('total_services', 0)}")
            self.logger.info(f"    - Policies: {summary.get('total_policies', 0)}")
            self.logger.info(f"    - Issues: {len(inconsistencies)}")
            
            return {
                "success": True,
                "has_issues": has_issues,
                "inconsistencies_count": len(inconsistencies),
                "inconsistencies": inconsistencies,
                "summary": summary,
                "static_policy_count": len(static_policies),
                "service_node_count": len(service_nodes),
                "execution_time": time.time() - stage_start
            }
            
        except Exception as e:
            self.logger.error(f"  Static analysis failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start
            }
    
    def _stage3_traffic_test(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 3: Traffic Testing"""
        stage_start = time.time()
        timing_breakdown = {}
        
        try:
            traffic_config = test_case.get('traffic_config', {})
            if not traffic_config:
                raise Exception("traffic_config 未配置，无法执行流量测试")
            
            matrix_file = traffic_config.get('matrix_file')
            if not matrix_file:
                raise Exception("traffic_config.matrix_file 未指定")
            
            matrix_path = Path(matrix_file)
            if not matrix_path.is_absolute():
                matrix_path = (project_root / matrix_path).resolve()
            else:
                matrix_path = matrix_path.resolve()

            timing_start = time.time()
            if traffic_config.get('auto_generate_matrix'):
                self.logger.info("  Auto-generating test matrix based on latest control plane configs...")
                self._generate_test_matrix(test_case, matrix_path)
            timing_breakdown['matrix_generation'] = time.time() - timing_start

            if not matrix_path.exists():
                raise Exception(f"测试矩阵文件不存在: {matrix_path}")
            
            cluster_config = test_case.get('cluster_config', {})
            ssh_config = traffic_config.get('ssh_config')
            if not ssh_config:
                vm_host = cluster_config.get('vm_host', self.config.get('ssh_host'))
                vm_user = cluster_config.get('vm_user', self.config.get('ssh_user', 'root'))
                vm_password = cluster_config.get('vm_password', self.config.get('ssh_password'))
                vm_port = cluster_config.get('vm_port', 22)
                vm_key_file = cluster_config.get('vm_key_file')
                if vm_host:
                    ssh_config = {
                        'hostname': vm_host,
                        'username': vm_user,
                        'password': vm_password,
                        'key_filename': vm_key_file,
                        'port': vm_port
                    }
            
            namespace = traffic_config.get(
                'namespace',
                cluster_config.get('namespace', self.config.get('default_namespace', 'default'))
            )
            
            if sys.platform == 'win32':
                try:
                    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
                except (AttributeError, ValueError):
                    try:
                        import io
                        if hasattr(sys.stdout, 'buffer'):
                            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
                        if hasattr(sys.stderr, 'buffer'):
                            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
                    except Exception:
                        pass
            
            timing_start = time.time()
            self.logger.info(f"  Running traffic driver with matrix: {matrix_path}")
            suite = TestSuite.from_matrix_file(str(matrix_path))
            tester = DynamicTester(ssh_config=ssh_config, namespace=namespace)
            timing_breakdown['driver_init'] = time.time() - timing_start
            
            timing_start = time.time()
            single_case = traffic_config.get('single_case')
            if single_case:
                tc = next((c for c in suite.cases if c.case_id == single_case), None)
                if not tc:
                    raise ValueError(f"未找到用例: {single_case}")
                pipeline_results = [tester.run_single(tc)]
            else:
                pipeline_results = tester.run(suite)
            timing_breakdown['traffic_execution'] = time.time() - timing_start
            
            case_ids = [pr.test_case.case_id for pr in pipeline_results]
            http_summary = {}
            for pr in pipeline_results:
                if not pr.execution:
                    continue
                case_id = pr.test_case.case_id
                metrics = {
                    'status_codes': pr.execution.status_codes,
                    'total_requests': pr.execution.total_requests,
                    'success_rate': pr.execution.success_rate,
                    'avg_response_time': pr.execution.avg_response_time,
                    'error_count': pr.execution.error_count,
                }
                http_summary[case_id] = {
                    'status_codes': metrics.get('status_codes', {}),
                    'total_requests': metrics.get('total_requests', 0),
                    'success_rate': metrics.get('success_rate', 0),
                    'avg_response_time': metrics.get('avg_response_time', 0),
                    'error_count': metrics.get('error_count', 0)
                }
            
            log_dir = traffic_config.get('log_dir', os.path.join(project_root, 'results', 'envoy_logs'))
            log_dir = os.path.abspath(log_dir)
            http_results_dir = traffic_config.get('http_results_dir', os.path.join(project_root, 'results', 'http_results'))
            http_results_dir = os.path.abspath(http_results_dir)
            
            total_time = time.time() - stage_start
            timing_breakdown['total'] = total_time
            
            # 记录详细计时信息
            self.logger.info(f"  Stage 3 timing breakdown:")
            for key, value in timing_breakdown.items():
                if key != 'total':
                    self.logger.info(f"    - {key}: {value:.2f}s")
            
            return {
                "success": True,
                "matrix_file": str(matrix_path),
                "namespace": namespace,
                "case_count": len(case_ids),
                "case_ids": case_ids,
                "http_summary": http_summary,
                "log_dir": log_dir,
                "http_results_dir": http_results_dir,
                "execution_time": total_time,
                "timing_breakdown": timing_breakdown
            }
            
        except Exception as e:
            self.logger.error(f"  Traffic test failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start,
                "timing_breakdown": timing_breakdown
            }
    
    def _stage4_dynamic_analysis(self, test_case: Dict[str, Any], traffic_result: Dict[str, Any]) -> Dict[str, Any]:
        """Stage 4: Dynamic Analysis"""
        stage_start = time.time()
        
        try:
            if not traffic_result or not traffic_result.get("success"):
                self.logger.warning("  Skipping dynamic analysis because traffic stage did not succeed")
                return {
                    "success": False,
                    "skipped": True,
                    "execution_time": time.time() - stage_start
                }
            
            traffic_config = test_case.get('traffic_config', {})
            matrix_file = traffic_result.get('matrix_file')
            log_dir = traffic_result.get('log_dir')
            http_results_dir = traffic_result.get('http_results_dir')
            
            if not log_dir or not os.path.exists(log_dir):
                raise Exception(f"日志目录不存在: {log_dir}")
            
            verification_output_dir = traffic_config.get(
                'verification_output_dir',
                os.path.join(project_root, 'results', 'verification')
            )
            verification_output_dir = os.path.abspath(verification_output_dir)
            os.makedirs(verification_output_dir, exist_ok=True)
            
            istio_config_file = traffic_config.get('istio_config_file')
            if istio_config_file:
                istio_config_path = Path(istio_config_file)
                if not istio_config_path.is_absolute():
                    istio_config_path = (project_root / istio_config_path).resolve()
                istio_config_file = str(istio_config_path)
                if not os.path.exists(istio_config_file):
                    raise Exception(f"Istio配置文件不存在: {istio_config_file}")
            else:
                istio_config_file = None
            
            self.logger.info("  Running dynamic verification (log + HTTP analysis)")
            run_verification(
                matrix_file,
                log_dir,
                output_dir=verification_output_dir,
                istio_config_file=istio_config_file
            )
            
            latest_report_json = self._find_latest_file(
                verification_output_dir,
                prefix="istio_verification_",
                suffix=".json"
            )
            
            summary = {}
            has_anomalies = False
            failed_count = 0
            warning_count = 0
            total_count = 0
            
            if latest_report_json and os.path.exists(latest_report_json):
                with open(latest_report_json, 'r', encoding='utf-8') as f:
                    report_data = json.load(f)
                verification_steps = report_data.get("metadata", {}).get("test_config", {}).get("verification_process", {}).get("steps", [])
                summary = {
                    "report_file": latest_report_json,
                    "verification_output_dir": verification_output_dir
                }
                for step in verification_steps:
                    if step.get("step") == 3:
                        verification_summary = step.get("verification_summary", [])
                        total_count = len(verification_summary)
                        for case_result in verification_summary:
                            status = case_result.get("overall_status", "").lower()
                            if status == "failed":
                                failed_count += 1
                            elif status == "warning":
                                warning_count += 1
                        break
                summary["total_cases"] = total_count
                summary["failed_count"] = failed_count
                summary["warning_count"] = warning_count
                has_anomalies = failed_count > 0
            else:
                self.logger.warning("  未找到动态验证报告，无法汇总详细信息")
            
            return {
                "success": True,
                "has_anomalies": has_anomalies,
                "summary": summary,
                "http_results_dir": http_results_dir,
                "verification_output_dir": verification_output_dir,
                "execution_time": time.time() - stage_start
            }
            
        except Exception as e:
            self.logger.error(f"  Dynamic analysis failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start
            }
    
    def _stage5_consistency_check(self, 
                                   static_result: Dict[str, Any], 
                                   dynamic_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Stage 5: Consistency Check"""
        stage_start = time.time()
        
        try:
            self.logger.info(f"  Running consistency check...")
            
            # 整合静态和动态结果
            has_static_issues = static_result.get("has_issues", False)
            has_dynamic_anomalies = dynamic_result.get("has_anomalies", False) if dynamic_result else False
            
            # 检查一致性
            consistent = True
            consistency_issues = []
            
            # 示例一致性规则：如果静态分析Found权重配置问题，动态分析应该检测到流量分布异常
            if has_static_issues:
                static_types = [inc["type"] for inc in static_result.get("inconsistencies", [])]
                if "WEIGHT_MISMATCH" in static_types:
                    if not has_dynamic_anomalies:
                        consistent = False
                        consistency_issues.append("Static detected weight mismatch, but dynamic did not detect traffic anomaly")
            
            status_text = "[OK] Consistent" if consistent else "[FAIL] Inconsistent"
            self.logger.info(f"  Consistency check completed: {status_text}")
            
            return {
                "success": True,
                "consistent": consistent,
                "has_static_issues": has_static_issues,
                "has_dynamic_anomalies": has_dynamic_anomalies,
                "consistency_issues": consistency_issues,
                "execution_time": time.time() - stage_start
            }
            
        except Exception as e:
            self.logger.error(f"  Consistency check failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "execution_time": time.time() - stage_start
            }
    
    def _extract_traffic_metrics(self, traffic_result: Dict[str, Any]) -> Dict[str, Any]:
        """从流量测试结果中提取指标"""
        test_results = traffic_result.get("test_results", {})
        
        # 聚合所有测试结果
        total_requests = 0
        successful_requests = 0
        failed_requests = 0
        response_times = []
        status_codes = {}
        
        for test_id, result in test_results.items():
            total_requests += result.get("total_requests", 0)
            successful_requests += result.get("successful_requests", 0)
            failed_requests += result.get("failed_requests", 0)
            response_times.extend(result.get("response_times", []))
            
            # 聚合状态码
            for code, count in result.get("status_code_distribution", {}).items():
                status_codes[code] = status_codes.get(code, 0) + count
        
        return {
            "request_count": total_requests,
            "success_count": successful_requests,
            "failure_count": failed_requests,
            "response_times": response_times,
            "status_codes": status_codes,
            "error_messages": []
        }
    
    def _validate_results(self, 
                         test_case: Dict[str, Any],
                         static_result: Dict[str, Any],
                         dynamic_result: Optional[Dict[str, Any]],
                         consistency_result: Dict[str, Any]) -> bool:
        """验证结果是否符合expected"""
        expected = test_case.get('expected_results', {})
        
        # 验证静态分析结果
        expected_static_issues = expected.get('has_static_issues', None)
        if expected_static_issues is not None:
            if static_result.get('has_issues') != expected_static_issues:
                self.logger.warning(f"  Static analysis result does not match expectation: expected={expected_static_issues}, actual={static_result.get('has_issues')}")
                return False
        
        # 验证动态分析结果
        if dynamic_result and not dynamic_result.get("skipped"):
            expected_dynamic_anomalies = expected.get('has_dynamic_anomalies', None)
            if expected_dynamic_anomalies is not None:
                if dynamic_result.get('has_anomalies') != expected_dynamic_anomalies:
                    self.logger.warning(f"  动态分析结果不符合expected: expected={expected_dynamic_anomalies}, actual={dynamic_result.get('has_anomalies')}")
                    return False
        
        # 验证一致性
        expected_consistent = expected.get('consistent', True)
        if consistency_result.get('consistent') != expected_consistent:
            self.logger.warning(f"  一致性结果不符合expected: expected={expected_consistent}, actual={consistency_result.get('consistent')}")
            return False
        
        return True
    
    def run_evaluation(self) -> str:
        """运行完整的端到端评估"""
        self.logger.info("Starting E2E evaluation")
        
        # 加载测试用例
        test_cases_file = os.path.join(
            self.config["test_cases_dir"], 
            "e2e_test_cases.json"
        )
        
        if not os.path.exists(test_cases_file):
            self.logger.error(f"Test case file not found: {test_cases_file}")
            return None
        
        with open(test_cases_file, 'r', encoding='utf-8') as f:
            test_suite = json.load(f)
        
        test_cases = test_suite.get('test_cases', [])
        self.logger.info(f"Loaded {len(test_cases)} test cases")
        
        # 运行所有测试用例
        for test_case in test_cases:
            result = self.run_e2e_test(test_case)
            self.results["test_results"].append(result)
        
        # 计算统计指标
        self._calculate_metrics()
        
        # 生成报告
        report_file = self._generate_report()
        
        self.logger.info("E2E evaluation completed")
        return report_file
    
    def _calculate_metrics(self):
        """计算评估指标"""
        total_tests = len(self.results["test_results"])
        successful_tests = sum(1 for r in self.results["test_results"] if r.get("overall_success"))
        
        total_time = sum(r.get("execution_time", 0) for r in self.results["test_results"])
        total_static_latency = sum(r.get("static_latency", 0.0) for r in self.results["test_results"])
        total_dynamic_latency = sum(r.get("dynamic_latency", 0.0) for r in self.results["test_results"])

        static_counts = sum(
            1 for r in self.results["test_results"]
            if any(
                r.get("stages", {}).get(stage_key, {}).get("skipped") is not True
                for stage_key in ("1_parsing", "2_static_analysis")
            )
        )
        dynamic_counts = sum(
            1 for r in self.results["test_results"]
            if any(
                r.get("stages", {}).get(stage_key, {}).get("skipped") is not True
                for stage_key in ("3_traffic_test", "4_dynamic_analysis")
            )
        )
        
        self.results["pipeline_metrics"] = {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "failed_tests": total_tests - successful_tests,
            "success_rate": successful_tests / total_tests if total_tests > 0 else 0,
            "total_execution_time": total_time,
            "average_test_time": total_tests and (total_time / total_tests) or 0,
            "total_static_latency": total_static_latency,
            "average_static_latency": static_counts and (total_static_latency / static_counts) or 0,
            "total_dynamic_latency": total_dynamic_latency,
            "average_dynamic_latency": dynamic_counts and (total_dynamic_latency / dynamic_counts) or 0
        }
        
        self.results["summary"] = {
            "evaluation_completed": True,
            "end_time": datetime.now().isoformat(),
            "overall_success": successful_tests == total_tests
        }

    def _find_latest_file(self, directory: str, prefix: str, suffix: str) -> Optional[str]:
        """查找指定目录下最新的文件"""
        if not os.path.exists(directory):
            return None
        pattern = os.path.join(directory, f"{prefix}*{suffix}")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)
    
    def _generate_report(self) -> str:
        """生成评估报告"""
        os.makedirs(self.config["output_dir"], exist_ok=True)
        
        report_file = os.path.join(
            self.config["output_dir"],
            f"e2e_evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Evaluation report generated: {report_file}")
        return report_file


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="端到端评估")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--output", help="输出目录", default="results/e2e")
    
    args = parser.parse_args()
    
    evaluator = E2EEvaluator(args.config)
    report_file = evaluator.run_evaluation()
    
    if report_file:
        print(f"[SUCCESS] E2E evaluation completed！")
        print(f"[REPORT] 报告文件: {report_file}")
    else:
        print(f"[FAILED] 端到端评估FAILED！")


if __name__ == "__main__":
    main()

