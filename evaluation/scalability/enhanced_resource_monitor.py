#!/usr/bin/env python3
"""
增强版系统资源监控器
监控整个系统资源，包括子进程、网络IO等
"""

import time
import threading
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import statistics

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class EnhancedSystemMetrics:
    """增强的系统指标数据类"""
    timestamp: float
    # CPU指标
    cpu_percent: float  # CPU使用率（%）
    cpu_per_core: List[float]  # 每个核心的CPU使用率
    # 内存指标
    memory_percent: float  # 内存使用率（%）
    memory_used_mb: float  # 已使用内存（MB）
    memory_total_mb: float  # 总内存（MB）
    memory_available_mb: float  # 可用内存（MB）
    # 进程指标
    process_count: int  # 进程总数
    python_process_count: int  # Python进程数
    python_process_memory_mb: float  # Python进程总内存（MB）
    # 网络指标（必须在有默认值的字段之前）
    network_bytes_sent: int  # 网络发送字节数
    network_bytes_recv: int  # 网络接收字节数
    # 磁盘指标（必须在有默认值的字段之前）
    disk_read_bytes: int  # 磁盘读取字节数
    disk_write_bytes: int  # 磁盘写入字节数
    # 进程树指标（有默认值，放在最后）
    process_tree_count: int = 0  # 进程树总进程数（包括子进程）
    process_tree_memory_mb: float = 0.0  # 进程树总内存（MB）
    process_tree_cpu_percent: float = 0.0  # 进程树总CPU使用率（%）
    network_connections: int = 0  # 网络连接数
    # 系统负载
    load_avg: Optional[float] = None  # 系统负载（Linux）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'cpu_percent': round(self.cpu_percent, 2),
            'cpu_per_core': [round(c, 2) for c in self.cpu_per_core],
            'memory_percent': round(self.memory_percent, 2),
            'memory_used_mb': round(self.memory_used_mb, 2),
            'memory_total_mb': round(self.memory_total_mb, 2),
            'memory_available_mb': round(self.memory_available_mb, 2),
            'process_count': self.process_count,
            'python_process_count': self.python_process_count,
            'python_process_memory_mb': round(self.python_process_memory_mb, 2),
            'process_tree_count': self.process_tree_count,
            'process_tree_memory_mb': round(self.process_tree_memory_mb, 2),
            'process_tree_cpu_percent': round(self.process_tree_cpu_percent, 2),
            'network_bytes_sent': self.network_bytes_sent,
            'network_bytes_recv': self.network_bytes_recv,
            'network_connections': self.network_connections,
            'disk_read_bytes': self.disk_read_bytes,
            'disk_write_bytes': self.disk_write_bytes,
            'load_avg': round(self.load_avg, 2) if self.load_avg else None
        }


