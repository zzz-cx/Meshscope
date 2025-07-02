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

from result_comparator import ComprehensiveResult, VerificationResult, VerificationStatus
from behavior_model import ExpectedBehavior

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
                    <div class="progress-fill" style="width: {overall_stats['success_rate']*100:.1f}%"></div>
                </div>
            </div>
        </section>
        
        <section class="test-details">
            <h2>📋 详细测试结果</h2>
            {self._generate_test_cases_html(results)}
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
                
                html_parts.append(f"""
                    <div class="verification-item {verification_status}">
                        <span class="verification-name">{verification_symbol} {verification.test_name}</span>
                        <span class="verification-message">{verification.message}</span>
                    </div>
                """)
            
            html_parts.append("</div></div>")
        
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