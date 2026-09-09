#!/usr/bin/env python3
"""
可视化图表生成器 - 生成实验四的各种分析图表
"""

import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
import warnings

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 忽略警告
warnings.filterwarnings('ignore')


class PlotGenerator:
    """可视化图表生成器"""
    
    def __init__(self, results_dir: str = "results"):
        """初始化图表生成器"""
        self.results_dir = Path(results_dir)
        self.viz_dir = self.results_dir / "visualizations"
        self.viz_dir.mkdir(exist_ok=True)
        
        # 设置样式
        sns.set_style("whitegrid")
        plt.style.use('seaborn-v0_8')
    
    def plot_coverage_vs_test_cases(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制覆盖率 vs 测试用例数量对比图"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        methods = []
        test_case_counts = []
        coverage_percentages = []
        
        # 提取数据
        for method_data in data.get("coverage_results", []):
            methods.append(method_data.get("method", "unknown"))
            coverage_percentages.append(method_data.get("coverage_percentage", 0))
        
        for method_data in data.get("generation_results", {}).values():
            methods.append(method_data.get("method", "unknown"))
            test_case_counts.append(len(method_data.get("test_cases", [])))
        
        # 确保数据对齐
        min_len = min(len(methods), len(test_case_counts), len(coverage_percentages))
        methods = methods[:min_len]
        test_case_counts = test_case_counts[:min_len]
        coverage_percentages = coverage_percentages[:min_len]
        
        # 子图1：覆盖率对比
        bars1 = ax1.bar(methods, coverage_percentages, 
                       color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57'])
        ax1.set_title('各方法覆盖率对比', fontsize=14, fontweight='bold')
        ax1.set_ylabel('覆盖率 (%)', fontsize=12)
        ax1.set_ylim(0, 100)
        
        # 添加数值标签
        for bar, value in zip(bars1, coverage_percentages):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{value:.1f}%', ha='center', va='bottom', fontweight='bold')
        
        # 子图2：测试用例数量对比
        bars2 = ax2.bar(methods, test_case_counts,
                       color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57'])
        ax2.set_title('各方法测试用例数量对比', fontsize=14, fontweight='bold')
        ax2.set_ylabel('测试用例数量', fontsize=12)
        
        # 添加数值标签
        for bar, value in zip(bars2, test_case_counts):
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(test_case_counts)*0.01,
                    f'{value}', ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'coverage_vs_test_cases.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_test_case_counts_bar(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制测试用例数量柱状图"""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        methods = []
        counts = []
        
        for method, method_data in data.get("generation_results", {}).items():
            methods.append(method.upper())
            counts.append(len(method_data.get("test_cases", [])))
        
        # 创建柱状图
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57']
        bars = ax.bar(methods, counts, color=colors[:len(methods)])
        
        ax.set_title('测试用例生成数量对比', fontsize=16, fontweight='bold', pad=20)
        ax.set_ylabel('测试用例数量', fontsize=12)
        ax.set_xlabel('测试方法', fontsize=12)
        
        # 添加数值标签
        for bar, count in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(counts)*0.01,
                   f'{count}', ha='center', va='bottom', fontweight='bold', fontsize=11)
        
        # 添加网格
        ax.grid(True, alpha=0.3, axis='y')
        ax.set_axisbelow(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'test_case_counts_bar.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_cost_coverage_efficiency_scatter(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制成本-覆盖率效率散点图"""
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # 提取效率数据
        efficiency_data = data.get("cost_efficiency_analysis", {}).get("efficiency_results", [])
        cost_data = data.get("cost_efficiency_analysis", {}).get("cost_results", [])
        
        methods = []
        coverage_values = []
        time_values = []
        efficiency_scores = []
        
        for eff_result in efficiency_data:
            methods.append(eff_result.get("method", "unknown"))
            coverage_values.append(eff_result.get("coverage_achieved", 0))
            time_values.append(eff_result.get("total_time", 0))
            efficiency_scores.append(eff_result.get("efficiency_score", 0))
        
        # 创建散点图
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57']
        sizes = [score * 1000 for score in efficiency_scores]  # 用效率分数调整点的大小
        
        scatter = ax.scatter(time_values, coverage_values, s=sizes, c=colors[:len(methods)], 
                           alpha=0.7, edgecolors='black', linewidth=1)
        
        # 添加方法标签
        for i, method in enumerate(methods):
            ax.annotate(method.upper(), (time_values[i], coverage_values[i]),
                       xytext=(5, 5), textcoords='offset points',
                       fontsize=10, fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
        
        ax.set_xlabel('执行时间 (秒)', fontsize=12)
        ax.set_ylabel('覆盖率 (%)', fontsize=12)
        ax.set_title('成本-覆盖率效率分析\n(点的大小表示效率分数)', fontsize=14, fontweight='bold')
        
        # 添加网格
        ax.grid(True, alpha=0.3)
        
        # 添加效率分数图例
        legend_elements = []
        for i, method in enumerate(methods):
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=colors[i], markersize=8,
                                            label=f'{method.upper()}: {efficiency_scores[i]:.3f}'))
        
        ax.legend(handles=legend_elements, title='效率分数', loc='lower right')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'cost_coverage_efficiency_scatter.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_execution_time_boxplot(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制执行时间箱线图"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # 准备数据
        methods = []
        generation_times = []
        execution_times = []
        
        for method, method_data in data.get("generation_results", {}).items():
            methods.append(method.upper())
            generation_times.append(method_data.get("generation_time", 0))
            execution_times.append(method_data.get("execution_time", 0))
        
        # 子图1：生成时间
        ax1.bar(methods, generation_times, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax1.set_title('测试用例生成时间', fontsize=14, fontweight='bold')
        ax1.set_ylabel('时间 (秒)', fontsize=12)
        ax1.grid(True, alpha=0.3, axis='y')
        
        # 添加数值标签
        for i, time_val in enumerate(generation_times):
            ax1.text(i, time_val + max(generation_times)*0.01, f'{time_val:.2f}s',
                    ha='center', va='bottom', fontweight='bold')
        
        # 子图2：执行时间
        ax2.bar(methods, execution_times, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax2.set_title('测试用例执行时间', fontsize=14, fontweight='bold')
        ax2.set_ylabel('时间 (秒)', fontsize=12)
        ax2.grid(True, alpha=0.3, axis='y')
        
        # 添加数值标签
        for i, time_val in enumerate(execution_times):
            ax2.text(i, time_val + max(execution_times)*0.01, f'{time_val:.2f}s',
                    ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'execution_time_boxplot.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_coverage_comparison_radar(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制覆盖率对比雷达图"""
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        
        # 准备数据
        methods = []
        coverage_data = []
        
        for coverage_result in data.get("coverage_results", []):
            methods.append(coverage_result.get("method", "unknown"))
            coverage_data.append(coverage_result.get("coverage_percentage", 0))
        
        # 雷达图参数
        angles = np.linspace(0, 2 * np.pi, len(methods), endpoint=False).tolist()
        coverage_data += coverage_data[:1]  # 闭合图形
        angles += angles[:1]
        
        # 绘制雷达图
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57']
        ax.plot(angles, coverage_data, 'o-', linewidth=2, 
               color=colors[0], label='Coverage Comparison')
        ax.fill(angles, coverage_data, alpha=0.25, color=colors[0])
        
        # 设置标签
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([method.upper() for method in methods])
        ax.set_ylim(0, 100)
        ax.set_title('各方法覆盖率对比雷达图', fontsize=16, fontweight='bold', pad=30)
        
        # 添加数值标签
        for angle, coverage, method in zip(angles[:-1], coverage_data[:-1], methods):
            ax.text(angle, coverage + 5, f'{coverage:.1f}%', 
                   ha='center', va='center', fontweight='bold')
        
        # 添加网格
        ax.grid(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'coverage_comparison_radar.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_efficiency_ranking(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制效率排名图"""
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # 提取效率数据
        efficiency_data = data.get("cost_efficiency_analysis", {}).get("efficiency_results", [])
        
        # 按效率分数排序
        sorted_data = sorted(efficiency_data, key=lambda x: x.get("efficiency_score", 0), reverse=True)
        
        methods = [item.get("method", "unknown").upper() for item in sorted_data]
        efficiency_scores = [item.get("efficiency_score", 0) for item in sorted_data]
        coverage_values = [item.get("coverage_achieved", 0) for item in sorted_data]
        time_values = [item.get("total_time", 0) for item in sorted_data]
        
        # 创建水平条形图
        y_pos = np.arange(len(methods))
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57']
        
        bars = ax.barh(y_pos, efficiency_scores, color=colors[:len(methods)])
        
        # 设置标签
        ax.set_yticks(y_pos)
        ax.set_yticklabels(methods)
        ax.set_xlabel('效率分数', fontsize=12)
        ax.set_title('测试方法效率排名', fontsize=16, fontweight='bold', pad=20)
        
        # 添加数值标签
        for i, (bar, score, coverage, time_val) in enumerate(zip(bars, efficiency_scores, coverage_values, time_values)):
            ax.text(bar.get_width() + max(efficiency_scores)*0.01, bar.get_y() + bar.get_height()/2,
                   f'{score:.3f}\n({coverage:.1f}%, {time_val:.1f}s)', 
                   ha='left', va='center', fontweight='bold')
        
        # 添加排名标签
        for i, (method, score) in enumerate(zip(methods, efficiency_scores)):
            ax.text(-max(efficiency_scores)*0.1, i, f'#{i+1}', 
                   ha='center', va='center', fontweight='bold', fontsize=14,
                   bbox=dict(boxstyle='circle', facecolor='gold', alpha=0.8))
        
        ax.grid(True, alpha=0.3, axis='x')
        ax.set_axisbelow(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'efficiency_ranking.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def plot_comprehensive_comparison(self, data: Dict[str, Any], save_path: Optional[str] = None):
        """绘制综合对比图"""
        fig = plt.figure(figsize=(20, 12))
        
        # 创建网格布局
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
        
        # 子图1：覆盖率对比
        ax1 = fig.add_subplot(gs[0, 0])
        coverage_results = data.get("coverage_results", [])
        methods = [r.get("method", "unknown") for r in coverage_results]
        coverages = [r.get("coverage_percentage", 0) for r in coverage_results]
        ax1.bar(methods, coverages, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax1.set_title('覆盖率对比', fontweight='bold')
        ax1.set_ylabel('覆盖率 (%)')
        ax1.grid(True, alpha=0.3)
        
        # 子图2：测试用例数量
        ax2 = fig.add_subplot(gs[0, 1])
        generation_results = data.get("generation_results", {})
        methods = list(generation_results.keys())
        counts = [len(r.get("test_cases", [])) for r in generation_results.values()]
        ax2.bar(methods, counts, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax2.set_title('测试用例数量', fontweight='bold')
        ax2.set_ylabel('数量')
        ax2.grid(True, alpha=0.3)
        
        # 子图3：执行时间
        ax3 = fig.add_subplot(gs[0, 2])
        execution_times = [r.get("execution_time", 0) for r in generation_results.values()]
        ax3.bar(methods, execution_times, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax3.set_title('执行时间', fontweight='bold')
        ax3.set_ylabel('时间 (秒)')
        ax3.grid(True, alpha=0.3)
        
        # 子图4：效率分数
        ax4 = fig.add_subplot(gs[1, :2])
        efficiency_results = data.get("cost_efficiency_analysis", {}).get("efficiency_results", [])
        eff_methods = [r.get("method", "unknown") for r in efficiency_results]
        eff_scores = [r.get("efficiency_score", 0) for r in efficiency_results]
        ax4.bar(eff_methods, eff_scores, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4'])
        ax4.set_title('效率分数对比', fontweight='bold')
        ax4.set_ylabel('效率分数')
        ax4.grid(True, alpha=0.3)
        
        # 子图5：成本-覆盖率散点图
        ax5 = fig.add_subplot(gs[1, 2])
        if efficiency_results:
            coverages = [r.get("coverage_achieved", 0) for r in efficiency_results]
            times = [r.get("total_time", 0) for r in efficiency_results]
            ax5.scatter(times, coverages, s=100, alpha=0.7)
            for i, method in enumerate(eff_methods):
                ax5.annotate(method, (times[i], coverages[i]), xytext=(5, 5), textcoords='offset points')
            ax5.set_xlabel('总时间 (秒)')
            ax5.set_ylabel('覆盖率 (%)')
            ax5.set_title('成本-覆盖率', fontweight='bold')
            ax5.grid(True, alpha=0.3)
        
        # 子图6：方法对比雷达图
        ax6 = fig.add_subplot(gs[2, :], projection='polar')
        if coverage_results:
            angles = np.linspace(0, 2 * np.pi, len(coverage_results), endpoint=False).tolist()
            coverage_data = [r.get("coverage_percentage", 0) for r in coverage_results]
            coverage_data += coverage_data[:1]
            angles += angles[:1]
            
            ax6.plot(angles, coverage_data, 'o-', linewidth=2)
            ax6.fill(angles, coverage_data, alpha=0.25)
            ax6.set_xticks(angles[:-1])
            ax6.set_xticklabels([r.get("method", "unknown").upper() for r in coverage_results])
            ax6.set_title('方法综合对比雷达图', fontweight='bold', pad=30)
            ax6.grid(True)
        
        plt.suptitle('实验四：效率评估综合对比分析', fontsize=20, fontweight='bold', y=0.98)
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.savefig(self.viz_dir / 'comprehensive_comparison.png', dpi=300, bbox_inches='tight')
        
        plt.close()
    
    def generate_all_visualizations(self, data_file: str):
        """生成所有可视化图表"""
        print("开始生成可视化图表...")
        
        # 加载数据
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 生成各种图表
        visualizations = [
            ("覆盖率 vs 测试用例数量对比图", self.plot_coverage_vs_test_cases),
            ("测试用例数量柱状图", self.plot_test_case_counts_bar),
            ("成本-覆盖率效率散点图", self.plot_cost_coverage_efficiency_scatter),
            ("执行时间箱线图", self.plot_execution_time_boxplot),
            ("覆盖率对比雷达图", self.plot_coverage_comparison_radar),
            ("效率排名图", self.plot_efficiency_ranking),
            ("综合对比图", self.plot_comprehensive_comparison)
        ]
        
        for name, plot_func in visualizations:
            try:
                print(f"  生成 {name}...")
                plot_func(data)
                print(f"    ✓ 完成")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
        
        print(f"可视化图表生成完成，保存位置: {self.viz_dir}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="实验四可视化图表生成器")
    parser.add_argument("--data", required=True, help="实验数据JSON文件路径")
    parser.add_argument("--output", help="输出目录路径")
    
    args = parser.parse_args()
    
    # 检查数据文件
    if not Path(args.data).exists():
        print(f"错误: 数据文件不存在: {args.data}")
        return
    
    # 创建图表生成器
    output_dir = args.output if args.output else "results"
    plotter = PlotGenerator(output_dir)
    
    # 生成所有可视化图表
    plotter.generate_all_visualizations(args.data)


if __name__ == "__main__":
    main()
