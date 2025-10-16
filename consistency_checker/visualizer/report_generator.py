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

logger = logging.getLogger(__name__)


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
            recommendations=self._generate_recommendations()
        )
        
        logger.info(f"  ✓ 报告生成完成: {report_id}")
        
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
        """生成详细发现"""
        findings = []
        
        # 按严重程度分组
        for inc in sorted(
            self.consistency_result.inconsistencies,
            key=lambda x: ["critical", "high", "medium", "low", "info"].index(x.severity.value)
        ):
            finding = {
                "id": inc.inconsistency_id,
                "type": inc.inconsistency_type,
                "severity": inc.severity.value,
                "title": inc.description,
                "affected_policies": inc.affected_policies,
                "affected_services": inc.affected_services,
                "static_expectation": inc.static_expectation,
                "dynamic_observation": inc.dynamic_observation,
                "root_cause": inc.root_cause,
                "suggestions": inc.suggestions,
                "impact_scope": inc.impact_scope
            }
            findings.append(finding)
        
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
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"  ✓ HTML报告已保存")
    
    def _build_html_content(self, graph_data: Optional[Dict[str, Any]]) -> str:
        """构建HTML内容"""
        cr = self.consistency_result
        
        # 简化的HTML模板
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Istio一致性验证报告 - {self.namespace}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4caf50; padding-bottom: 10px; margin-bottom: 20px; }}
        h2 {{ color: #555; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #4caf50; padding-left: 10px; }}
        h3 {{ color: #666; margin-top: 20px; margin-bottom: 10px; }}
        .status-badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
        .status-consistent {{ background: #4caf50; color: white; }}
        .status-partial {{ background: #f57c00; color: white; }}
        .status-inconsistent {{ background: #d32f2f; color: white; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .metric-card {{ background: #f9f9f9; padding: 20px; border-radius: 8px; border-left: 4px solid #4caf50; }}
        .metric-value {{ font-size: 32px; font-weight: bold; color: #333; }}
        .metric-label {{ color: #666; font-size: 14px; margin-top: 5px; }}
        .issue-list {{ list-style: none; }}
        .issue-item {{ background: #fff3e0; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #f57c00; }}
        .issue-critical {{ background: #ffebee; border-left-color: #d32f2f; }}
        .issue-high {{ background: #fff3e0; border-left-color: #f57c00; }}
        .issue-medium {{ background: #e3f2fd; border-left-color: #2196f3; }}
        .severity {{ font-weight: bold; text-transform: uppercase; }}
        .severity-critical {{ color: #d32f2f; }}
        .severity-high {{ color: #f57c00; }}
        .severity-medium {{ color: #2196f3; }}
        .severity-low {{ color: #4caf50; }}
        .recommendations {{ background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .recommendations ul {{ padding-left: 20px; }}
        .recommendations li {{ margin: 10px 0; }}
        #graph {{ width: 100%; height: 600px; border: 1px solid #ddd; border-radius: 8px; margin: 20px 0; background: #fafafa; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; font-weight: bold; color: #333; }}
        tr:hover {{ background: #f9f9f9; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Istio配置一致性验证报告</h1>
        <p><strong>命名空间:</strong> {self.namespace} | <strong>生成时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>总体状态</h2>
        <p><span class="status-badge status-{cr.overall_status.value}">{cr.overall_status.value.upper()}</span></p>
        
        <div class="metrics">
            <div class="metric-card">
                <div class="metric-value">{cr.consistency_rate:.1%}</div>
                <div class="metric-label">一致性率</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{cr.total_policies}</div>
                <div class="metric-label">总策略数</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{cr.verified_policies}</div>
                <div class="metric-label">已验证策略</div>
            </div>
            <div class="metric-card">
                <div class="metric-value">{len(cr.inconsistencies)}</div>
                <div class="metric-label">不一致性问题</div>
            </div>
        </div>
        
        <h2>静态分析结果</h2>
        <table>
            <tr><th>指标</th><th>数值</th></tr>
            <tr><td>服务数量</td><td>{self.static_result.get('summary', {}).get('total_services', 0)}</td></tr>
            <tr><td>策略数量</td><td>{self.static_result.get('summary', {}).get('total_policies', 0)}</td></tr>
            <tr><td>配置边数量</td><td>{self.static_result.get('summary', {}).get('total_edges', 0)}</td></tr>
        </table>
        
        <h2>动态测试结果</h2>
        <table>
            <tr><th>指标</th><th>数值</th></tr>
            <tr><td>测试用例数</td><td>{self.dynamic_result.get('summary', {}).get('total_tests', 0)}</td></tr>
            <tr><td>验证通过</td><td>{self.dynamic_result.get('summary', {}).get('verified_tests', 0)}</td></tr>
            <tr><td>验证失败</td><td>{self.dynamic_result.get('summary', {}).get('failed_tests', 0)}</td></tr>
            <tr><td>验证率</td><td>{self.dynamic_result.get('statistics', {}).get('verification_rate', 0.0):.1%}</td></tr>
        </table>
        
        <h2>不一致性详情</h2>
        <ul class="issue-list">
"""
        
        # 添加不一致性列表
        for inc in cr.inconsistencies[:20]:  # 限制显示前20个
            severity_class = f"issue-{inc.severity.value}"
            html += f"""
            <li class="issue-item {severity_class}">
                <div><span class="severity severity-{inc.severity.value}">[{inc.severity.value}]</span> {inc.description}</div>
                <div style="margin-top: 10px; font-size: 14px; color: #666;">
                    <strong>受影响服务:</strong> {', '.join(inc.affected_services)}<br>
                    <strong>根本原因:</strong> {inc.root_cause or '未知'}
                </div>
            </li>
"""
        
        html += """
        </ul>
        
        <h2>修复建议</h2>
        <div class="recommendations">
            <ul>
"""
        
        # 添加建议列表
        for rec in self._generate_recommendations():
            html += f"<li>{rec}</li>\n"
        
        html += """
            </ul>
        </div>
        
    </div>
</body>
</html>
"""
        
        return html


