#!/usr/bin/env python3
"""
报告生成器

主要功能：
1. 生成 HTML 格式的可视化测试报告
2. 生成 JSON 格式的详细测试报告
3. 支持多种图表和统计信息
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from .result_comparator import ComprehensiveResult, VerificationResult, VerificationStatus
from .behavior_model import ExpectedBehavior

class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, output_dir: str = "results/reports"):
        """
        初始化报告生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_comprehensive_report(self, results: List[ComprehensiveResult],
                                    test_config: Optional[Dict] = None,
                                    output_prefix: str = "test_report") -> Dict[str, str]:
        """
        生成综合测试报告
        
        Args:
            results: 验证结果列表
            test_config: 测试配置信息
            output_prefix: 输出文件前缀
            
        Returns:
            生成的文件路径字典
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 生成 JSON 报告
        json_file = os.path.join(self.output_dir, f"{output_prefix}_{timestamp}.json")
        self._generate_json_report(results, test_config, json_file)
        
        # 生成 HTML 报告
        html_file = os.path.join(self.output_dir, f"{output_prefix}_{timestamp}.html")
        self._generate_html_report(results, test_config, html_file)
        
        # 生成摘要文件
        summary_file = os.path.join(self.output_dir, f"{output_prefix}_summary_{timestamp}.txt")
        self._generate_summary_report(results, summary_file)
        
        print(f"📊 报告生成完成:")
        print(f"  - JSON 报告: {json_file}")
        print(f"  - HTML 报告: {html_file}")
        print(f"  - 摘要报告: {summary_file}")
        
        return {
            'json': json_file,
            'html': html_file,
            'summary': summary_file
        }
    
    def _generate_json_report(self, results: List[ComprehensiveResult],
                            test_config: Optional[Dict], output_file: str):
        """生成 JSON 格式报告"""
        # 计算整体统计
        overall_stats = self._calculate_overall_statistics(results)
        
        # 构建报告数据
        report_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_test_cases': len(results),
                'tool_version': '1.0.0',
                'test_config': test_config or {}
            },
            'overall_statistics': overall_stats,
            'test_results': []
        }
        
        # 添加每个测试用例的详细结果
        for result in results:
            test_result = {
                'case_id': result.case_id,
                'description': result.test_description,
                'overall_status': result.overall_status.value,
                'summary': result.summary,
                'metrics': result.metrics,
                'individual_verifications': []
            }
            
            # 添加各项验证结果
            for verification in result.individual_results:
                verification_data = {
                    'test_name': verification.test_name,
                    'status': verification.status.value,
                    'expected_value': verification.expected_value,
                    'actual_value': verification.actual_value,
                    'deviation': verification.deviation,
                    'message': verification.message,
                    'details': verification.details
                }
                test_result['individual_verifications'].append(verification_data)
            
            report_data['test_results'].append(test_result)
        
        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
    
    def _generate_html_report(self, results: List[ComprehensiveResult],
                            test_config: Optional[Dict], output_file: str):
        """生成 HTML 格式报告"""
        overall_stats = self._calculate_overall_statistics(results)
        
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Istio 动态测试报告</title>
    <style>
        {self._get_css_styles()}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>🛡️ Istio 动态测试验证报告</h1>
            <div class="timestamp">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        </header>
        
        <section class="summary">
            <h2>📊 测试摘要</h2>
            <div class="stats-grid">
                <div class="stat-card passed">
                    <h3>{overall_stats['passed_cases']}</h3>
                    <p>通过用例</p>
                </div>
                <div class="stat-card failed">
                    <h3>{overall_stats['failed_cases']}</h3>
                    <p>失败用例</p>
                </div>
                <div class="stat-card warning">
                    <h3>{overall_stats['warning_cases']}</h3>
                    <p>警告用例</p>
                </div>
                <div class="stat-card total">
                    <h3>{overall_stats['total_cases']}</h3>
                    <p>总用例数</p>
                </div>
            </div>
            <div class="success-rate">
                <h3>整体成功率: {overall_stats['success_rate']:.1%}</h3>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {overall_stats['success_rate']:.1f}%"></div>
                </div>
            </div>
        </section>
        
        <section class="test-details">
            <h2>📋 详细测试结果</h2>
            {self._generate_test_cases_html(results)}
        </section>
        
        <section class="verification-process">
            <h2>[DETAIL] 验证过程详情</h2>
            {self._generate_verification_process_html(test_config)}
        </section>
        
        <section class="charts">
            <h2>📈 统计图表</h2>
            {self._generate_charts_html(results)}
        </section>
        
        <footer class="footer">
            <p>由 Istio 动态测试框架生成 | {datetime.now().year}</p>
        </footer>
    </div>
    
    <script>
        {self._get_javascript()}
    </script>
</body>
</html>
"""
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _generate_summary_report(self, results: List[ComprehensiveResult], output_file: str):
        """生成文本摘要报告"""
        overall_stats = self._calculate_overall_statistics(results)
        
        content = []
        content.append("=" * 60)
        content.append("Istio 动态测试验证报告摘要")
        content.append("=" * 60)
        content.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("")
        
        # 整体统计
        content.append("📊 整体统计:")
        content.append(f"  总用例数: {overall_stats['total_cases']}")
        content.append(f"  通过用例: {overall_stats['passed_cases']}")
        content.append(f"  失败用例: {overall_stats['failed_cases']}")
        content.append(f"  警告用例: {overall_stats['warning_cases']}")
        content.append(f"  成功率: {overall_stats['success_rate']:.1%}")
        content.append("")
        
        # 用例详情
        content.append("📋 用例详情:")
        for result in results:
            status_symbol = {
                VerificationStatus.PASSED: "✅",
                VerificationStatus.FAILED: "❌",
                VerificationStatus.WARNING: "⚠️",
                VerificationStatus.SKIPPED: "⏭️"
            }.get(result.overall_status, "❓")
            
            content.append(f"  {status_symbol} {result.case_id}: {result.test_description}")
            content.append(f"     {result.summary}")
            
            # 显示失败的验证项
            failed_verifications = [v for v in result.individual_results 
                                  if v.status == VerificationStatus.FAILED]
            if failed_verifications:
                content.append("     失败项:")
                for verification in failed_verifications:
                    content.append(f"       - {verification.test_name}: {verification.message}")
            
            content.append("")
        
        # 建议
        if overall_stats['failed_cases'] > 0:
            content.append("💡 建议:")
            content.append("  1. 检查失败用例的具体错误信息")
            content.append("  2. 验证 Istio 配置是否正确部署")
            content.append("  3. 确认测试环境网络连通性")
            content.append("  4. 查看详细的 HTML 或 JSON 报告获取更多信息")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
    
    def _calculate_overall_statistics(self, results: List[ComprehensiveResult]) -> Dict[str, Any]:
        """计算整体统计信息"""
        total_cases = len(results)
        passed_cases = sum(1 for r in results if r.overall_status == VerificationStatus.PASSED)
        failed_cases = sum(1 for r in results if r.overall_status == VerificationStatus.FAILED)
        warning_cases = sum(1 for r in results if r.overall_status == VerificationStatus.WARNING)
        skipped_cases = sum(1 for r in results if r.overall_status == VerificationStatus.SKIPPED)
        
        success_rate = passed_cases / total_cases if total_cases > 0 else 0
        
        # 计算总请求数和成功率
        total_requests = sum(r.metrics.get('total_requests', 0) for r in results)
        total_success_requests = sum(r.metrics.get('success_count', 0) for r in results)
        overall_success_rate = total_success_requests / total_requests if total_requests > 0 else 0
        
        return {
            'total_cases': total_cases,
            'passed_cases': passed_cases,
            'failed_cases': failed_cases,
            'warning_cases': warning_cases,
            'skipped_cases': skipped_cases,
            'success_rate': success_rate,
            'total_requests': total_requests,
            'total_success_requests': total_success_requests,
            'overall_success_rate': overall_success_rate
        }
    
    def _generate_test_cases_html(self, results: List[ComprehensiveResult]) -> str:
        """生成测试用例详情的 HTML"""
        html_parts = []
        
        for result in results:
            status_class = result.overall_status.value
            status_symbol = {
                VerificationStatus.PASSED: "✅",
                VerificationStatus.FAILED: "❌", 
                VerificationStatus.WARNING: "⚠️",
                VerificationStatus.SKIPPED: "⏭️"
            }.get(result.overall_status, "❓")
            
            html_parts.append(f"""
            <div class="test-case {status_class}">
                <div class="test-case-header">
                    <h3>{status_symbol} {result.case_id}</h3>
                    <span class="status-badge {status_class}">{result.overall_status.value.upper()}</span>
                </div>
                <p class="test-description">{result.test_description}</p>
                <p class="test-summary">{result.summary}</p>
                
                <div class="metrics">
                    <span>请求数: {result.metrics.get('total_requests', 0)}</span>
                    <span>成功率: {result.metrics.get('success_rate', 0):.1%}</span>
                    <span>Pod数: {result.metrics.get('total_pods', 0)}</span>
                </div>
                
                <div class="verifications">
                    <h4>验证详情:</h4>
            """)
            
            for verification in result.individual_results:
                verification_status = verification.status.value
                verification_symbol = {
                    VerificationStatus.PASSED: "✅",
                    VerificationStatus.FAILED: "❌",
                    VerificationStatus.WARNING: "⚠️",
                    VerificationStatus.SKIPPED: "⏭️"
                }.get(verification.status, "❓")
                
                # 生成详细的验证信息
                verification_details = self._generate_verification_details_html(verification)
                
                html_parts.append(f"""
                    <div class="verification-item {verification_status}">
                        <div class="verification-header">
                            <span class="verification-name">{verification_symbol} {verification.test_name}</span>
                            <span class="verification-message">{verification.message}</span>
                        </div>
                        {verification_details}
                    </div>
                """)
            
            html_parts.append("</div></div>")
        
        return ''.join(html_parts)
    
    def _generate_verification_details_html(self, verification: VerificationResult) -> str:
        """生成单个验证项的详细信息HTML"""
        if not verification.details:
            return ""
        
        details_html = []
        
        # 根据验证类型生成不同的详细信息
        if verification.test_name == "重试验证":
            details_html.append('<div class="verification-details retry-details">')
            details_html.append('<h5>重试验证详情</h5>')
            
            # 时间分析
            if 'avg_response_time' in verification.details:
                details_html.append(f'<p>📊 平均响应时间: {verification.details["avg_response_time"]:.3f}s</p>')
            
            if 'time_variance_ratio' in verification.details:
                details_html.append(f'<p>📈 响应时间方差比: {verification.details["time_variance_ratio"]:.1f} (P95/P50)</p>')
            
            if 'retry_indicators' in verification.details:
                indicators = verification.details['retry_indicators']
                if indicators:
                    details_html.append('<p>[METRICS] 重试指标:</p>')
                    details_html.append('<ul>')
                    for indicator in indicators:
                        details_html.append(f'<li>{indicator}</li>')
                    details_html.append('</ul>')
            
            # 时间验证结果
            if 'time_validation_passed' in verification.details:
                validation_icon = "✅" if verification.details['time_validation_passed'] else "❌"
                details_html.append(f'<p>{validation_icon} 时间验证: {"通过" if verification.details["time_validation_passed"] else "失败"}</p>')
            
            # 期望配置
            if 'expected_max_retries' in verification.details and verification.details['expected_max_retries']:
                details_html.append(f'<p>⚙️ 期望重试次数: {verification.details["expected_max_retries"]}</p>')
            
            if 'expected_retry_timeout' in verification.details and verification.details['expected_retry_timeout']:
                details_html.append(f'<p>⏱️ 期望重试超时: {verification.details["expected_retry_timeout"]}s</p>')
            
            details_html.append('</div>')
        
        elif verification.test_name == "熔断器验证":
            details_html.append('<div class="verification-details circuit-breaker-details">')
            details_html.append('<h5>熔断器验证详情</h5>')
            
            # 基本统计
            if 'total_requests' in verification.details:
                details_html.append(f'<p>📊 总请求数: {verification.details["total_requests"]}</p>')
            
            if 'error_rate' in verification.details:
                details_html.append(f'<p>❌ 错误率: {verification.details["error_rate"]:.1%}</p>')
            
            if 'circuit_breaker_errors' in verification.details:
                details_html.append(f'<p>⚡ 503熔断错误: {verification.details["circuit_breaker_errors"]}个</p>')
            
            # 熔断指标
            if 'cb_indicators' in verification.details:
                indicators = verification.details['cb_indicators']
                if indicators:
                    details_html.append('<p>[METRICS] 熔断指标:</p>')
                    details_html.append('<ul>')
                    for indicator in indicators:
                        details_html.append(f'<li>{indicator}</li>')
                    details_html.append('</ul>')
            
            # 时间分析
            if 'time_analysis' in verification.details:
                time_analysis = verification.details['time_analysis']
                details_html.append('<h6>时间分析:</h6>')
                details_html.append('<ul>')
                
                if 'max_consecutive_errors' in time_analysis:
                    details_html.append(f'<li>最大连续错误: {time_analysis["max_consecutive_errors"]}个</li>')
                
                if 'trip_detection_time' in time_analysis:
                    details_html.append(f'<li>熔断触发时间: {time_analysis["trip_detection_time"]:.3f}s</li>')
                
                if 'recovery_time' in time_analysis:
                    details_html.append(f'<li>恢复时间: {time_analysis["recovery_time"]:.3f}s</li>')
                
                if 'avg_cb_response_time' in time_analysis:
                    details_html.append(f'<li>熔断响应时间: {time_analysis["avg_cb_response_time"]:.3f}s</li>')
                
                details_html.append('</ul>')
            
            # 时间验证结果
            if 'time_validation_passed' in verification.details:
                validation_icon = "✅" if verification.details['time_validation_passed'] else "❌"
                details_html.append(f'<p>{validation_icon} 时间验证: {"通过" if verification.details["time_validation_passed"] else "失败"}</p>')
            
            # 期望配置
            if 'expected_trip_threshold' in verification.details and verification.details['expected_trip_threshold']:
                details_html.append(f'<p>⚙️ 期望熔断阈值: {verification.details["expected_trip_threshold"]}</p>')
            
            if 'expected_recovery_time' in verification.details and verification.details['expected_recovery_time']:
                details_html.append(f'<p>⏱️ 期望恢复时间: {verification.details["expected_recovery_time"]}s</p>')
            
            details_html.append('</div>')
        
        elif verification.test_name == "流量分布验证":
            details_html.append('<div class="verification-details traffic-details">')
            details_html.append('<h5>流量分布验证详情</h5>')
            
            if 'distribution_analysis' in verification.details:
                analysis = verification.details['distribution_analysis']
                details_html.append('<div class="distribution-table">')
                details_html.append('<table><thead><tr><th>版本</th><th>实际请求</th><th>实际占比</th><th>期望占比</th><th>偏差</th></tr></thead><tbody>')
                
                for version_data in analysis:
                    version = version_data.get('version', 'N/A')
                    actual_count = version_data.get('actual_count', 0)
                    actual_percentage = version_data.get('actual_percentage', 0) * 100
                    expected_percentage = version_data.get('expected_percentage', 0) * 100
                    deviation = version_data.get('deviation', 0) * 100
                    
                    details_html.append(f'''
                        <tr>
                            <td>{version}</td>
                            <td>{actual_count}</td>
                            <td>{actual_percentage:.1f}%</td>
                            <td>{expected_percentage:.1f}%</td>
                            <td class="{'positive' if deviation > 0 else 'negative'}">{deviation:+.1f}%</td>
                        </tr>
                    ''')
                
                details_html.append('</tbody></table>')
                details_html.append('</div>')
            
            if 'effective_margin_of_error' in verification.details:
                details_html.append(f'<p>⚙️ 有效容错: ±{verification.details["effective_margin_of_error"]:.1%}</p>')
            
            details_html.append('</div>')
        
        elif verification.test_name == "HTTP状态码验证":
            details_html.append('<div class="verification-details http-details">')
            details_html.append('<h5>HTTP验证详情</h5>')
            
            if 'total_requests' in verification.details:
                details_html.append(f'<p>📊 总请求数: {verification.details["total_requests"]}</p>')
            
            if 'success_rate' in verification.details:
                details_html.append(f'<p>✅ 成功率: {verification.details["success_rate"]:.1%}</p>')
            
            if 'avg_response_time' in verification.details:
                details_html.append(f'<p>⏱️ 平均响应时间: {verification.details["avg_response_time"]:.3f}s</p>')
            
            if 'status_code_distribution' in verification.details:
                distribution = verification.details['status_code_distribution']
                details_html.append('<p>📋 状态码分布:</p>')
                details_html.append('<ul>')
                for code, count in distribution.items():
                    details_html.append(f'<li>{code}: {count}次</li>')
                details_html.append('</ul>')
            
            details_html.append('</div>')
        
        # 通用详情展示
        elif verification.details:
            details_html.append('<div class="verification-details generic-details">')
            details_html.append('<h5>详细信息</h5>')
            details_html.append('<ul>')
            
            for key, value in verification.details.items():
                if isinstance(value, (int, float, str, bool)):
                    details_html.append(f'<li><strong>{key}:</strong> {value}</li>')
                elif isinstance(value, list) and len(value) <= 5:
                    details_html.append(f'<li><strong>{key}:</strong> {", ".join(map(str, value))}</li>')
            
            details_html.append('</ul>')
            details_html.append('</div>')
        
        return ''.join(details_html)
    
    def _generate_verification_process_html(self, test_config: Optional[Dict]) -> str:
        """生成验证过程详情的 HTML"""
        if not test_config or "verification_process" not in test_config:
            return '<p>⚠️ 未找到验证过程信息</p>'
        
        process_info = test_config["verification_process"]
        
        html_parts = []
        
        # 总体信息
        total_duration = process_info.get("total_duration_ms", 0) / 1000
        html_parts.append(f"""
        <div class="process-summary">
            <h3>📝 总体信息</h3>
            <div class="process-info-grid">
                <div class="info-item">
                    <span class="label">开始时间:</span>
                    <span class="value">{process_info.get('start_time', 'N/A')}</span>
                </div>
                <div class="info-item">
                    <span class="label">结束时间:</span>
                    <span class="value">{process_info.get('end_time', 'N/A')}</span>
                </div>
                <div class="info-item">
                    <span class="label">总耗时:</span>
                    <span class="value">{total_duration:.2f}秒</span>
                </div>
                <div class="info-item">
                    <span class="label">配置文件:</span>
                    <span class="value">{process_info.get('istio_config_file', '未使用') or '未使用'}</span>
                </div>
            </div>
        </div>
        """)
        
        # 步骤详情
        steps = process_info.get("steps", [])
        if steps:
            html_parts.append('<h3>🔄 验证步骤</h3>')
            html_parts.append('<div class="steps-container">')
            
            for step in steps:
                step_duration = step.get("duration_ms", 0) / 1000
                step_html = f"""
                <div class="step-card">
                    <div class="step-header">
                        <h4>步骤 {step.get('step', 'N/A')}: {step.get('name', 'Unknown')}</h4>
                        <span class="step-duration">{step_duration:.2f}s</span>
                    </div>
                    <div class="step-content">
                """
                
                # 步骤特定信息
                if step.get('name') == '解析测试矩阵':
                    step_html += f"""
                        <p><strong>解析的行为数量:</strong> {step.get('parsed_behaviors_count', 0)}</p>
                        <details class="behaviors-details">
                            <summary>查看期望行为详情 ({len(step.get('behaviors_summary', []))}个)</summary>
                            <div class="behaviors-list">
                    """
                    for behavior in step.get('behaviors_summary', []):
                        step_html += f"""
                                <div class="behavior-item">
                                    <strong>{behavior.get('case_id', 'N/A')}</strong>: 
                                    {behavior.get('policy_type', 'N/A')} - {behavior.get('description', 'N/A')}
                        """
                        if behavior.get('expected_retry_attempts'):
                            step_html += f"<br>🔄 重试: {behavior['expected_retry_attempts']}次, 单次超时: {behavior.get('expected_per_try_timeout', 'N/A')}s"
                        if behavior.get('expected_trip_threshold'):
                            step_html += f"<br>⚡ 熔断: 阈值{behavior['expected_trip_threshold']}, 恢复时间: {behavior.get('expected_recovery_time', 'N/A')}s"
                        step_html += "</div>"
                    step_html += "</div></details>"
                
                elif step.get('name') == '加载和解析日志':
                    step_html += f"""
                        <p><strong>处理的用例数:</strong> {step.get('cases_with_logs_count', 0)}</p>
                        <p><strong>总日志条目:</strong> {step.get('total_log_entries', 0)}</p>
                        <details class="log-details">
                            <summary>查看日志解析详情</summary>
                            <div class="log-summary-table">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>用例ID</th>
                                            <th>日志条目</th>
                                            <th>Pod数量</th>
                                            <th>成功率</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    for log_info in step.get('log_summary', []):
                        success_rate = log_info.get('success_rate', 0) * 100
                        step_html += f"""
                                        <tr>
                                            <td>{log_info.get('case_id', 'N/A')}</td>
                                            <td>{log_info.get('total_entries', 0)}</td>
                                            <td>{log_info.get('pod_count', 0)}</td>
                                            <td class="success-rate-cell">{success_rate:.1f}%</td>
                                        </tr>
                        """
                    step_html += """
                                    </tbody>
                                </table>
                            </div>
                        </details>
                    """
                
                elif step.get('name') == '执行对比验证':
                    step_html += f"""
                        <p><strong>验证结果数量:</strong> {step.get('verification_results_count', 0)}</p>
                        <div class="verification-stats">
                            <span class="stat passed">✅ 通过: {step.get('passed_count', 0)}</span>
                            <span class="stat failed">❌ 失败: {step.get('failed_count', 0)}</span>
                            <span class="stat warning">⚠️ 警告: {step.get('warning_count', 0)}</span>
                        </div>
                    """
                
                elif step.get('name') == '生成验证报告':
                    step_html += f"""
                        <p><strong>输出目录:</strong> {step.get('output_dir', 'N/A')}</p>
                        <p><strong>生成的文件:</strong></p>
                        <ul>
                    """
                    for file_path in step.get('generated_files', []):
                        step_html += f"<li>{file_path}</li>"
                    step_html += "</ul>"
                
                # 错误信息
                if step.get('error'):
                    step_html += f'<div class="error-message">❌ 错误: {step["error"]}</div>'
                
                step_html += """
                    </div>
                </div>
                """
                html_parts.append(step_html)
            
            html_parts.append('</div>')
        
        return ''.join(html_parts)
    
    def _generate_charts_html(self, results: List[ComprehensiveResult]) -> str:
        """生成图表的 HTML"""
        overall_stats = self._calculate_overall_statistics(results)
        
        return f"""
        <div class="charts-container">
            <div class="chart">
                <h3>测试用例状态分布</h3>
                <div class="pie-chart" id="statusPieChart">
                    <div class="pie-slice passed" style="--percentage: {overall_stats['passed_cases']/overall_stats['total_cases']*100:.1f}"></div>
                    <div class="pie-slice failed" style="--percentage: {overall_stats['failed_cases']/overall_stats['total_cases']*100:.1f}"></div>
                    <div class="pie-slice warning" style="--percentage: {overall_stats['warning_cases']/overall_stats['total_cases']*100:.1f}"></div>
                </div>
                <div class="legend">
                    <div class="legend-item">
                        <span class="color-box passed"></span>
                        <span>通过 ({overall_stats['passed_cases']})</span>
                    </div>
                    <div class="legend-item">
                        <span class="color-box failed"></span>
                        <span>失败 ({overall_stats['failed_cases']})</span>
                    </div>
                    <div class="legend-item">
                        <span class="color-box warning"></span>
                        <span>警告 ({overall_stats['warning_cases']})</span>
                    </div>
                </div>
            </div>
            
            <div class="chart">
                <h3>请求统计</h3>
                <div class="bar-chart">
                    <div class="bar-item">
                        <span class="bar-label">总请求数</span>
                        <div class="bar">
                            <div class="bar-fill" style="width: 100%"></div>
                            <span class="bar-value">{overall_stats['total_requests']}</span>
                        </div>
                    </div>
                    <div class="bar-item">
                        <span class="bar-label">成功请求</span>
                        <div class="bar">
                            <div class="bar-fill success" style="width: {overall_stats['overall_success_rate']*100:.1f}%"></div>
                            <span class="bar-value">{overall_stats['total_success_requests']}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
    
    def _get_css_styles(self) -> str:
        """获取 CSS 样式"""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .timestamp {
            opacity: 0.9;
            font-size: 1.1em;
        }
        
        .summary {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            color: white;
        }
        
        .stat-card h3 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .stat-card.passed { background: #4CAF50; }
        .stat-card.failed { background: #f44336; }
        .stat-card.warning { background: #ff9800; }
        .stat-card.total { background: #2196F3; }
        
        .success-rate h3 {
            text-align: center;
            margin-bottom: 15px;
            color: #333;
        }
        
        .progress-bar {
            background: #e0e0e0;
            border-radius: 25px;
            height: 30px;
            overflow: hidden;
        }
        
        .progress-fill {
            background: linear-gradient(90deg, #4CAF50, #8BC34A);
            height: 100%;
            transition: width 0.3s ease;
        }
        
        .test-details {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .test-case {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 20px;
            overflow: hidden;
        }
        
        .test-case.passed { border-left: 5px solid #4CAF50; }
        .test-case.failed { border-left: 5px solid #f44336; }
        .test-case.warning { border-left: 5px solid #ff9800; }
        
        .test-case-header {
            background: #f8f9fa;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .test-case-header h3 {
            margin: 0;
            font-size: 1.2em;
        }
        
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
        }
        
        .status-badge.passed { background: #4CAF50; color: white; }
        .status-badge.failed { background: #f44336; color: white; }
        .status-badge.warning { background: #ff9800; color: white; }
        
        .test-description, .test-summary {
            padding: 10px 20px;
            margin: 0;
        }
        
        .test-description {
            font-weight: bold;
            color: #555;
        }
        
        .metrics {
            padding: 10px 20px;
            background: #f8f9fa;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        
        .metrics span {
            background: white;
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 0.9em;
            border: 1px solid #e0e0e0;
        }
        
        .verifications {
            padding: 20px;
        }
        
        .verification-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .verification-item:last-child {
            border-bottom: none;
        }
        
        .verification-name {
            font-weight: bold;
        }
        
        .verification-message {
            color: #666;
            font-size: 0.9em;
        }
        
        .charts {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .charts-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
        }
        
        .chart h3 {
            text-align: center;
            margin-bottom: 20px;
            color: #333;
        }
        
        .legend {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .color-box {
            width: 16px;
            height: 16px;
            border-radius: 3px;
        }
        
        .color-box.passed { background: #4CAF50; }
        .color-box.failed { background: #f44336; }
        .color-box.warning { background: #ff9800; }
        
        .bar-chart {
            max-width: 400px;
            margin: 0 auto;
        }
        
        .bar-item {
            margin-bottom: 15px;
        }
        
        .bar-label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        
        .bar {
            background: #e0e0e0;
            border-radius: 10px;
            height: 30px;
            position: relative;
            overflow: hidden;
        }
        
        .bar-fill {
            background: #2196F3;
            height: 100%;
            border-radius: 10px;
            transition: width 0.3s ease;
        }
        
        .bar-fill.success {
            background: #4CAF50;
        }
        
        .bar-value {
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            font-weight: bold;
            color: #333;
        }
        
        .footer {
            text-align: center;
            padding: 20px;
            color: #666;
            margin-top: 30px;
        }
        
        /* 验证过程样式 */
        .verification-process {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .process-summary {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 25px;
        }
        
        .process-info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            background: white;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }
        
        .info-item .label {
            font-weight: 600;
            color: #2c3e50;
        }
        
        .info-item .value {
            color: #34495e;
            font-family: monospace;
        }
        
        .steps-container {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        .step-card {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            transition: box-shadow 0.3s ease;
        }
        
        .step-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .step-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .step-header h4 {
            margin: 0;
            font-size: 1.1em;
        }
        
        .step-duration {
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.9em;
            font-weight: 600;
        }
        
        .step-content {
            padding: 20px;
            background: white;
        }
        
        .behaviors-details, .log-details {
            margin-top: 15px;
        }
        
        .behaviors-details summary, .log-details summary {
            cursor: pointer;
            font-weight: 600;
            color: #3498db;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
            margin-bottom: 10px;
        }
        
        .behaviors-list {
            padding: 10px;
            background: #fdfdfd;
            border-radius: 5px;
            border: 1px solid #e9ecef;
        }
        
        .behavior-item {
            padding: 8px 12px;
            margin-bottom: 8px;
            background: white;
            border-radius: 4px;
            border-left: 3px solid #3498db;
            font-size: 0.9em;
        }
        
        .log-summary-table table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        
        .log-summary-table th,
        .log-summary-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        
        .log-summary-table th {
            background: #f8f9fa;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .success-rate-cell {
            font-weight: 600;
            color: #27ae60;
        }
        
        .verification-stats {
            display: flex;
            gap: 20px;
            margin-top: 15px;
        }
        
        .verification-stats .stat {
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9em;
        }
        
        .verification-stats .stat.passed {
            background: #d5f5d5;
            color: #2d7d2d;
        }
        
        .verification-stats .stat.failed {
            background: #f5d5d5;
            color: #7d2d2d;
        }
        
        .verification-stats .stat.warning {
            background: #fff3cd;
            color: #856404;
        }
        
        .error-message {
            margin-top: 15px;
            padding: 12px;
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            border-radius: 5px;
            color: #721c24;
            font-weight: 500;
        }
        
        /* 验证详情样式 */
        .verification-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .verification-details {
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #3498db;
        }
        
        .verification-details h5 {
            margin: 0 0 10px 0;
            color: #2c3e50;
            font-size: 1.1em;
        }
        
        .verification-details h6 {
            margin: 10px 0 5px 0;
            color: #34495e;
            font-size: 1em;
        }
        
        .verification-details p {
            margin: 5px 0;
            font-size: 0.9em;
        }
        
        .verification-details ul {
            margin: 10px 0;
            padding-left: 20px;
        }
        
        .verification-details li {
            margin: 3px 0;
            font-size: 0.9em;
        }
        
        .retry-details {
            border-left-color: #f39c12;
            background: #fef9e7;
        }
        
        .circuit-breaker-details {
            border-left-color: #e74c3c;
            background: #fdf2f2;
        }
        
        .traffic-details {
            border-left-color: #9b59b6;
            background: #f8f4ff;
        }
        
        .http-details {
            border-left-color: #27ae60;
            background: #f0f8f0;
        }
        
        .generic-details {
            border-left-color: #95a5a6;
            background: #f5f6fa;
        }
        
        .distribution-table table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            font-size: 0.9em;
        }
        
        .distribution-table th,
        .distribution-table td {
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
        }
        
        .distribution-table th {
            background: #e9ecef;
            font-weight: 600;
            color: #495057;
        }
        
        .distribution-table .positive {
            color: #dc3545;
            font-weight: 600;
        }
        
        .distribution-table .negative {
            color: #28a745;
            font-weight: 600;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }
            
            .header h1 {
                font-size: 2em;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .charts-container {
                grid-template-columns: 1fr;
            }
        }
        """
    
    def _get_javascript(self) -> str:
        """获取 JavaScript 代码"""
        return """
        // 添加一些交互性
        document.addEventListener('DOMContentLoaded', function() {
            // 点击测试用例标题时折叠/展开详情
            document.querySelectorAll('.test-case-header').forEach(header => {
                header.style.cursor = 'pointer';
                header.addEventListener('click', function() {
                    const verifications = this.parentElement.querySelector('.verifications');
                    if (verifications) {
                        verifications.style.display = verifications.style.display === 'none' ? 'block' : 'none';
                    }
                });
            });
            
            // 添加一些动画效果
            setTimeout(() => {
                document.querySelectorAll('.progress-fill, .bar-fill').forEach(el => {
                    el.style.opacity = '1';
                    el.style.transform = 'scaleX(1)';
                });
            }, 500);
        });
        """

# 工具函数
def generate_quick_report(results: List[ComprehensiveResult], 
                         output_dir: str = "results/reports") -> str:
    """
    快速生成简单的文本报告
    
    Args:
        results: 验证结果列表
        output_dir: 输出目录
        
    Returns:
        生成的报告文件路径
    """
    generator = ReportGenerator(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"quick_report_{timestamp}.txt")
    
    generator._generate_summary_report(results, output_file)
    return output_file 