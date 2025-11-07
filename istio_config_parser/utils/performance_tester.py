"""
性能测试工具类
用于测试并行处理的CPU占用、内存使用和时延数据
"""
import time
import psutil
import threading
import statistics
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    execution_time: float  # 执行时间（秒）
    cpu_percent_avg: float  # 平均CPU使用率
    cpu_percent_max: float  # 最大CPU使用率
    memory_mb_avg: float  # 平均内存使用（MB）
    memory_mb_max: float  # 最大内存使用（MB）
    thread_count_avg: int  # 平均线程数
    thread_count_max: int  # 最大线程数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'execution_time_seconds': round(self.execution_time, 3),
            'cpu_percent_avg': round(self.cpu_percent_avg, 2),
            'cpu_percent_max': round(self.cpu_percent_max, 2),
            'memory_mb_avg': round(self.memory_mb_avg, 2),
            'memory_mb_max': round(self.memory_mb_max, 2),
            'thread_count_avg': self.thread_count_avg,
            'thread_count_max': self.thread_count_max
        }


class SystemMonitor:
    """系统监控类，用于监控CPU、内存和线程使用情况"""
    
    def __init__(self, sampling_interval: float = 0.1):
        """
        初始化系统监控器
        
        Args:
            sampling_interval: 采样间隔（秒）
        """
        self.sampling_interval = sampling_interval
        self.monitoring = False
        self.metrics_data: List[Dict[str, float]] = []
        self.monitor_thread: Optional[threading.Thread] = None
        self.process = psutil.Process()
    
    def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.metrics_data.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.debug("系统监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)
        
        logger.debug(f"系统监控已停止，收集到 {len(self.metrics_data)} 个数据点")
    
    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                # 获取CPU使用率
                cpu_percent = self.process.cpu_percent()
                
                # 获取内存使用情况
                memory_info = self.process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024  # 转换为MB
                
                # 获取线程数
                thread_count = threading.active_count()
                
                # 记录数据
                metrics = {
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb,
                    'thread_count': thread_count
                }
                
                self.metrics_data.append(metrics)
                time.sleep(self.sampling_interval)
                
            except Exception as e:
                logger.error(f"监控循环出错: {e}")
                break
    
    def get_summary(self) -> Dict[str, float]:
        """获取监控摘要"""
        if not self.metrics_data:
            return {
                'cpu_percent_avg': 0.0,
                'cpu_percent_max': 0.0,
                'memory_mb_avg': 0.0,
                'memory_mb_max': 0.0,
                'thread_count_avg': 0,
                'thread_count_max': 0
            }
        
        # 计算统计数据
        cpu_values = [m['cpu_percent'] for m in self.metrics_data]
        memory_values = [m['memory_mb'] for m in self.metrics_data]
        thread_values = [m['thread_count'] for m in self.metrics_data]
        
        return {
            'cpu_percent_avg': statistics.mean(cpu_values),
            'cpu_percent_max': max(cpu_values),
            'memory_mb_avg': statistics.mean(memory_values),
            'memory_mb_max': max(memory_values),
            'thread_count_avg': int(statistics.mean(thread_values)),
            'thread_count_max': max(thread_values)
        }


class PerformanceTester:
    """性能测试器"""
    
    def __init__(self, sampling_interval: float = 0.1):
        """
        初始化性能测试器
        
        Args:
            sampling_interval: 监控采样间隔（秒）
        """
        self.sampling_interval = sampling_interval
        self.results: List[Tuple[str, PerformanceMetrics]] = []
    
    @contextmanager
    def measure_performance(self, test_name: str = "test"):
        """
        性能测试上下文管理器
        
        Args:
            test_name: 测试名称
            
        Yields:
            PerformanceMetrics: 性能指标对象
        """
        monitor = SystemMonitor(self.sampling_interval)
        
        # 开始监控
        monitor.start_monitoring()
        start_time = time.time()
        
        try:
            yield monitor
        finally:
            # 停止监控并计算指标
            end_time = time.time()
            monitor.stop_monitoring()
            
            execution_time = end_time - start_time
            summary = monitor.get_summary()
            
            metrics = PerformanceMetrics(
                execution_time=execution_time,
                cpu_percent_avg=summary['cpu_percent_avg'],
                cpu_percent_max=summary['cpu_percent_max'],
                memory_mb_avg=summary['memory_mb_avg'],
                memory_mb_max=summary['memory_mb_max'],
                thread_count_avg=summary['thread_count_avg'],
                thread_count_max=summary['thread_count_max']
            )
            
            self.results.append((test_name, metrics))
            
            logger.info(f"性能测试 '{test_name}' 完成:")
            logger.info(f"  执行时间: {execution_time:.3f} 秒")
            logger.info(f"  CPU使用率 - 平均: {summary['cpu_percent_avg']:.2f}%, 最大: {summary['cpu_percent_max']:.2f}%")
            logger.info(f"  内存使用 - 平均: {summary['memory_mb_avg']:.2f} MB, 最大: {summary['memory_mb_max']:.2f} MB")
            logger.info(f"  线程数 - 平均: {summary['thread_count_avg']}, 最大: {summary['thread_count_max']}")
    
    def run_comparison_test(
        self,
        test_func: Callable[[], Any],
        serial_func: Optional[Callable[[], Any]] = None,
        parallel_func: Optional[Callable[[], Any]] = None,
        test_name: str = "comparison"
    ) -> Dict[str, PerformanceMetrics]:
        """
        运行对比测试
        
        Args:
            test_func: 测试函数
            serial_func: 串行版本测试函数（可选）
            parallel_func: 并行版本测试函数（可选）
            test_name: 测试名称
            
        Returns:
            测试结果字典
        """
        results = {}
        
        if serial_func:
            with self.measure_performance(f"{test_name}_serial") as monitor:
                serial_func()
            results['serial'] = self.results[-1][1]
        
        if parallel_func:
            with self.measure_performance(f"{test_name}_parallel") as monitor:
                parallel_func()
            results['parallel'] = self.results[-1][1]
        
        if not serial_func and not parallel_func:
            with self.measure_performance(test_name) as monitor:
                test_func()
            results['default'] = self.results[-1][1]
        
        return results
    
    def get_comparison_report(self, results: Dict[str, PerformanceMetrics]) -> str:
        """
        生成对比报告
        
        Args:
            results: 测试结果字典
            
        Returns:
            格式化的对比报告
        """
        if not results:
            return "没有测试结果"
        
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("性能测试对比报告")
        report_lines.append("=" * 80)
        
        for mode, metrics in results.items():
            report_lines.append(f"\n【{mode.upper()} 模式】")
            report_lines.append("-" * 40)
            report_lines.append(f"执行时间:     {metrics.execution_time:.3f} 秒")
            report_lines.append(f"CPU使用率:    平均 {metrics.cpu_percent_avg:.2f}%, 最大 {metrics.cpu_percent_max:.2f}%")
            report_lines.append(f"内存使用:     平均 {metrics.memory_mb_avg:.2f} MB, 最大 {metrics.memory_mb_max:.2f} MB")
            report_lines.append(f"线程数:       平均 {metrics.thread_count_avg}, 最大 {metrics.thread_count_max}")
        
        # 计算性能提升
        if 'serial' in results and 'parallel' in results:
            serial = results['serial']
            parallel = results['parallel']
            
            time_improvement = ((serial.execution_time - parallel.execution_time) / serial.execution_time) * 100
            cpu_change = parallel.cpu_percent_avg - serial.cpu_percent_avg
            memory_change = parallel.memory_mb_avg - serial.memory_mb_avg
            
            report_lines.append("\n【性能对比分析】")
            report_lines.append("-" * 40)
            report_lines.append(f"时间提升:     {time_improvement:+.1f}% ({'提升' if time_improvement > 0 else '降低'})")
            report_lines.append(f"CPU变化:      {cpu_change:+.2f}个百分点")
            report_lines.append(f"内存变化:     {memory_change:+.2f} MB")
            
            if time_improvement > 0:
                speedup = serial.execution_time / parallel.execution_time
                report_lines.append(f"加速比:       {speedup:.2f}x")
        
        report_lines.append("\n" + "=" * 80)
        
        return "\n".join(report_lines)
    
    def save_results_to_file(self, filepath: str):
        """
        保存结果到文件
        
        Args:
            filepath: 文件路径
        """
        import json
        
        data = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': []
        }
        
        for test_name, metrics in self.results:
            data['results'].append({
                'test_name': test_name,
                'metrics': metrics.to_dict()
            })
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"性能测试结果已保存到: {filepath}")
    
    def clear_results(self):
        """清除测试结果"""
        self.results.clear()


