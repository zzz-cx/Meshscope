#!/usr/bin/env python3
"""
系统资源监控器
支持从主机系统读取真实的CPU和内存数据，以及通过SSH或Kubernetes API获取远程指标
"""

import time
import threading
import subprocess
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import statistics

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class SystemMetrics:
    """系统指标数据类"""
    timestamp: float
    cpu_percent: float  # CPU使用率（%）
    memory_percent: float  # 内存使用率（%）
    memory_used_mb: float  # 已使用内存（MB）
    memory_total_mb: float  # 总内存（MB）
    load_avg: Optional[float] = None  # 系统负载（Linux）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'cpu_percent': round(self.cpu_percent, 2),
            'memory_percent': round(self.memory_percent, 2),
            'memory_used_mb': round(self.memory_used_mb, 2),
            'memory_total_mb': round(self.memory_total_mb, 2),
            'load_avg': round(self.load_avg, 2) if self.load_avg else None
        }


class SystemResourceMonitor:
    """系统资源监控器 - 监控整个系统的CPU和内存使用情况"""
    
    def __init__(
        self,
        sampling_interval: float = 0.1,
        monitor_remote: bool = False,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None
    ):
        """
        初始化系统资源监控器
        
        Args:
            sampling_interval: 采样间隔（秒）
            monitor_remote: 是否监控远程主机
            ssh_host: SSH主机地址
            ssh_user: SSH用户名
            ssh_password: SSH密码
        """
        self.sampling_interval = sampling_interval
        self.monitoring = False
        self.metrics_data: List[SystemMetrics] = []
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 远程监控配置
        self.monitor_remote = monitor_remote
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.ssh_client: Optional[Any] = None
        
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
        
        # 如果是远程监控，建立SSH连接
        if self.monitor_remote and self.ssh_host:
            self._connect_ssh()
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info("系统资源监控已启动（监控整个系统）")
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        
        # 关闭SSH连接
        if self.ssh_client:
            self._disconnect_ssh()
        
        data_points = len(self.metrics_data)
        logger.info(f"系统资源监控已停止，收集到 {data_points} 个数据点")
        if data_points > 0:
            # 显示采样到的数据范围
            cpu_values = [m.cpu_percent for m in self.metrics_data]
            memory_values = [m.memory_percent for m in self.metrics_data]
            logger.debug(f"  CPU范围: {min(cpu_values):.2f}% - {max(cpu_values):.2f}%")
            logger.debug(f"  内存范围: {min(memory_values):.2f}% - {max(memory_values):.2f}%")
    
    def _connect_ssh(self):
        """建立SSH连接"""
        if not PARAMIKO_AVAILABLE:
            logger.warning("paramiko未安装，无法使用SSH监控")
            return
        
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                hostname=self.ssh_host,
                username=self.ssh_user,
                password=self.ssh_password,
                timeout=10
            )
            logger.info(f"SSH连接已建立: {self.ssh_host}")
        except Exception as e:
            logger.error(f"SSH连接失败: {e}")
            self.ssh_client = None
    
    def _disconnect_ssh(self):
        """断开SSH连接"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
                logger.info("SSH连接已断开")
            except Exception as e:
                logger.warning(f"断开SSH连接时出错: {e}")
            finally:
                self.ssh_client = None
    
    def _get_local_metrics(self) -> Optional[SystemMetrics]:
        """获取本地系统指标"""
        try:
            # CPU使用率（整个系统）
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # 内存使用情况（整个系统）
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_mb = memory.used / (1024 * 1024)
            memory_total_mb = memory.total / (1024 * 1024)
            
            # 系统负载（Linux）
            try:
                load_avg = psutil.getloadavg()[0]  # 1分钟平均负载
            except (AttributeError, OSError):
                load_avg = None  # Windows不支持getloadavg
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                load_avg=load_avg
            )
        except Exception as e:
            logger.error(f"获取本地系统指标失败: {e}")
            return None
    
    def _get_remote_metrics_via_ssh(self) -> Optional[SystemMetrics]:
        """通过SSH获取远程系统指标"""
        if not self.ssh_client:
            return None
        
        try:
            # 使用top命令获取CPU和内存使用率（Linux）
            # top -bn1 表示批处理模式，只运行一次
            stdin, stdout, stderr = self.ssh_client.exec_command(
                "top -bn1 | head -n 3"
            )
            top_output = stdout.read().decode('utf-8')
            
            # 解析top输出
            lines = top_output.strip().split('\n')
            if len(lines) < 3:
                # 如果top不可用，尝试使用vmstat或/proc/stat
                return self._get_remote_metrics_via_proc()
            
            # 从top输出解析CPU使用率
            # 第二行格式: %Cpu(s):  x.x us,  y.y sy,  z.z id, ...
            cpu_line = lines[1] if len(lines) > 1 else ""
            cpu_percent = 0.0
            if '%Cpu(s):' in cpu_line or 'Cpu(s):' in cpu_line:
                # 提取idle百分比，然后计算使用率
                parts = cpu_line.split(',')
                for part in parts:
                    if 'id' in part.lower():
                        try:
                            idle = float(part.split()[0].replace('%', ''))
                            cpu_percent = 100.0 - idle
                            break
                        except (ValueError, IndexError):
                            pass
            
            # 从top输出解析内存使用率
            # 第三行格式: KiB Mem:  total used free ...
            mem_line = lines[2] if len(lines) > 2 else ""
            memory_percent = 0.0
            memory_used_mb = 0.0
            memory_total_mb = 0.0
            if 'Mem:' in mem_line:
                parts = mem_line.split()
                try:
                    # 查找total和used
                    for i, part in enumerate(parts):
                        if part == 'total' and i > 0:
                            memory_total_mb = float(parts[i-1]) / 1024  # KiB to MB
                        elif part == 'used' and i > 0:
                            memory_used_mb = float(parts[i-1]) / 1024  # KiB to MB
                    
                    if memory_total_mb > 0:
                        memory_percent = (memory_used_mb / memory_total_mb) * 100
                except (ValueError, IndexError):
                    pass
            
            # 如果解析失败，使用/proc方法
            if cpu_percent == 0.0 or memory_percent == 0.0:
                return self._get_remote_metrics_via_proc()
            
            # 获取系统负载
            stdin, stdout, stderr = self.ssh_client.exec_command("uptime")
            uptime_output = stdout.read().decode('utf-8')
            load_avg = None
            if 'load average:' in uptime_output:
                try:
                    load_part = uptime_output.split('load average:')[1].strip()
                    load_avg = float(load_part.split(',')[0])
                except (ValueError, IndexError):
                    pass
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                load_avg=load_avg
            )
        except Exception as e:
            logger.warning(f"通过SSH获取远程指标失败: {e}，尝试使用/proc方法")
            return self._get_remote_metrics_via_proc()
    
    def _get_remote_metrics_via_proc(self) -> Optional[SystemMetrics]:
        """通过/proc文件系统获取远程系统指标（更可靠的方法）"""
        if not self.ssh_client:
            return None
        
        try:
            # 获取CPU使用率 - 使用vmstat或直接读取/proc/stat
            # 先尝试使用vmstat（更简单）
            stdin, stdout, stderr = self.ssh_client.exec_command("vmstat 1 2 | tail -n 1")
            vmstat_output = stdout.read().decode('utf-8')
            
            cpu_percent = 0.0
            if vmstat_output and len(vmstat_output.strip().split()) >= 15:
                # vmstat输出格式: procs r b swpd free buff cache si so bi bo in cs us sy id wa st
                parts = vmstat_output.strip().split()
                try:
                    # us + sy = CPU使用率
                    us = float(parts[12])  # user time
                    sy = float(parts[13])  # system time
                    cpu_percent = us + sy
                except (ValueError, IndexError):
                    pass
            
            # 如果vmstat失败，使用/proc/stat方法
            if cpu_percent == 0.0:
                stdin1, stdout1, stderr1 = self.ssh_client.exec_command("cat /proc/stat | head -n 1")
                stat1 = stdout1.read().decode('utf-8')
                time.sleep(0.2)  # 增加等待时间
                stdin2, stdout2, stderr2 = self.ssh_client.exec_command("cat /proc/stat | head -n 1")
                stat2 = stdout2.read().decode('utf-8')
                
                if stat1 and stat2:
                    # 解析CPU时间
                    def parse_cpu_line(line):
                        parts = line.split()
                        if len(parts) >= 8:
                            user = int(parts[1])
                            nice = int(parts[2])
                            system = int(parts[3])
                            idle = int(parts[4])
                            iowait = int(parts[5]) if len(parts) > 5 else 0
                            total = user + nice + system + idle + iowait
                            return total, idle
                        return 0, 0
                    
                    total1, idle1 = parse_cpu_line(stat1)
                    total2, idle2 = parse_cpu_line(stat2)
                    
                    if total2 > total1:
                        total_diff = total2 - total1
                        idle_diff = idle2 - idle1
                        if total_diff > 0:
                            cpu_percent = ((total_diff - idle_diff) / total_diff) * 100
            
            # 获取内存使用情况
            stdin, stdout, stderr = self.ssh_client.exec_command("cat /proc/meminfo")
            meminfo = stdout.read().decode('utf-8')
            
            memory_total_mb = 0.0
            memory_used_mb = 0.0
            memory_percent = 0.0
            
            if meminfo:
                for line in meminfo.split('\n'):
                    if 'MemTotal:' in line:
                        try:
                            memory_total_mb = float(line.split()[1]) / 1024  # kB to MB
                        except (ValueError, IndexError):
                            pass
                    elif 'MemAvailable:' in line:
                        try:
                            mem_available = float(line.split()[1]) / 1024  # kB to MB
                            memory_used_mb = memory_total_mb - mem_available
                        except (ValueError, IndexError):
                            pass
                    elif 'MemFree:' in line and memory_used_mb == 0.0:
                        try:
                            mem_free = float(line.split()[1]) / 1024  # kB to MB
                            memory_used_mb = memory_total_mb - mem_free
                        except (ValueError, IndexError):
                            pass
                
                if memory_total_mb > 0:
                    memory_percent = (memory_used_mb / memory_total_mb) * 100
            
            # 获取系统负载
            stdin, stdout, stderr = self.ssh_client.exec_command("cat /proc/loadavg")
            loadavg_output = stdout.read().decode('utf-8')
            load_avg = None
            if loadavg_output:
                try:
                    load_avg = float(loadavg_output.split()[0])
                except (ValueError, IndexError):
                    pass
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                load_avg=load_avg
            )
        except Exception as e:
            logger.error(f"通过/proc获取远程指标失败: {e}")
            return None
    
    def _monitor_loop(self):
        """监控循环"""
        # 初始延迟，确保第一次采样准确（对于CPU百分比计算很重要）
        time.sleep(0.1)
        
        while self.monitoring:
            try:
                if self.monitor_remote and self.ssh_client:
                    # 监控远程系统
                    metrics = self._get_remote_metrics_via_ssh()
                else:
                    # 监控本地系统
                    metrics = self._get_local_metrics()
                
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
                'load_avg_avg': 0.0,
                'load_avg_max': 0.0
            }
        
        cpu_values = [m.cpu_percent for m in self.metrics_data]
        memory_percent_values = [m.memory_percent for m in self.metrics_data]
        memory_used_values = [m.memory_used_mb for m in self.metrics_data]
        load_avg_values = [m.load_avg for m in self.metrics_data if m.load_avg is not None]
        
        # 获取总内存（通常不变）
        memory_total_mb = self.metrics_data[0].memory_total_mb if self.metrics_data else 0.0
        
        return {
            'cpu_percent_avg': statistics.mean(cpu_values) if cpu_values else 0.0,
            'cpu_percent_max': max(cpu_values) if cpu_values else 0.0,
            'memory_percent_avg': statistics.mean(memory_percent_values) if memory_percent_values else 0.0,
            'memory_percent_max': max(memory_percent_values) if memory_percent_values else 0.0,
            'memory_used_mb_avg': statistics.mean(memory_used_values) if memory_used_values else 0.0,
            'memory_used_mb_max': max(memory_used_values) if memory_used_values else 0.0,
            'memory_total_mb': memory_total_mb,
            'load_avg_avg': statistics.mean(load_avg_values) if load_avg_values else 0.0,
            'load_avg_max': max(load_avg_values) if load_avg_values else 0.0
        }
    
    def get_all_metrics(self) -> List[Dict[str, Any]]:
        """获取所有指标数据"""
        return [m.to_dict() for m in self.metrics_data]

