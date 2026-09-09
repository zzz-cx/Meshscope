#!/usr/bin/env python3
"""
结果统计与可视化分析器 - 箱线图/曲线图/散点图
"""

import os
import sys
import json
import argparse
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import rcParams

# 设置中文字体
rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

# 设置绘图样式
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")


class ResultAnalyzer:
    """结果分析器"""
    
    def __init__(self, results_file: str):
        """初始化分析器"""
        self.results_file = results_file
        self.data = self._load_results()
        self.df = self._create_dataframe()
        self.output_dir = Path("results/visualizations")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_results(self) -> Dict[str, Any]:
        """加载实验结果"""
        with open(self.results_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _create_dataframe(self) -> pd.DataFrame:
        """创建分析用的DataFrame"""
        rows = []
        
        method_results = self.data.get("method_results", [])
        for result in method_results:
            row = {
                "method": result.get("method", "unknown"),
                "config_scale": result.get("config_scale", "unknown"),
                "change_rate": result.get("change_rate", "unknown"),
                "repetition": result.get("repetition", 0),
                "total_time": result.get("total_time", 0),
                "success": result.get("success", True),
                "timestamp": result.get("timestamp", "")
            }
            
            # 提取准确性指标
            accuracy_metrics = result.get("accuracy_metrics", {})
            row.update({
                "precision": accuracy_metrics.get("precision", 0),
                "recall": accuracy_metrics.get("recall", 0),
                "f1_score": accuracy_metrics.get("f1_score", 0),
                "actual_issues": accuracy_metrics.get("actual_issues", 0)
            })
            
            # 提取性能指标
            if "static_results" in result:
                static_results = result["static_results"]
                row.update({
                    "parsing_time": static_results.get("parsing_time", 0),
                    "analysis_time": static_results.get("analysis_time", 0)
                })
            
            if "dynamic_results" in result:
                dynamic_results = result["dynamic_results"]
                row.update({
                    "traffic_generation_time": dynamic_results.get("traffic_generation_time", 0),
                    "validation_time": dynamic_results.get("validation_time", 0)
                })
            
            rows.append(row)
        
        return pd.DataFrame(rows)
    
    def generate_all_visualizations(self):
        """生成所有可视化图表"""
        print("生成可视化图表...")
        
        # 1. 延迟箱线图
        self._plot_latency_boxplot()
        
        # 2. 延迟曲线图
        self._plot_latency_timeline()
        
        # 3. 开销-延迟散点图
        self._plot_cost_latency_scatter()
        
        # 4. 精度表格
        self._plot_accuracy_table()
        
        # 5. 性能对比雷达图
        self._plot_performance_radar()
        
        # 6. 配置规模影响分析
        self._plot_scale_impact()
        
        # 7. 变更速率影响分析
        self._plot_rate_impact()
        
        print(f"所有图表已保存到: {self.output_dir}")
    
    def _plot_latency_boxplot(self):
        """绘制延迟箱线图：配置规模 × 变更速率"""
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle('配置变更响应延迟箱线图', fontsize=16, fontweight='bold')
        
        methods = self.df['method'].unique()
        
        for i, method in enumerate(methods):
            ax = axes[i]
            method_data = self.df[self.df['method'] == method]
            
            # 创建组合标签
            method_data = method_data.copy()
            method_data['scale_rate'] = method_data['config_scale'] + '_' + method_data['change_rate']
            
            # 绘制箱线图
            sns.boxplot(data=method_data, x='scale_rate', y='total_time', ax=ax)
            ax.set_title(f'{method.replace("_", " ").title()} 方法')
            ax.set_xlabel('配置规模_变更速率')
            ax.set_ylabel('总响应时间 (秒)')
            ax.tick_params(axis='x', rotation=45)
            
            # 添加均值线
            for j, scale_rate in enumerate(method_data['scale_rate'].unique()):
                subset = method_data[method_data['scale_rate'] == scale_rate]
                mean_time = subset['total_time'].mean()
                ax.axhline(y=mean_time, xmin=j/len(method_data['scale_rate'].unique()),
                          xmax=(j+1)/len(method_data['scale_rate'].unique()),
                          color='red', linestyle='--', alpha=0.7)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'latency_boxplot.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_latency_timeline(self):
        """绘制延迟曲线图：首次响应 & 最终确认随时间变化"""
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # 按方法分组
        for method in self.df['method'].unique():
            method_data = self.df[self.df['method'] == method].copy()
            
            # 按时间排序
            method_data['timestamp'] = pd.to_datetime(method_data['timestamp'])
            method_data = method_data.sort_values('timestamp')
            
            # 计算累积统计
            method_data['cumulative_avg'] = method_data['total_time'].expanding().mean()
            method_data['cumulative_std'] = method_data['total_time'].expanding().std()
            
            # 绘制曲线
            ax.plot(method_data.index, method_data['cumulative_avg'], 
                   label=f'{method.replace("_", " ").title()}', linewidth=2)
            
            # 添加置信区间
            upper_bound = method_data['cumulative_avg'] + method_data['cumulative_std']
            lower_bound = method_data['cumulative_avg'] - method_data['cumulative_std']
            ax.fill_between(method_data.index, lower_bound, upper_bound, alpha=0.2)
        
        ax.set_title('响应延迟随时间变化曲线', fontsize=14, fontweight='bold')
        ax.set_xlabel('实验序号')
        ax.set_ylabel('累积平均响应时间 (秒)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'latency_timeline.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_cost_latency_scatter(self):
        """绘制开销-延迟散点图：请求数 vs 检测延迟"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('开销-延迟散点图分析', fontsize=16, fontweight='bold')
        
        # 1. 总时间 vs 实际问题数
        ax1 = axes[0, 0]
        sns.scatterplot(data=self.df, x='actual_issues', y='total_time', 
                       hue='method', style='config_scale', ax=ax1)
        ax1.set_title('检测延迟 vs 发现问题数')
        ax1.set_xlabel('发现问题数')
        ax1.set_ylabel('总响应时间 (秒)')
        
        # 2. 解析时间 vs 总时间
        if 'parsing_time' in self.df.columns:
            ax2 = axes[0, 1]
            parsing_data = self.df.dropna(subset=['parsing_time'])
            sns.scatterplot(data=parsing_data, x='parsing_time', y='total_time',
                           hue='method', ax=ax2)
            ax2.set_title('解析时间 vs 总时间')
            ax2.set_xlabel('解析时间 (秒)')
            ax2.set_ylabel('总响应时间 (秒)')
        
        # 3. 验证时间 vs 总时间
        if 'validation_time' in self.df.columns:
            ax3 = axes[1, 0]
            validation_data = self.df.dropna(subset=['validation_time'])
            sns.scatterplot(data=validation_data, x='validation_time', y='total_time',
                           hue='method', ax=ax3)
            ax3.set_title('验证时间 vs 总时间')
            ax3.set_xlabel('验证时间 (秒)')
            ax3.set_ylabel('总响应时间 (秒)')
        
        # 4. 准确率 vs 响应时间
        ax4 = axes[1, 1]
        sns.scatterplot(data=self.df, x='f1_score', y='total_time',
                       hue='method', size='actual_issues', ax=ax4)
        ax4.set_title('准确率 vs 响应时间')
        ax4.set_xlabel('F1分数')
        ax4.set_ylabel('总响应时间 (秒)')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'cost_latency_scatter.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_accuracy_table(self):
        """绘制精度表格：Precision / Recall / F1 并列展示"""
        # 计算每个方法的平均指标
        accuracy_summary = self.df.groupby('method').agg({
            'precision': ['mean', 'std'],
            'recall': ['mean', 'std'],
            'f1_score': ['mean', 'std']
        }).round(3)
        
        # 创建表格图
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.axis('tight')
        ax.axis('off')
        
        # 准备表格数据
        table_data = []
        methods = accuracy_summary.index.tolist()
        
        for method in methods:
            row = [method.replace('_', ' ').title()]
            
            # Precision
            prec_mean = accuracy_summary.loc[method, ('precision', 'mean')]
            prec_std = accuracy_summary.loc[method, ('precision', 'std')]
            row.append(f"{prec_mean:.3f} ± {prec_std:.3f}")
            
            # Recall
            rec_mean = accuracy_summary.loc[method, ('recall', 'mean')]
            rec_std = accuracy_summary.loc[method, ('recall', 'std')]
            row.append(f"{rec_mean:.3f} ± {rec_std:.3f}")
            
            # F1 Score
            f1_mean = accuracy_summary.loc[method, ('f1_score', 'mean')]
            f1_std = accuracy_summary.loc[method, ('f1_score', 'std')]
            row.append(f"{f1_mean:.3f} ± {f1_std:.3f}")
            
            table_data.append(row)
        
        # 创建表格
        table = ax.table(cellText=table_data,
                        colLabels=['方法', 'Precision', 'Recall', 'F1 Score'],
                        cellLoc='center',
                        loc='center')
        
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        table.scale(1.2, 2)
        
        # 设置表格样式
        for i in range(len(table_data) + 1):
            for j in range(4):
                cell = table[(i, j)]
                if i == 0:  # 标题行
                    cell.set_facecolor('#4CAF50')
                    cell.set_text_props(weight='bold', color='white')
                else:
                    if i % 2 == 0:
                        cell.set_facecolor('#f0f0f0')
                    else:
                        cell.set_facecolor('white')
        
        plt.title('准确性指标对比表', fontsize=16, fontweight='bold', pad=20)
        plt.savefig(self.output_dir / 'accuracy_table.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_performance_radar(self):
        """绘制性能对比雷达图"""
        # 计算每个方法的标准化指标
        metrics = ['precision', 'recall', 'f1_score']
        methods = self.df['method'].unique()
        
        # 计算平均值并标准化到0-1范围
        method_metrics = {}
        for method in methods:
            method_data = self.df[self.df['method'] == method]
            method_metrics[method] = {
                'precision': method_data['precision'].mean(),
                'recall': method_data['recall'].mean(),
                'f1_score': method_data['f1_score'].mean(),
                'speed': 1 / (method_data['total_time'].mean() / 60)  # 转换为每分钟处理次数
            }
        
        # 标准化到0-1
        all_values = []
        for method_data in method_metrics.values():
            all_values.extend(method_data.values())
        
        min_val, max_val = min(all_values), max(all_values)
        
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        
        angles = np.linspace(0, 2 * np.pi, len(metrics) + 1, endpoint=True).tolist()
        
        for method in methods:
            values = []
            for metric in metrics:
                normalized = (method_metrics[method][metric] - min_val) / (max_val - min_val)
                values.append(normalized)
            values += values[:1]  # 闭合图形
            
            ax.plot(angles, values, 'o-', linewidth=2, label=method.replace('_', ' ').title())
            ax.fill(angles, values, alpha=0.25)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([m.replace('_', ' ').title() for m in metrics])
        ax.set_ylim(0, 1)
        ax.set_title('方法性能雷达图', size=16, fontweight='bold', pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
        ax.grid(True)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'performance_radar.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_scale_impact(self):
        """绘制配置规模影响分析"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('配置规模对性能的影响分析', fontsize=16, fontweight='bold')
        
        # 1. 响应时间 vs 配置规模
        ax1 = axes[0, 0]
        sns.boxplot(data=self.df, x='config_scale', y='total_time', hue='method', ax=ax1)
        ax1.set_title('响应时间 vs 配置规模')
        ax1.set_xlabel('配置规模')
        ax1.set_ylabel('总响应时间 (秒)')
        
        # 2. 准确性 vs 配置规模
        ax2 = axes[0, 1]
        sns.boxplot(data=self.df, x='config_scale', y='f1_score', hue='method', ax=ax2)
        ax2.set_title('准确性 vs 配置规模')
        ax2.set_xlabel('配置规模')
        ax2.set_ylabel('F1分数')
        
        # 3. 解析时间 vs 配置规模
        if 'parsing_time' in self.df.columns:
            ax3 = axes[1, 0]
            parsing_data = self.df.dropna(subset=['parsing_time'])
            sns.boxplot(data=parsing_data, x='config_scale', y='parsing_time', hue='method', ax=ax3)
            ax3.set_title('解析时间 vs 配置规模')
            ax3.set_xlabel('配置规模')
            ax3.set_ylabel('解析时间 (秒)')
        
        # 4. 验证时间 vs 配置规模
        if 'validation_time' in self.df.columns:
            ax4 = axes[1, 1]
            validation_data = self.df.dropna(subset=['validation_time'])
            sns.boxplot(data=validation_data, x='config_scale', y='validation_time', hue='method', ax=ax4)
            ax4.set_title('验证时间 vs 配置规模')
            ax4.set_xlabel('配置规模')
            ax4.set_ylabel('验证时间 (秒)')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'scale_impact.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_rate_impact(self):
        """绘制变更速率影响分析"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('变更速率对性能的影响分析', fontsize=16, fontweight='bold')
        
        # 1. 响应时间 vs 变更速率
        ax1 = axes[0, 0]
        sns.boxplot(data=self.df, x='change_rate', y='total_time', hue='method', ax=ax1)
        ax1.set_title('响应时间 vs 变更速率')
        ax1.set_xlabel('变更速率')
        ax1.set_ylabel('总响应时间 (秒)')
        
        # 2. 准确性 vs 变更速率
        ax2 = axes[0, 1]
        sns.boxplot(data=self.df, x='change_rate', y='f1_score', hue='method', ax=ax2)
        ax2.set_title('准确性 vs 变更速率')
        ax2.set_xlabel('变更速率')
        ax2.set_ylabel('F1分数')
        
        # 3. 成功率 vs 变更速率
        success_rate = self.df.groupby(['change_rate', 'method'])['success'].mean().reset_index()
        ax3 = axes[1, 0]
        sns.barplot(data=success_rate, x='change_rate', y='success', hue='method', ax=ax3)
        ax3.set_title('成功率 vs 变更速率')
        ax3.set_xlabel('变更速率')
        ax3.set_ylabel('成功率')
        
        # 4. 性能稳定性分析
        stability_data = self.df.groupby(['change_rate', 'method'])['total_time'].std().reset_index()
        stability_data.rename(columns={'total_time': 'time_std'}, inplace=True)
        ax4 = axes[1, 1]
        sns.barplot(data=stability_data, x='change_rate', y='time_std', hue='method', ax=ax4)
        ax4.set_title('性能稳定性 vs 变更速率')
        ax4.set_xlabel('变更速率')
        ax4.set_ylabel('响应时间标准差 (秒)')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'rate_impact.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def generate_summary_report(self) -> str:
        """生成总结报告"""
        report_lines = []
        report_lines.append("# 实验三结果分析报告")
        report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")
        
        # 基本统计
        total_experiments = len(self.df)
        successful_experiments = self.df['success'].sum()
        success_rate = successful_experiments / total_experiments
        
        report_lines.append("## 基本统计")
        report_lines.append(f"- 总实验数: {total_experiments}")
        report_lines.append(f"- 成功实验数: {successful_experiments}")
        report_lines.append(f"- 成功率: {success_rate:.2%}")
        report_lines.append("")
        
        # 方法对比
        report_lines.append("## 方法对比")
        method_stats = self.df.groupby('method').agg({
            'total_time': ['mean', 'std'],
            'f1_score': ['mean', 'std'],
            'success': 'mean'
        }).round(3)
        
        for method in method_stats.index:
            method_name = method.replace('_', ' ').title()
            avg_time = method_stats.loc[method, ('total_time', 'mean')]
            std_time = method_stats.loc[method, ('total_time', 'std')]
            avg_f1 = method_stats.loc[method, ('f1_score', 'mean')]
            std_f1 = method_stats.loc[method, ('f1_score', 'std')]
            success_rate = method_stats.loc[method, ('success', 'mean')]
            
            report_lines.append(f"### {method_name}")
            report_lines.append(f"- 平均响应时间: {avg_time:.3f} ± {std_time:.3f} 秒")
            report_lines.append(f"- 平均F1分数: {avg_f1:.3f} ± {std_f1:.3f}")
            report_lines.append(f"- 成功率: {success_rate:.2%}")
            report_lines.append("")
        
        # 配置规模影响
        report_lines.append("## 配置规模影响")
        scale_stats = self.df.groupby('config_scale').agg({
            'total_time': 'mean',
            'f1_score': 'mean'
        }).round(3)
        
        for scale in scale_stats.index:
            avg_time = scale_stats.loc[scale, 'total_time']
            avg_f1 = scale_stats.loc[scale, 'f1_score']
            report_lines.append(f"- {scale}规模: 平均响应时间 {avg_time:.3f}s, 平均F1分数 {avg_f1:.3f}")
        
        report_lines.append("")
        
        # 变更速率影响
        report_lines.append("## 变更速率影响")
        rate_stats = self.df.groupby('change_rate').agg({
            'total_time': 'mean',
            'f1_score': 'mean'
        }).round(3)
        
        for rate in rate_stats.index:
            avg_time = rate_stats.loc[rate, 'total_time']
            avg_f1 = rate_stats.loc[rate, 'f1_score']
            report_lines.append(f"- {rate}速率: 平均响应时间 {avg_time:.3f}s, 平均F1分数 {avg_f1:.3f}")
        
        report_lines.append("")
        
        # 建议
        report_lines.append("## 建议")
        best_method = method_stats['total_time']['mean'].idxmin()
        best_accuracy_method = method_stats['f1_score']['mean'].idxmax()
        
        report_lines.append(f"- 最快方法: {best_method.replace('_', ' ').title()}")
        report_lines.append(f"- 最准确方法: {best_accuracy_method.replace('_', ' ').title()}")
        
        if best_method == best_accuracy_method:
            report_lines.append("- 建议采用该方法，它在速度和准确性方面都表现最佳")
        else:
            report_lines.append("- 需要在速度和准确性之间进行权衡")
        
        # 保存报告
        report_file = self.output_dir / 'analysis_report.md'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))
        
        return str(report_file)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="实验结果分析器")
    parser.add_argument("--results", required=True, help="实验结果文件路径")
    parser.add_argument("--output", help="输出目录", default="results/visualizations")
    parser.add_argument("--report-only", action="store_true", help="仅生成报告，不生成图表")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.results):
        print(f"错误: 结果文件不存在: {args.results}")
        return
    
    # 创建分析器
    analyzer = ResultAnalyzer(args.results)
    
    if not args.report_only:
        # 生成所有可视化图表
        analyzer.generate_all_visualizations()
    
    # 生成总结报告
    report_file = analyzer.generate_summary_report()
    
    print(f"分析完成！")
    print(f"报告文件: {report_file}")
    if not args.report_only:
        print(f"图表目录: {analyzer.output_dir}")


if __name__ == "__main__":
    main()