class EnhancedSystemResourceMonitor:
    """增强版系统资源监控器 - 监控整个系统资源，包括子进程"""
    
    def __init__(self, sampling_interval: float = 0.1):
        """
        初始化增强版系统资源监控器
        
        Args:
            sampling_interval: 采样间隔（秒）
        """
        self.sampling_interval = sampling_interval
        self.monitoring = False
        self.metrics_data: List[EnhancedSystemMetrics] = []
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 初始网络和磁盘IO计数（用于计算增量）
        self.initial_network = None
        self.initial_disk = None
        
        # 主进程（用于监控子进程）
        self.main_process = None
        if PSUTIL_AVAILABLE:
            try:
                self.main_process = psutil.Process()
            except Exception as e:
                logger.warning(f"无法获取主进程: {e}")
        
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil未安装，无法监控系统资源")
    
    def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            return
        
        if not PSUTIL_AVAILABLE:
            logger.error("psutil未安装，无法启动监控")
            return
        
        self.monitoring = True
        self.metrics_data.clear()
        
        # 记录初始网络和磁盘IO
        try:
            self.initial_network = psutil.net_io_counters()
            self.initial_disk = psutil.disk_io_counters()
        except Exception as e:
            logger.warning(f"无法获取初始IO统计: {e}")
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info("增强版系统资源监控已启动（监控整个系统+子进程）")
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        
        data_points = len(self.metrics_data)
        logger.info(f"增强版系统资源监控已停止，收集到 {data_points} 个数据点")
        if data_points > 0:
            cpu_values = [m.cpu_percent for m in self.metrics_data]
            memory_values = [m.memory_percent for m in self.metrics_data]
            logger.debug(f"  CPU范围: {min(cpu_values):.2f}% - {max(cpu_values):.2f}%")
            logger.debug(f"  内存范围: {min(memory_values):.2f}% - {max(memory_values):.2f}%")
    
    def _get_python_processes_memory(self) -> tuple[int, float]:
        """获取所有Python进程的数量和总内存使用（包括子进程）"""
        python_count = 0
        total_memory_mb = 0.0
        
        try:
            # 获取主进程及其所有子进程
            if self.main_process:
                try:
                    # 获取进程树（包括所有子进程）
                    children = self.main_process.children(recursive=True)
                    all_processes = [self.main_process] + children
                    
                    for proc in all_processes:
                        try:
                            pinfo = proc.as_dict(['name', 'memory_info'])
                            if pinfo.get('name') and 'python' in pinfo['name'].lower():
                                python_count += 1
                                if pinfo.get('memory_info'):
                                    total_memory_mb += pinfo['memory_info'].rss / 1024 / 1024
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except Exception as e:
                    logger.debug(f"获取进程树失败: {e}")
                    # 回退到简单方法
                    pass
            
            # 如果进程树方法失败，使用全局扫描
            if python_count == 0:
                for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                    try:
                        pinfo = proc.info
                        if pinfo['name'] and 'python' in pinfo['name'].lower():
                            python_count += 1
                            if pinfo['memory_info']:
                                total_memory_mb += pinfo['memory_info'].rss / 1024 / 1024
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception as e:
            logger.debug(f"获取Python进程信息失败: {e}")
        
        return python_count, total_memory_mb
    
    def _get_process_tree_stats(self) -> Dict[str, Any]:
        """获取进程树统计信息（包括所有子进程）"""
        stats = {
            'total_processes': 0,
            'child_processes': 0,
            'total_memory_mb': 0.0,
            'total_cpu_percent': 0.0
        }
        
        if not self.main_process:
            return stats
        
        try:
            # 获取所有子进程（递归）
            children = self.main_process.children(recursive=True)
            stats['child_processes'] = len(children)
            stats['total_processes'] = 1 + len(children)  # 主进程 + 子进程
            
            # 计算总内存和CPU
            try:
                main_mem = self.main_process.memory_info().rss / 1024 / 1024
                main_cpu = self.main_process.cpu_percent(interval=0.0)
                stats['total_memory_mb'] += main_mem
                stats['total_cpu_percent'] += main_cpu
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            for child in children:
                try:
                    child_mem = child.memory_info().rss / 1024 / 1024
                    child_cpu = child.cpu_percent(interval=0.0)
                    stats['total_memory_mb'] += child_mem
                    stats['total_cpu_percent'] += child_cpu
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.debug(f"获取进程树统计失败: {e}")
        
        return stats
    
    def _get_metrics(self) -> Optional[EnhancedSystemMetrics]:
        """获取增强的系统指标"""
        try:
            # CPU使用率（整个系统）
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
            
            # 内存使用情况（整个系统）
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_mb = memory.used / (1024 * 1024)
            memory_total_mb = memory.total / (1024 * 1024)
            memory_available_mb = memory.available / (1024 * 1024)
            
            # 进程统计
            process_count = len(psutil.pids())
            python_count, python_memory_mb = self._get_python_processes_memory()
            
            # 进程树统计（包括所有子进程）
            process_tree_stats = self._get_process_tree_stats()
            process_tree_count = process_tree_stats.get('total_processes', 0)
            process_tree_memory_mb = process_tree_stats.get('total_memory_mb', 0.0)
            process_tree_cpu_percent = process_tree_stats.get('total_cpu_percent', 0.0)
            
            # 网络IO（增量）
            network_bytes_sent = 0
            network_bytes_recv = 0
            network_connections = 0
            try:
                network = psutil.net_io_counters()
                if self.initial_network:
                    network_bytes_sent = network.bytes_sent - self.initial_network.bytes_sent
                    network_bytes_recv = network.bytes_recv - self.initial_network.bytes_recv
                
                # 获取网络连接数（包括Kubernetes API调用等）
                try:
                    if self.main_process:
                        connections = self.main_process.connections()
                        network_connections = len(connections)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 尝试获取系统级连接数
                    try:
                        connections = psutil.net_connections()
                        network_connections = len([c for c in connections if c.status == 'ESTABLISHED'])
                    except (psutil.AccessDenied, AttributeError):
                        pass
            except Exception as e:
                logger.debug(f"获取网络IO失败: {e}")
            
            # 磁盘IO（增量）
            disk_read_bytes = 0
            disk_write_bytes = 0
            try:
                disk = psutil.disk_io_counters()
                if disk and self.initial_disk:
                    disk_read_bytes = disk.read_bytes - self.initial_disk.read_bytes
                    disk_write_bytes = disk.write_bytes - self.initial_disk.write_bytes
            except Exception as e:
                logger.debug(f"获取磁盘IO失败: {e}")
            
            # 系统负载（Linux）
            try:
                load_avg = psutil.getloadavg()[0]  # 1分钟平均负载
            except (AttributeError, OSError):
                load_avg = None  # Windows不支持getloadavg
            
            return EnhancedSystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                cpu_per_core=cpu_per_core,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                memory_available_mb=memory_available_mb,
                process_count=process_count,
                python_process_count=python_count,
                python_process_memory_mb=python_memory_mb,
                network_bytes_sent=network_bytes_sent,
                network_bytes_recv=network_bytes_recv,
                disk_read_bytes=disk_read_bytes,
                disk_write_bytes=disk_write_bytes,
                process_tree_count=process_tree_count,
                process_tree_memory_mb=process_tree_memory_mb,
                process_tree_cpu_percent=process_tree_cpu_percent,
                network_connections=network_connections,
                load_avg=load_avg
            )
        except Exception as e:
            logger.error(f"获取增强系统指标失败: {e}")
            return None
    
    def _monitor_loop(self):
        """监控循环"""
        # 初始延迟，确保第一次采样准确
        time.sleep(0.1)
        
        while self.monitoring:
            try:
                metrics = self._get_metrics()
                if metrics:
                    self.metrics_data.append(metrics)
                
                time.sleep(self.sampling_interval)
            except Exception as e:
                logger.error(f"监控循环出错: {e}")
                time.sleep(self.sampling_interval)
    
    def get_summary(self) -> Dict[str, float]:
        """获取监控摘要"""
        if not self.metrics_data:
            return {
                'cpu_percent_avg': 0.0,
                'cpu_percent_max': 0.0,
                'memory_percent_avg': 0.0,
                'memory_percent_max': 0.0,
                'memory_used_mb_avg': 0.0,
                'memory_used_mb_max': 0.0,
                'memory_total_mb': 0.0,
                'python_process_count_avg': 0,
                'python_process_memory_mb_avg': 0.0,
                'python_process_memory_mb_max': 0.0,
                'network_bytes_total': 0,
                'disk_bytes_total': 0
            }
        
        cpu_values = [m.cpu_percent for m in self.metrics_data]
        memory_percent_values = [m.memory_percent for m in self.metrics_data]
        memory_used_values = [m.memory_used_mb for m in self.metrics_data]
        python_memory_values = [m.python_process_memory_mb for m in self.metrics_data]
        python_count_values = [m.python_process_count for m in self.metrics_data]
        
        # 获取总内存（通常不变）
        memory_total_mb = self.metrics_data[0].memory_total_mb if self.metrics_data else 0.0
        
        # 网络和磁盘IO（使用最后一个值，因为它们是累积的）
        last_metrics = self.metrics_data[-1]
        network_total = last_metrics.network_bytes_sent + last_metrics.network_bytes_recv
        disk_total = last_metrics.disk_read_bytes + last_metrics.disk_write_bytes
        
        # 进程树统计
        process_tree_memory_values = [m.process_tree_memory_mb for m in self.metrics_data]
        process_tree_cpu_values = [m.process_tree_cpu_percent for m in self.metrics_data]
        process_tree_count_values = [m.process_tree_count for m in self.metrics_data]
        network_connections_values = [m.network_connections for m in self.metrics_data]
        
        return {
            'cpu_percent_avg': statistics.mean(cpu_values) if cpu_values else 0.0,
            'cpu_percent_max': max(cpu_values) if cpu_values else 0.0,
            'memory_percent_avg': statistics.mean(memory_percent_values) if memory_percent_values else 0.0,
            'memory_percent_max': max(memory_percent_values) if memory_percent_values else 0.0,
            'memory_used_mb_avg': statistics.mean(memory_used_values) if memory_used_values else 0.0,
            'memory_used_mb_max': max(memory_used_values) if memory_used_values else 0.0,
            'memory_total_mb': memory_total_mb,
            'python_process_count_avg': int(statistics.mean(python_count_values)) if python_count_values else 0,
            'python_process_memory_mb_avg': statistics.mean(python_memory_values) if python_memory_values else 0.0,
            'python_process_memory_mb_max': max(python_memory_values) if python_memory_values else 0.0,
            'process_tree_count_avg': int(statistics.mean(process_tree_count_values)) if process_tree_count_values else 0,
            'process_tree_memory_mb_avg': statistics.mean(process_tree_memory_values) if process_tree_memory_values else 0.0,
            'process_tree_memory_mb_max': max(process_tree_memory_values) if process_tree_memory_values else 0.0,
            'process_tree_cpu_percent_avg': statistics.mean(process_tree_cpu_values) if process_tree_cpu_values else 0.0,
            'process_tree_cpu_percent_max': max(process_tree_cpu_values) if process_tree_cpu_values else 0.0,
            'network_bytes_total': network_total,
            'network_connections_avg': int(statistics.mean(network_connections_values)) if network_connections_values else 0,
            'network_connections_max': max(network_connections_values) if network_connections_values else 0,
            'disk_bytes_total': disk_total
        }
    
    def get_all_metrics(self) -> List[Dict[str, Any]]:
        """获取所有指标数据"""
        return [m.to_dict() for m in self.metrics_data]

