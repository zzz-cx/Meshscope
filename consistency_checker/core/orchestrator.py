"""
全局流程编排器

负责协调静态分析、动态测试、一致性检查和可视化报告的完整流程
"""

import os
import json
import logging
from typing import Dict, Optional, Any
from datetime import datetime

from consistency_checker.config import get_config
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.core.consistency_checker import ConsistencyChecker
from consistency_checker.visualizer.report_generator import ComprehensiveReportGenerator
from consistency_checker.visualizer.graph_generator import GraphGenerator
from consistency_checker.models.data_models import VerificationReport

logger = logging.getLogger(__name__)


class Pipeline:
    """端到端一致性验证流水线"""
    
    def __init__(self, namespace: Optional[str] = None):
        """
        初始化流水线
        
        Args:
            namespace: Kubernetes命名空间
        """
        self.config = get_config()
        self.namespace = namespace or self.config.namespace
        
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
        
        # 第一阶段：静态分析
        logger.info("\n📋 第一阶段：静态配置分析")
        logger.info("-" * 80)
        self.static_result = self._run_static_analysis()
        
        # 第二阶段：动态分析
        logger.info("\n🔄 第二阶段：动态测试分析")
        logger.info("-" * 80)
        self.dynamic_result = self._run_dynamic_analysis()
        
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
    
    def _run_static_analysis(self) -> Dict[str, Any]:
        """运行静态分析"""
        self.static_analyzer = StaticAnalyzer(
            config_dir=self.config.control_plane_config_dir,
            namespace=self.namespace
        )
        
        result = self.static_analyzer.analyze()
        
        # 保存结果
        self._save_intermediate_result("static_analysis", result)
        
        logger.info(f"  ✓ 静态策略数量: {len(result['static_policies'])}")
        logger.info(f"  ✓ 服务节点数量: {len(result['service_nodes'])}")
        logger.info(f"  ✓ 配置边数量: {len(result['config_edges'])}")
        logger.info(f"  ✓ 平面一致性问题: {len(result['plane_consistency_issues'])}")
        
        return result
    
    def _run_dynamic_analysis(self) -> Dict[str, Any]:
        """运行动态分析"""
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
    
    def _run_consistency_check(self) -> Any:
        """运行一致性检查"""
        if not self.static_result or not self.dynamic_result:
            raise RuntimeError("必须先运行静态分析和动态分析")
        
        self.consistency_checker = ConsistencyChecker(
            static_policies=self.static_result['static_policies'],
            dynamic_behaviors=self.dynamic_result['dynamic_behaviors'],
            tolerance=self.config.traffic_split_tolerance
        )
        
        result = self.consistency_checker.check()
        
        # 保存结果
        self._save_intermediate_result("consistency_check", {
            "overall_status": result.overall_status.value,
            "consistency_rate": result.consistency_rate,
            "total_policies": result.total_policies,
            "verified_policies": result.verified_policies,
            "inconsistencies": [
                {
                    "id": inc.inconsistency_id,
                    "type": inc.inconsistency_type,
                    "severity": inc.severity.value,
                    "description": inc.description,
                    "affected_services": inc.affected_services
                }
                for inc in result.inconsistencies
            ],
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
        
        # 5. 生成HTML报告
        logger.info("  🔹 生成HTML报告...")
        html_path = os.path.join(
            self.config.visualization_output_dir,
            f"{report.report_id}_report.html"
        )
        report_generator.generate_html_report(html_path, graph_generator.get_graph_data())
        
        logger.info(f"  ✓ 报告已保存")
        logger.info(f"    - JSON: {self.config.consistency_output_dir}/{report.report_id}.json")
        logger.info(f"    - HTML: {html_path}")
        
        return report
    
    def _save_intermediate_result(self, stage: str, result: Dict[str, Any]):
        """保存中间结果"""
        output_dir = self.config.consistency_output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)
        
        # 序列化处理
        serializable_result = self._make_serializable(result)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serializable_result, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"  保存中间结果: {filepath}")
    
    def _save_final_report(self, report: VerificationReport):
        """保存最终报告"""
        output_dir = self.config.consistency_output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, f"{report.report_id}.json")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    
    def _make_serializable(self, obj: Any) -> Any:
        """将对象转换为可序列化的格式"""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            # 处理dataclass等对象
            result = {}
            for k, v in obj.__dict__.items():
                if k.startswith('_'):
                    continue
                try:
                    if hasattr(v, 'value'):  # Enum
                        result[k] = v.value
                    elif isinstance(v, datetime):
                        result[k] = v.isoformat()
                    else:
                        result[k] = self._make_serializable(v)
                except:
                    result[k] = str(v)
            return result
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, 'value'):  # Enum
            return obj.value
        else:
            return obj


