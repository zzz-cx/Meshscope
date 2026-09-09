#!/usr/bin/env python3
"""
打点工具 - 时间戳、日志记录
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import logging
from contextlib import contextmanager
from dataclasses import dataclass, asdict


@dataclass
class InstrumentationPoint:
    """打点数据结构"""
    stage: str  # Monitor, Parser, Scheduler, Generator, Executor, Detector
    event_type: str  # start, end, error, info
    timestamp: str  # UTC ISO format
    duration_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    thread_id: Optional[int] = None
    process_id: Optional[int] = None


class InstrumentationLogger:
    """打点日志记录器"""
    
    def __init__(self, log_file: str = None, log_level: str = "INFO"):
        self.log_file = log_file or "instrumentation.log"
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.points = []
        self.lock = threading.Lock()
        
        # 设置日志记录器
        self.logger = logging.getLogger("instrumentation")
        self.logger.setLevel(self.log_level)
        
        # 文件处理器
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(self.log_level)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # 禁用重复日志
        self.logger.propagate = False
    
    def log_point(self, point: InstrumentationPoint):
        """记录打点"""
        with self.lock:
            self.points.append(point)
            
            # 记录到日志文件
            log_message = f"STAGE={point.stage} EVENT={point.event_type}"
            if point.duration_ms:
                log_message += f" DURATION={point.duration_ms:.2f}ms"
            if point.metadata:
                log_message += f" METADATA={json.dumps(point.metadata)}"
            
            self.logger.info(log_message)
    
    def get_points_by_stage(self, stage: str) -> List[InstrumentationPoint]:
        """获取特定阶段的打点"""
        with self.lock:
            return [p for p in self.points if p.stage == stage]
    
    def get_points_by_timerange(self, start_time: str, end_time: str) -> List[InstrumentationPoint]:
        """获取时间范围内的打点"""
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        
        with self.lock:
            result = []
            for point in self.points:
                point_dt = datetime.fromisoformat(point.timestamp.replace('Z', '+00:00'))
                if start_dt <= point_dt <= end_dt:
                    result.append(point)
            return result
    
    def clear_points(self):
        """清空打点数据"""
        with self.lock:
            self.points.clear()
    
    def export_points(self, output_file: str):
        """导出打点数据"""
        with self.lock:
            points_data = [asdict(point) for point in self.points]
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(points_data, f, indent=2, ensure_ascii=False)


class PerformanceTimer:
    """性能计时器"""
    
    def __init__(self, logger: InstrumentationLogger, stage: str):
        self.logger = logger
        self.stage = stage
        self.start_time = None
        self.end_time = None
    
    @contextmanager
    def timer(self, event_type: str = "execution", metadata: Dict[str, Any] = None):
        """上下文管理器用于计时"""
        self.start(event_type, metadata)
        try:
            yield self
        finally:
            self.end()
    
    def start(self, event_type: str = "start", metadata: Dict[str, Any] = None):
        """开始计时"""
        self.start_time = time.time()
        point = InstrumentationPoint(
            stage=self.stage,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
            thread_id=threading.get_ident(),
            process_id=os.getpid()
        )
        self.logger.log_point(point)
    
    def end(self, event_type: str = "end", metadata: Dict[str, Any] = None):
        """结束计时"""
        if self.start_time is None:
            return
        
        self.end_time = time.time()
        duration_ms = (self.end_time - self.start_time) * 1000
        
        point = InstrumentationPoint(
            stage=self.stage,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            metadata=metadata,
            thread_id=threading.get_ident(),
            process_id=os.getpid()
        )
        self.logger.log_point(point)
        
        return duration_ms
    
    def lap(self, event_type: str = "lap", metadata: Dict[str, Any] = None) -> float:
        """记录中间时间点"""
        if self.start_time is None:
            return 0.0
        
        current_time = time.time()
        duration_ms = (current_time - self.start_time) * 1000
        
        point = InstrumentationPoint(
            stage=self.stage,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            metadata=metadata,
            thread_id=threading.get_ident(),
            process_id=os.getpid()
        )
        self.logger.log_point(point)
        
        return duration_ms


class StageInstrumentation:
    """阶段打点管理器"""
    
    def __init__(self, logger: InstrumentationLogger):
        self.logger = logger
        self.timers = {}
        self.stage_start_times = {}
    
    def get_timer(self, stage: str) -> PerformanceTimer:
        """获取特定阶段的计时器"""
        if stage not in self.timers:
            self.timers[stage] = PerformanceTimer(self.logger, stage)
        return self.timers[stage]
    
    def start_stage(self, stage: str, metadata: Dict[str, Any] = None):
        """开始阶段"""
        self.stage_start_times[stage] = time.time()
        self.get_timer(stage).start("start", metadata)
    
    def end_stage(self, stage: str, metadata: Dict[str, Any] = None) -> float:
        """结束阶段"""
        if stage not in self.stage_start_times:
            return 0.0
        
        duration_ms = self.get_timer(stage).end("end", metadata)
        del self.stage_start_times[stage]
        return duration_ms
    
    def log_stage_event(self, stage: str, event_type: str, metadata: Dict[str, Any] = None):
        """记录阶段事件"""
        point = InstrumentationPoint(
            stage=stage,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
            thread_id=threading.get_ident(),
            process_id=os.getpid()
        )
        self.logger.log_point(point)
    
    def calculate_end_to_end_latency(self, start_stage: str = "Monitor", 
                                   end_stage: str = "Detector") -> Optional[float]:
        """计算端到端延迟"""
        start_points = self.logger.get_points_by_stage(start_stage)
        end_points = self.logger.get_points_by_stage(end_stage)
        
        if not start_points or not end_points:
            return None
        
        # 找到最近的开始和结束点
        latest_start = max(start_points, key=lambda p: p.timestamp)
        latest_end = max(end_points, key=lambda p: p.timestamp)
        
        start_dt = datetime.fromisoformat(latest_start.timestamp.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(latest_end.timestamp.replace('Z', '+00:00'))
        
        return (end_dt - start_dt).total_seconds() * 1000  # 转换为毫秒
    
    def get_stage_statistics(self) -> Dict[str, Dict[str, Any]]:
        """获取各阶段统计信息"""
        statistics = {}
        
        for stage in ["Monitor", "Parser", "Scheduler", "Generator", "Executor", "Detector"]:
            points = self.logger.get_points_by_stage(stage)
            
            if not points:
                continue
            
            # 计算执行次数和平均时间
            execution_points = [p for p in points if p.event_type == "end" and p.duration_ms]
            
            if execution_points:
                durations = [p.duration_ms for p in execution_points]
                statistics[stage] = {
                    "execution_count": len(execution_points),
                    "average_duration_ms": sum(durations) / len(durations),
                    "min_duration_ms": min(durations),
                    "max_duration_ms": max(durations),
                    "total_duration_ms": sum(durations)
                }
            else:
                statistics[stage] = {
                    "execution_count": len(points),
                    "average_duration_ms": 0,
                    "min_duration_ms": 0,
                    "max_duration_ms": 0,
                    "total_duration_ms": 0
                }
        
        return statistics


class InstrumentationManager:
    """打点管理器 - 全局单例"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.logger = InstrumentationLogger()
            self.stage_manager = StageInstrumentation(self.logger)
            self._initialized = True
    
    def get_stage_manager(self) -> StageInstrumentation:
        """获取阶段管理器"""
        return self.stage_manager
    
    def get_logger(self) -> InstrumentationLogger:
        """获取日志记录器"""
        return self.logger
    
    def reset(self):
        """重置打点数据"""
        self.logger.clear_points()
        self.stage_manager.timers.clear()
        self.stage_manager.stage_start_times.clear()


