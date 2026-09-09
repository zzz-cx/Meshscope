"""
报告生成器

生成综合验证报告（JSON和HTML格式）
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from consistency_checker.models.data_models import (
    VerificationReport,
    ConsistencyResult,
    SeverityLevel
)
from consistency_checker.core.finding_records import LAYER_CATALOG, checks_performed

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = os.path.join(
    os.path.dirname(__file__), "templates", "consistency_report.html"
)


class ComprehensiveReportGenerator:
    """综合报告生成器"""
    
    def __init__(
        self,
        static_result: Dict[str, Any],
        dynamic_result: Dict[str, Any],
        consistency_result: ConsistencyResult,
        namespace: str = "default"
    ):
        """
        初始化报告生成器
        
        Args:
            static_result: 静态分析结果
            dynamic_result: 动态测试结果
            consistency_result: 一致性检查结果
            namespace: 命名空间
        """
        self.static_result = static_result
        self.dynamic_result = dynamic_result
        self.consistency_result = consistency_result
        self.namespace = namespace
        self._report: Optional[VerificationReport] = None
        
    def generate(self) -> VerificationReport:
        """
        生成综合报告
        
        Returns:
            验证报告对象
        """
        logger.info("生成综合验证报告")
        
        report_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        report = VerificationReport(
            report_id=report_id,
            title=f"Istio配置一致性验证报告 - {self.namespace}",
            timestamp=datetime.now(),
            namespace=self.namespace,
            executed_by="consistency_checker",
            
            # 静态分析结果
            static_analysis=self._summarize_static_analysis(),
            
            # 动态测试结果
            dynamic_testing=self._summarize_dynamic_testing(),
            
            # 一致性检查结果
            consistency_check=self.consistency_result,
            
            # 图数据
            graph_nodes=self.static_result.get('service_nodes', []),
            graph_edges=self.static_result.get('config_edges', []),
            
            # 报告内容
            executive_summary=self._generate_executive_summary(),
            detailed_findings=self._generate_detailed_findings(),
            recommendations=self._generate_recommendations(),
            metadata={
                "layers": LAYER_CATALOG,
                "checks_performed": checks_performed(),
            },
        )
        
        logger.info(f"  ✓ 报告生成完成: {report_id}")
        self._report = report
        return report
    
    def _summarize_static_analysis(self) -> Dict[str, Any]:
        """总结静态分析结果"""
        return {
            "total_services": len(self.static_result.get('service_nodes', [])),
            "total_policies": len(self.static_result.get('static_policies', [])),
            "total_edges": len(self.static_result.get('config_edges', [])),
            "plane_consistency_issues": len(self.static_result.get('plane_consistency_issues', [])),
            "policies_by_type": self._count_policies_by_type(),
            "services_with_virtualservice": sum(
                1 for node in self.static_result.get('service_nodes', [])
                if node.has_virtualservice
            ),
            "services_with_destinationrule": sum(
                1 for node in self.static_result.get('service_nodes', [])
                if node.has_destinationrule
            )
        }
    
    def _summarize_dynamic_testing(self) -> Dict[str, Any]:
        """总结动态测试结果"""
        return {
            "total_test_cases": len(self.dynamic_result.get('dynamic_behaviors', [])),
            "verified_tests": self.dynamic_result.get('summary', {}).get('verified_tests', 0),
            "failed_tests": self.dynamic_result.get('summary', {}).get('failed_tests', 0),
            "verification_rate": self.dynamic_result.get('statistics', {}).get('verification_rate', 0.0),
            "tests_by_policy_type": self.dynamic_result.get('statistics', {}).get('by_policy_type', {})
        }
    
    def _count_policies_by_type(self) -> Dict[str, int]:
        """统计各类型策略数量"""
        counts = {}
        for policy in self.static_result.get('static_policies', []):
            policy_type = policy.policy_type.value
            counts[policy_type] = counts.get(policy_type, 0) + 1
        return counts
    
    def _generate_executive_summary(self) -> str:
        """生成执行摘要"""
        cr = self.consistency_result
        
        summary_parts = [
            f"# 执行摘要\n",
            f"命名空间: {self.namespace}",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"## 总体状态: {cr.overall_status.value.upper()}\n",
            f"**一致性率**: {cr.consistency_rate:.2%}",
            f"**总策略数**: {cr.total_policies}",
            f"**已验证策略**: {cr.verified_policies}",
            f"**不一致策略**: {len(cr.inconsistent_policies)}",
            f"**未验证策略**: {len(cr.unverified_policies)}\n",
            f"## 问题概览\n",
            f"- 总不一致性: {len(cr.inconsistencies)}",
            f"- 关键问题: {cr.summary.get('critical_issues', 0)}",
            f"- 高优先级问题: {cr.summary.get('high_issues', 0)}",
            f"- 作用范围问题: {cr.summary.get('scope_issues', 0)}",
            f"- 行为偏差: {cr.summary.get('behavior_deviations', 0)}",
            f"- 策略冲突: {cr.summary.get('policy_conflicts', 0)}"
        ]
        
        # 添加关键发现
        if cr.inconsistencies:
            critical_issues = [
                inc for inc in cr.inconsistencies
                if inc.severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH]
            ]
            if critical_issues:
                summary_parts.append("\n## 关键发现\n")
                for inc in critical_issues[:5]:  # 显示前5个关键问题
                    summary_parts.append(
                        f"- [{inc.severity.value.upper()}] {inc.description}"
                    )
        
        return "\n".join(summary_parts)
    
    def _generate_detailed_findings(self) -> List[Dict[str, Any]]:
        """生成详细发现：每条含层次、资源、Sdecl / Sdp / Srt。"""
        findings = []
        for inc in sorted(
            self.consistency_result.inconsistencies,
            key=lambda x: ["critical", "high", "medium", "low", "info"].index(x.severity.value)
        ):
            findings.append(inc.to_record())
        return findings
    
    def _generate_recommendations(self) -> List[str]:
        """生成修复建议"""
        recommendations = []
        
        cr = self.consistency_result
        
        # 基于不一致性生成建议
        if cr.summary.get('critical_issues', 0) > 0:
            recommendations.append(
                "🔴 存在关键问题，建议立即修复以避免服务中断"
            )
        
        if cr.summary.get('unverified_policies', 0) > 0:
            recommendations.append(
                f"⚠️ 发现 {len(cr.unverified_policies)} 个未验证的策略，"
                f"建议添加对应的动态测试用例以确保策略生效"
            )
        
        if cr.summary.get('scope_issues', 0) > 0:
            recommendations.append(
                f"⚠️ 发现 {cr.summary['scope_issues']} 个作用范围问题，"
                f"建议检查策略配置的子集定义和测试覆盖"
            )
        
        if cr.summary.get('behavior_deviations', 0) > 0:
            recommendations.append(
                f"❌ 发现 {cr.summary['behavior_deviations']} 个行为偏差，"
                f"建议检查配置与实际运行时行为的差异"
            )
        
        if cr.summary.get('policy_conflicts', 0) > 0:
            recommendations.append(
                f"⚠️ 发现 {cr.summary['policy_conflicts']} 个策略冲突，"
                f"建议合并或删除冗余配置"
            )
        
        # 基于一致性率给出建议
        if cr.consistency_rate < 0.5:
            recommendations.append(
                "⚠️ 一致性率较低（< 50%），建议进行全面的配置审查和测试"
            )
        elif cr.consistency_rate < 0.8:
            recommendations.append(
                "ℹ️ 一致性率中等（50-80%），建议逐步修复发现的问题"
            )
        elif cr.consistency_rate < 1.0:
            recommendations.append(
                "✅ 一致性率较高（> 80%），建议修复剩余的小问题"
            )
        else:
            recommendations.append(
                "✅ 所有策略均通过验证，配置一致性良好"
            )
        
        # 平面一致性建议
        plane_issues = self.static_result.get('plane_consistency_issues', [])
        if plane_issues:
            recommendations.append(
                f"⚠️ 控制平面和数据平面存在 {len(plane_issues)} 个不一致，"
                f"建议检查配置同步状态"
            )
        
        return recommendations
    
    def generate_html_report(self, output_path: str, graph_data: Optional[Dict[str, Any]] = None):
        """
        生成HTML格式报告
        
        Args:
            output_path: 输出文件路径
            graph_data: 图数据（用于嵌入可视化）
        """
        logger.info(f"生成HTML报告: {output_path}")
        
        html_content = self._build_html_content(graph_data)
        
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"  ✓ HTML报告已保存")

    def html_payload(self, report: Optional[VerificationReport] = None) -> Dict[str, Any]:
        """HTML / 前端共用的报告载荷。"""
        cr = self.consistency_result
        report = report or getattr(self, "_report", None)
        records = [inc.to_record() for inc in cr.inconsistencies]
        return {
            "report_id": report.report_id if report else None,
            "title": report.title if report else f"Istio配置一致性验证报告 - {self.namespace}",
            "namespace": self.namespace,
            "timestamp": (report.timestamp.isoformat() if report else datetime.now().isoformat()),
            "overall_status": cr.overall_status.value,
            "consistency_rate": cr.consistency_rate,
            "verified_policies": cr.verified_policies,
            "total_policies": cr.total_policies,
            "metrics": {
                "total_policies": cr.total_policies,
                "verified_policies": cr.verified_policies,
                "unverified_policies": len(cr.unverified_policies),
                "critical_issues": cr.summary.get("critical_issues", 0),
                "high_issues": cr.summary.get("high_issues", 0),
            },
            "by_layer": cr.summary.get("by_layer") or {},
            "by_type": cr.summary.get("by_type") or {},
            "layers": LAYER_CATALOG,
            "checks": checks_performed(),
            "records": records,
            "inconsistencies": records,
            "recommendations": self._generate_recommendations(),
            "static_analysis": self._summarize_static_analysis(),
            "dynamic_testing": self._summarize_dynamic_testing(),
        }
    
    def _build_html_content(self, graph_data: Optional[Dict[str, Any]]) -> str:
        """构建 PatternFly 深色交互式 HTML 报告。"""
        with open(_HTML_TEMPLATE, "r", encoding="utf-8") as f:
            template = f.read()
        payload = self.html_payload()
        if graph_data is not None:
            payload["graph_summary"] = {
                "nodes": len((graph_data or {}).get("nodes") or []),
                "edges": len((graph_data or {}).get("edges") or []),
            }
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        blob = blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        return template.replace("__REPORT_JSON__", blob)


