"""执行结果落盘（按协议分子目录，兼容旧 http_results 路径）。"""

import json
import os
from datetime import datetime

from istio_Dynamic_Test.internal.models.protocol import Protocol
from istio_Dynamic_Test.internal.models.testcase import ExecutionResult

_PROTOCOL_SUBDIR = {
    Protocol.HTTP: "http_results",
    Protocol.GRPC: "grpc_results",
}


def results_subdir(protocol: Protocol = Protocol.HTTP) -> str:
    return os.path.join("results", _PROTOCOL_SUBDIR.get(protocol, f"{protocol.value}_results"))


def save_execution_result(
    case_id: str,
    result: ExecutionResult,
    protocol: Protocol = Protocol.HTTP,
) -> str:
    """保存执行结果 JSON，返回文件路径。"""
    results_dir = results_subdir(protocol)
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = protocol.value
    path = os.path.join(results_dir, f"{case_id}_{prefix}_result_{ts}.json")
    payload_key = f"{prefix}_result"
    data = {
        "case_id": case_id,
        "timestamp": ts,
        "protocol": protocol.value,
        payload_key: {
            "status_codes": result.status_codes,
            "total_requests": result.total_requests,
            "success_rate": result.success_rate,
            "avg_response_time": result.avg_response_time,
            "error_count": result.error_count,
        },
        # 兼容 DynamicAnalyzer 读取 http_result 字段
        "http_result": {
            "status_codes": result.status_codes,
            "total_requests": result.total_requests,
            "success_rate": result.success_rate,
            "avg_response_time": result.avg_response_time,
            "error_count": result.error_count,
            "metadata": result.metadata or {},
            "version_counts": (result.metadata or {}).get("version_counts") or {},
            "version_percentages": (result.metadata or {}).get("version_percentages") or {},
            "landed_services": (result.metadata or {}).get("landed_services") or {},
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path
