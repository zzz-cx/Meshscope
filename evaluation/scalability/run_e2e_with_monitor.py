#!/usr/bin/env python3
"""
运行 e2e_validator 并监控 CPU / 内存指标的辅助脚本。

该脚本会启动 e2e_validator 作为子进程，使用 psutil 定期采样主进程及其所有子进程的 CPU 占用和内存占用，
并在任务结束后输出摘要，同时将完整的采样数据写入 JSON 文件。

使用示例：
    python evaluation/scalability/run_e2e_with_monitor.py \
        --vm-host ${SSH_HOST} --vm-user ${SSH_USER:-root} --vm-password ${SSH_PASSWORD} \
        --namespace default --output-dir results/e2e_validation_monitored
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from consistency_checker.config import get_config

try:
    import psutil
except ImportError as exc:  # pragma: no cover - 环境必须具备 psutil
    print("缺少 psutil 依赖，请先安装: pip install psutil", file=sys.stderr)
    raise exc


def parse_args() -> argparse.Namespace:
    global_config = get_config()
    parser = argparse.ArgumentParser(
        description="运行 e2e_validator 并采集 CPU/内存指标",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    default_host = os.getenv("SSH_HOST") or global_config.ssh_host
    default_user = os.getenv("SSH_USER") or global_config.ssh_user
    default_password = os.getenv("SSH_PASSWORD") or global_config.ssh_password
    parser.add_argument("--vm-host", required=not default_host, default=default_host, help="虚拟机主机地址")
    parser.add_argument("--vm-user", default=default_user, help="虚拟机用户名")
    parser.add_argument("--vm-password", default=default_password, help="虚拟机密码")
    parser.add_argument("--namespace", default=global_config.namespace, help="Kubernetes 命名空间")
    parser.add_argument(
        "--output-dir",
        default="results/e2e_validation_monitored",
        help="e2e_validator 的输出目录",
    )
    parser.add_argument(
        "--sampling-interval",
        type=float,
        default=0.5,
        help="采样间隔（秒）",
    )
    parser.add_argument(
        "--monitor-output",
        default="results/monitoring",
        help="监控数据输出目录",
    )
    return parser.parse_args()


def collect_process_metrics(process: psutil.Process) -> Dict[str, float]:
    """收集主进程及其所有子进程的 CPU / 内存使用情况。"""
    cpu_percent = process.cpu_percent(interval=None)
    mem_info = process.memory_info()
    total_cpu = cpu_percent
    total_mem = mem_info.rss / (1024 * 1024)

    for child in process.children(recursive=True):
        try:
            total_cpu += child.cpu_percent(interval=None)
            total_mem += child.memory_info().rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {"cpu_percent": total_cpu, "memory_mb": total_mem}


def run_with_monitor(args: argparse.Namespace) -> Dict[str, Any]:
    command = [
        sys.executable,
        "e2e_validator.py",
        "--vm-host",
        args.vm_host,
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
        "--namespace",
        args.namespace,
        "--output-dir",
        args.output_dir,
    ]

    monitor_dir = Path(args.monitor_output)
    monitor_dir.mkdir(parents=True, exist_ok=True)

    system_before = psutil.virtual_memory()
    started_at = time.time()

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )

    ps_process = psutil.Process(process.pid)
    ps_process.cpu_percent(interval=None)  # 初始化 CPU 百分比计算

    samples: List[Dict[str, float]] = []

    try:
        while True:
            if process.poll() is not None:
                break
            time.sleep(args.sampling_interval)
            metrics = collect_process_metrics(ps_process)
            samples.append(
                {
                    "timestamp": time.time() - started_at,
                    "cpu_percent": round(metrics["cpu_percent"], 2),
                    "memory_mb": round(metrics["memory_mb"], 2),
                }
            )
    finally:
        stdout = process.communicate()[0]

    finished_at = time.time()
    system_after = psutil.virtual_memory()

    cpu_values = [sample["cpu_percent"] for sample in samples]
    mem_values = [sample["memory_mb"] for sample in samples]

    summary = {
        "command": " ".join(command),
        "duration_sec": round(finished_at - started_at, 3),
        "stdout": stdout,
        "sample_count": len(samples),
        "cpu_avg_percent": round(sum(cpu_values) / len(cpu_values), 2)
        if cpu_values
        else 0.0,
        "cpu_max_percent": round(max(cpu_values), 2) if cpu_values else 0.0,
        "memory_avg_mb": round(sum(mem_values) / len(mem_values), 2)
        if mem_values
        else 0.0,
        "memory_max_mb": round(max(mem_values), 2) if mem_values else 0.0,
        "memory_before_mb": round(system_before.used / (1024 * 1024), 2),
        "memory_after_mb": round(system_after.used / (1024 * 1024), 2),
        "memory_delta_mb": round(
            (system_after.used - system_before.used) / (1024 * 1024), 2
        ),
        "samples": samples,
    }

    output_path = monitor_dir / f"e2e_monitor_{int(finished_at)}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    summary["output_file"] = str(output_path)
    return summary


def main() -> int:
    args = parse_args()
    summary = run_with_monitor(args)

    print("e2e_validator 运行完成，输出如下:\n")
    print(summary.pop("stdout", ""))

    print("资源监控摘要：")
    printable_summary = {k: v for k, v in summary.items() if k != "samples"}
    print(json.dumps(printable_summary, indent=2, ensure_ascii=False))

    print("采样数据已保存到:", printable_summary["output_file"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