# 便捷函数
def get_instrumentation() -> InstrumentationManager:
    """获取全局打点管理器"""
    return InstrumentationManager()


def log_stage_start(stage: str, metadata: Dict[str, Any] = None):
    """记录阶段开始"""
    manager = get_instrumentation()
    manager.get_stage_manager().start_stage(stage, metadata)


def log_stage_end(stage: str, metadata: Dict[str, Any] = None) -> float:
    """记录阶段结束"""
    manager = get_instrumentation()
    return manager.get_stage_manager().end_stage(stage, metadata)


def log_stage_event(stage: str, event_type: str, metadata: Dict[str, Any] = None):
    """记录阶段事件"""
    manager = get_instrumentation()
    manager.get_stage_manager().log_stage_event(stage, event_type, metadata)


@contextmanager
def stage_timer(stage: str, event_type: str = "execution", metadata: Dict[str, Any] = None):
    """阶段计时上下文管理器"""
    manager = get_instrumentation()
    timer = manager.get_stage_manager().get_timer(stage)
    
    with timer.timer(event_type, metadata):
        yield timer


def main():
    """主函数 - 用于测试"""
    import argparse
    
    parser = argparse.ArgumentParser(description="打点工具测试")
    parser.add_argument("--log-file", help="日志文件路径")
    parser.add_argument("--export", help="导出文件路径")
    
    args = parser.parse_args()
    
    # 初始化打点管理器
    manager = get_instrumentation()
    if args.log_file:
        manager.logger.log_file = args.log_file
    
    # 模拟一些打点操作
    stage_manager = manager.get_stage_manager()
    
    # 模拟实验流程
    stage_manager.start_stage("Monitor", {"config_files": ["test.yaml"]})
    time.sleep(0.1)
    
    stage_manager.start_stage("Parser", {"parsing_method": "yaml"})
    time.sleep(0.2)
    stage_manager.end_stage("Parser")
    
    stage_manager.start_stage("Generator", {"test_cases": 10})
    time.sleep(0.15)
    stage_manager.end_stage("Generator")
    
    stage_manager.start_stage("Executor", {"traffic_requests": 100})
    time.sleep(0.3)
    stage_manager.end_stage("Executor")
    
    stage_manager.start_stage("Detector", {"issues_found": 2})
    time.sleep(0.1)
    stage_manager.end_stage("Detector")
    
    stage_manager.end_stage("Monitor")
    
    # 计算端到端延迟
    e2e_latency = stage_manager.calculate_end_to_end_latency()
    print(f"End-to-end latency: {e2e_latency:.2f}ms")
    
    # 打印统计信息
    stats = stage_manager.get_stage_statistics()
    print("\nStage Statistics:")
    for stage, stat in stats.items():
        print(f"  {stage}: {stat['execution_count']} executions, "
              f"avg {stat['average_duration_ms']:.2f}ms")
    
    # 导出数据
    if args.export:
        manager.logger.export_points(args.export)
        print(f"Exported instrumentation data to {args.export}")


if __name__ == "__main__":
    main()
