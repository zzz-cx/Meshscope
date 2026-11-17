"""
全局流程编排器

负责协调静态分析、动态测试、一致性检查和可视化报告的完整流程
"""

import os
import json
import logging
from typing import Dict, Optional, Any
from datetime import datetime
from dataclasses import asdict, is_dataclass

from consistency_checker.config import get_config
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.visualizer.report_generator import ComprehensiveReportGenerator
from consistency_checker.visualizer.graph_generator import GraphGenerator
try:
    from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator  # type: ignore
    _THREE_LAYER_AVAILABLE = True
except Exception:  # pragma: no cover
    ThreeLayerGraphGenerator = None  # type: ignore
    _THREE_LAYER_AVAILABLE = False
from consistency_checker.models.data_models import VerificationReport
from consistency_checker.storage import get_store

logger = logging.getLogger(__name__)

# 尝试导入监控器
try:
    from istio_config_parser.istio_monitor.istio_sidecar_monitor import IstioSidecarMonitor
    MONITOR_AVAILABLE = True
except ImportError:
    MONITOR_AVAILABLE = False
    logger.warning("监控器模块不可用，将跳过配置获取步骤")


class Pipeline:
    """端到端一致性验证流水线"""
    
    def __init__(
        self,
        namespace: Optional[str] = None,
        safety=None,
        execute_dynamic: bool = False,
    ):
        """
        初始化流水线
        
        Args:
            namespace: Kubernetes命名空间
            safety: 动态验证安全开关（高压 / 故障注入 / rollout）
            execute_dynamic: 是否真正打入探测流量。完整流水线为 True；
                仅一致性判定时读已有结果。
        """
        self.config = get_config()
        self.namespace = namespace or self.config.namespace
        self.execute_dynamic = execute_dynamic
        try:
            from istio_Dynamic_Test.internal.pipeline.guards import options_from_config
            self.safety = safety or options_from_config()
        except Exception:
            self.safety = safety
        
        # 各模块实例
        self.static_analyzer: Optional[StaticAnalyzer] = None
        self.dynamic_analyzer: Optional[DynamicAnalyzer] = None
        self.consistency_checker: Optional[ConsistencyChecker] = None
        
        # 结果数据
        self.static_result = None
        self.dynamic_result = None
        self.consistency_result = None
        self.final_report: Optional[VerificationReport] = None
        
    def run_full_pipeline(self) -> VerificationReport:
        """
        运行完整的一致性验证流水线
        
        Returns:
            综合验证报告
        """
        logger.info("=" * 80)
        logger.info("开始Istio一致性验证流水线")
        logger.info("=" * 80)
        
        # 第零阶段：获取配置（如果监控器可用）
        if MONITOR_AVAILABLE:
            logger.info("\n🔧 第零阶段：从集群获取配置")
            logger.info("-" * 80)
            self._fetch_configs_from_cluster()
        
        # 第一阶段：静态分析
        logger.info("\n📋 第一阶段：静态配置分析")
        logger.info("-" * 80)
        self.static_result = self._run_static_analysis()
        
        # 第二阶段：动态分析（先打入探测流量，再读结果）
        logger.info("\n🔄 第二阶段：动态测试分析")
        logger.info("-" * 80)
        self.dynamic_result = self._run_dynamic_analysis(execute=True)
        
        # 第三阶段：一致性检查
        logger.info("\n✅ 第三阶段：一致性检查")
        logger.info("-" * 80)
        self.consistency_result = self._run_consistency_check()
        
        # 第四阶段：生成报告和可视化
        logger.info("\n📊 第四阶段：生成报告和可视化")
        logger.info("-" * 80)
        self.final_report = self._generate_reports()
        
        logger.info("\n" + "=" * 80)
        logger.info("流水线执行完成")
        logger.info(f"报告ID: {self.final_report.report_id}")
        logger.info(f"一致性状态: {self.consistency_result.overall_status.value}")
        logger.info(f"一致性率: {self.consistency_result.consistency_rate:.2%}")
        logger.info("=" * 80)
        
        return self.final_report
    
    def run_static_only(self) -> Dict[str, Any]:
        """仅运行静态分析"""
        logger.info("运行静态分析模式")
        self.static_result = self._run_static_analysis()
        return self.static_result
    
    def run_consistency_check_only(self) -> VerificationReport:
        """
        仅运行一致性检查（假设已有静态和动态分析结果）
        """
        logger.info("运行一致性检查模式")
        
        if not self.static_result:
            logger.info("加载静态分析结果...")
            self.static_result = self._run_static_analysis()
        
        if not self.dynamic_result:
            logger.info("加载动态分析结果...")
            self.dynamic_result = self._run_dynamic_analysis()
        
        self.consistency_result = self._run_consistency_check()
        self.final_report = self._generate_reports()
        
        return self.final_report
    
    def _fetch_configs_from_cluster(self) -> bool:
        """
        从Kubernetes集群获取配置
        
        Returns:
            是否成功获取配置
        """
        if not MONITOR_AVAILABLE:
            logger.warning("监控器不可用，跳过配置获取")
            return False
        
        try:
            # 准备输出目录
            control_plane_dir = self.config.control_plane_config_dir
            data_plane_dir = self.config.data_plane_config_dir
            
            # 确保目录存在
            os.makedirs(control_plane_dir, exist_ok=True)
            os.makedirs(data_plane_dir, exist_ok=True)
            
            # 检查是否已有配置
            has_existing_config = False
            if os.path.exists(control_plane_dir):
                # 检查是否有配置文件
                for root, dirs, files in os.walk(control_plane_dir):
                    if files:
                        has_existing_config = True
                        break
            
            if has_existing_config:
                logger.info("发现现有配置目录，仍从集群刷新，避免使用过期快照")
                logger.info(f"    配置目录: {control_plane_dir}")
            
            # 创建监控器
            # 注意：监控器会自动在output_dir的父目录创建control_plane_dir
            # 我们需要确保它使用正确的路径
            monitor = IstioSidecarMonitor(
                interval=3600,  # 不实际等待，只获取一次
                output_dir=data_plane_dir,  # 数据平面目录
                namespace=self.namespace,
                config_types=["routes", "clusters", "listeners"],
                use_vm=True,
                vm_host=self.config.ssh_host,
                vm_port=22,
                vm_user=self.config.ssh_user,
                vm_password=self.config.ssh_password,
                k8s_host=self.config.k8s_host,
                k8s_token=self.config.k8s_token
            )
            
            # 手动设置控制平面目录（如果监控器支持）
            if hasattr(monitor, 'control_plane_dir'):
                monitor.control_plane_dir = control_plane_dir
            
            # 立即获取配置
            logger.info("正在从集群获取配置...")
            changes = monitor.update_now()
            
            # 检查是否成功获取
            has_control_plane = os.path.exists(control_plane_dir) and os.path.isdir(control_plane_dir)
            has_data_plane = os.path.exists(data_plane_dir) and os.path.isdir(data_plane_dir)
            
            if has_control_plane or has_data_plane:
                logger.info(f"  ✓ 配置获取完成")
                logger.info(f"    - 控制平面配置: {'成功' if has_control_plane else '失败（可能需要K8s token）'}")
                logger.info(f"    - 数据平面配置: {'成功' if has_data_plane else '失败'}")
                logger.info(f"    - 配置变更数: {len(changes)}")
                return True
            else:
                logger.warning("  ⚠ 配置获取失败，将使用现有配置目录")
                logger.warning("    提示：如果配置目录为空，请确保:")
                logger.warning("    1. SSH连接配置正确（vm_host, vm_user, vm_password）")
                logger.warning("    2. Kubernetes token已配置（k8s_token）")
                logger.warning("    3. 或者手动将配置文件放入配置目录")
                return False
                
        except Exception as e:
            logger.error(f"配置获取失败: {str(e)}", exc_info=True)
            logger.warning("将使用现有配置目录继续执行")
            return False
    
    def _run_static_analysis(self) -> Dict[str, Any]:
        """运行静态分析"""
        self.static_analyzer = StaticAnalyzer(
            config_dir=None,  # 使用配置中的默认路径
            namespace=self.namespace
        )
        
        result = self.static_analyzer.analyze()
        self._save_intermediate_result("static_analysis", result)
        artifact = result.get("artifact")
        if artifact:
            try:
                get_store(self.config.database_path).save_artifact(
                    "aligned_semantic", self._make_serializable(artifact)
                )
            except Exception as exc:
                logger.warning("写入对齐产物到 SQLite 失败: %s", exc)
        
        logger.info(f"  ✓ 静态策略数量: {len(result['static_policies'])}")
        logger.info(f"  ✓ 服务节点数量: {len(result['service_nodes'])}")
        logger.info(f"  ✓ 配置边数量: {len(result['config_edges'])}")
        logger.info(f"  ✓ 平面一致性问题: {len(result['plane_consistency_issues'])}")
        
        return result
    
    def _run_dynamic_analysis(self, execute: Optional[bool] = None) -> Dict[str, Any]:
        """运行动态分析。完整流水线会先按安全开关打入探测流量。"""
        do_execute = self.execute_dynamic if execute is None else execute
        if do_execute:
            self._execute_dynamic_tests()

        self.dynamic_analyzer = DynamicAnalyzer(
            test_matrix_file=self.config.test_matrix_file,
            verification_dir=self.config.verification_dir,
            http_results_dir=self.config.http_results_dir
        )
        
        result = self.dynamic_analyzer.analyze()
        
        # 保存结果
        self._save_intermediate_result("dynamic_analysis", result)
        
        logger.info(f"  ✓ 测试用例数量: {len(result['dynamic_behaviors'])}")
        logger.info(f"  ✓ 验证通过: {result['summary']['verified_tests']}")
        logger.info(f"  ✓ 验证失败: {result['summary']['failed_tests']}")
        logger.info(f"  ✓ 验证率: {result['statistics']['verification_rate']:.2%}")
        
        return result

    def _execute_dynamic_tests(self) -> None:
        """从对齐模型生成矩阵并打入探测流量。"""
        from istio_Dynamic_Test.internal.pipeline.guards import banner_text, options_from_config, warning_lines
        from istio_Dynamic_Test.internal.pipeline.runner import run_aligned_dynamic_tests

        options = self.safety or options_from_config()
        self.safety = options
        logger.info("动态验证开关:\n%s", banner_text(options))
        for line in warning_lines(options):
            logger.warning(line)
        try:
            results = run_aligned_dynamic_tests(
                namespace=self.namespace,
                options=options,
            )
            skipped = sum(
                1 for r in results
                if r.validation and r.validation.overall_status.value == "skipped"
            )
            logger.info("  ✓ 动态打流完成: %s 条结果，跳过 %s 条", len(results), skipped)
        except Exception as exc:
            logger.error("动态打流失败，将继续用已有结果做分析: %s", exc, exc_info=True)
    
    def _run_consistency_check(self) -> Any:
        """运行一致性检查"""
        if not self.static_result or not self.dynamic_result:
            raise RuntimeError("必须先运行静态分析和动态分析")
        
        self.consistency_checker = ConsistencyChecker(
            static_policies=self.static_result['static_policies'],
            dynamic_behaviors=self.dynamic_result['dynamic_behaviors'],
            tolerance=self.config.traffic_split_tolerance,
            artifact=self.static_result.get("artifact") or {},
        )
        
        result = self.consistency_checker.check()
        
        # 保存结果
        self._save_intermediate_result("consistency_check", {
            "overall_status": result.overall_status.value,
            "consistency_rate": result.consistency_rate,
            "total_policies": result.total_policies,
            "verified_policies": result.verified_policies,
            "inconsistencies": [inc.to_record() for inc in result.inconsistencies],
            "summary": result.summary
        })
        
        logger.info(f"  ✓ 总策略数: {result.total_policies}")
        logger.info(f"  ✓ 已验证策略: {result.verified_policies}")
        logger.info(f"  ✓ 一致性率: {result.consistency_rate:.2%}")
        logger.info(f"  ✓ 不一致性问题: {len(result.inconsistencies)}")
        
        return result
    
    def _generate_reports(self) -> VerificationReport:
        """生成综合报告和可视化"""
        
        # 1. 构建图数据
        logger.info("  🔹 构建服务拓扑图...")
        graph_generator = GraphGenerator(
            service_nodes=self.static_result['service_nodes'],
            config_edges=self.static_result['config_edges'],
            consistency_result=self.consistency_result
        )
        graph_generator.generate()
        
        # 2. 生成综合报告
        logger.info("  🔹 生成综合报告...")
        report_generator = ComprehensiveReportGenerator(
            static_result=self.static_result,
            dynamic_result=self.dynamic_result,
            consistency_result=self.consistency_result,
            namespace=self.namespace
        )
        
        report = report_generator.generate()
        
        # 3. 输出报告文件
        self._save_final_report(report)
        
        # 4. 生成可视化图谱
        logger.info("  🔹 生成交互式图谱...")
        graph_generator.save_to_file(
            os.path.join(self.config.visualization_output_dir, f"{report.report_id}_graph.json")
        )

        # 4b. 生成三层空间配置依赖图（若模块存在）
        three_layer_payload = None
        if _THREE_LAYER_AVAILABLE and ThreeLayerGraphGenerator is not None:
            logger.info("  🔹 生成三层空间配置依赖图...")
            three_layer_gen = ThreeLayerGraphGenerator.from_static_result(
                self.static_result,
                consistency_result=self.consistency_result,
                namespace=self.namespace,
            )
            three_layer_gen.generate()
            three_layer_payload = three_layer_gen.to_d3_json()
            three_layer_gen.save_to_file(
                os.path.join(self.config.visualization_output_dir, f"{report.report_id}_three_layer_graph.json")
            )
        else:
            logger.info("  ⚠ 跳过三层空间图生成（three_layer_graph_generator 不可用）")
        
        # 5. 生成HTML报告
        logger.info("  🔹 生成HTML报告...")
        html_path = os.path.join(
            self.config.visualization_output_dir,
            f"{report.report_id}_report.html"
        )
        report_generator.generate_html_report(html_path, graph_generator.get_graph_data())

        store = get_store(self.config.database_path)
        store.save_report(report.to_dict(), html_path=html_path)
        store.save_graph(report.report_id, "topology", graph_generator.get_graph_data())
        if three_layer_payload is not None:
            store.save_graph(report.report_id, "three_layer", three_layer_payload)
            store.save_graph("latest", "three_layer", three_layer_payload)
        
        logger.info(f"  ✓ 报告已保存")
        logger.info(f"    - SQLite: {self.config.database_path}")
        logger.info(f"    - JSON: {self.config.consistency_output_dir}/{report.report_id}.json")
        logger.info(f"    - HTML: {html_path}")
        
        return report
    
    def _save_intermediate_result(self, stage: str, result: Dict[str, Any]):
        """保存中间结果到 SQLite（不再堆积 timestamp JSON）。"""
        try:
            get_store(self.config.database_path).save_artifact(
                stage, self._make_serializable(result)
            )
            logger.debug("  中间结果已写入 SQLite: %s", stage)
        except Exception as exc:
            logger.warning("中间结果写入 SQLite 失败 (%s): %s", stage, exc)
    
    def _save_final_report(self, report: VerificationReport):
        """导出 JSON 副本；权威数据在 SQLite。"""
        output_dir = self.config.consistency_output_dir
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{report.report_id}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False, default=str)
    
    def _make_serializable(self, obj: Any) -> Any:
        """将对象转换为可序列化的格式"""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif is_dataclass(obj):
            # 处理dataclass对象
            return self._make_serializable(asdict(obj))
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, 'value') and not isinstance(obj, (str, int, float, bool)):
            # Enum类型
            return obj.value
        elif hasattr(obj, '__dict__'):
            # 处理其他对象
            result = {}
            for k, v in obj.__dict__.items():
                if k.startswith('_'):
                    continue
                try:
                    result[k] = self._make_serializable(v)
                except:
                    result[k] = str(v)
            return result
        else:
            return obj