def create_performance_test_function(
    control_plane_dir: str,
    data_plane_dir: str,
    namespace: Optional[str] = None,
    enable_parallel: bool = True,
    max_workers: Optional[int] = None,
    export_mode: bool = False,
    output_dir: Optional[str] = None
) -> Callable[[], Any]:
    """
    创建性能测试函数
    
    Args:
        control_plane_dir: 控制平面目录
        data_plane_dir: 数据平面目录
        namespace: 命名空间
        enable_parallel: 是否启用并行
        max_workers: 最大工作线程数
        export_mode: 是否导出模式
        output_dir: 输出目录
        
    Returns:
        测试函数
    """
    def test_function():
        from istio_config_parser.main_parser import parse_unified_from_dir, parse_and_export_models
        
        if export_mode:
            parse_and_export_models(
                control_plane_dir=control_plane_dir,
                data_plane_dir=data_plane_dir,
                output_dir=output_dir or 'performance_test_output',
                namespace=namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
        else:
            parse_unified_from_dir(
                control_plane_dir=control_plane_dir,
                data_plane_dir=data_plane_dir,
                namespace=namespace,
                enable_parallel=enable_parallel,
                max_workers=max_workers
            )
    
    return test_function


def run_parallel_vs_serial_comparison(
    control_plane_dir: str = 'istio_monitor/istio_control_config',
    data_plane_dir: str = 'istio_monitor/istio_sidecar_config',
    namespace: Optional[str] = None,
    max_workers: int = 4,
    export_mode: bool = False,
    output_dir: Optional[str] = None,
    sampling_interval: float = 0.1
) -> Dict[str, PerformanceMetrics]:
    """
    运行并行vs串行对比测试
    
    Args:
        control_plane_dir: 控制平面目录
        data_plane_dir: 数据平面目录
        namespace: 命名空间
        max_workers: 最大工作线程数
        export_mode: 是否导出模式
        output_dir: 输出目录
        sampling_interval: 采样间隔
        
    Returns:
        测试结果
    """
    tester = PerformanceTester(sampling_interval=sampling_interval)
    
    # 创建测试函数
    serial_func = create_performance_test_function(
        control_plane_dir, data_plane_dir, namespace,
        enable_parallel=False, max_workers=None,
        export_mode=export_mode, output_dir=output_dir
    )
    
    parallel_func = create_performance_test_function(
        control_plane_dir, data_plane_dir, namespace,
        enable_parallel=True, max_workers=max_workers,
        export_mode=export_mode, output_dir=output_dir
    )
    
    # 运行对比测试
    results = tester.run_comparison_test(
        test_func=serial_func,  # 不会被使用，但需要提供
        serial_func=serial_func,
        parallel_func=parallel_func,
        test_name="parallel_vs_serial"
    )
    
    # 生成报告
    report = tester.get_comparison_report(results)
    print(report)
    
    return results


if __name__ == "__main__":
    # 示例用法
    logging.basicConfig(level=logging.INFO)
    
    # 运行对比测试
    results = run_parallel_vs_serial_comparison(
        namespace='online-boutique',
        max_workers=4,
        export_mode=False
    )
    
    # 保存结果
    tester = PerformanceTester()
    tester.save_results_to_file('performance_test_results.json')
