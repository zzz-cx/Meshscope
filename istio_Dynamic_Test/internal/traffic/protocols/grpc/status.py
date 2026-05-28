"""gRPC 状态码解析与判定。"""

import re
from typing import Dict, Optional, Tuple

# gRPC 官方状态码名称 → 数字字符串（与 ExecutionResult.status_codes 键一致）
_GRPC_NAME_TO_CODE: Dict[str, str] = {
    "OK": "0",
    "CANCELLED": "1",
    "CANCELED": "1",
    "UNKNOWN": "2",
    "INVALID_ARGUMENT": "3",
    "DEADLINE_EXCEEDED": "4",
    "NOT_FOUND": "5",
    "ALREADY_EXISTS": "6",
    "PERMISSION_DENIED": "7",
    "RESOURCE_EXHAUSTED": "8",
    "FAILED_PRECONDITION": "9",
    "ABORTED": "10",
    "OUT_OF_RANGE": "11",
    "UNIMPLEMENTED": "12",
    "INTERNAL": "13",
    "UNAVAILABLE": "14",
    "DATA_LOSS": "15",
    "UNAUTHENTICATED": "16",
}

# CamelCase（grpcurl 错误输出）
_GRPC_CAMEL_TO_CODE: Dict[str, str] = {
    "Ok": "0",
    "Cancelled": "1",
    "Canceled": "1",
    "Unknown": "2",
    "InvalidArgument": "3",
    "DeadlineExceeded": "4",
    "NotFound": "5",
    "AlreadyExists": "6",
    "PermissionDenied": "7",
    "ResourceExhausted": "8",
    "FailedPrecondition": "9",
    "Aborted": "10",
    "OutOfRange": "11",
    "Unimplemented": "12",
    "Internal": "13",
    "Unavailable": "14",
    "DataLoss": "15",
    "Unauthenticated": "16",
}


def grpc_name_to_code(name: str) -> str:
    """将 gRPC 状态名转为数字字符串；未知则返回原字符串。"""
    if not name:
        return "unknown"
    raw = name.strip()
    if raw.isdigit():
        return raw
    upper = raw.upper().replace(" ", "_")
    if upper in _GRPC_NAME_TO_CODE:
        return _GRPC_NAME_TO_CODE[upper]
    if raw in _GRPC_CAMEL_TO_CODE:
        return _GRPC_CAMEL_TO_CODE[raw]
    return raw


def is_grpc_success_code(code: str) -> bool:
    c = (code or "").strip()
    return c in ("0", "OK", "Ok")


def count_success_from_grpc_status_map(codes: dict) -> int:
    return sum(c for k, c in codes.items() if is_grpc_success_code(str(k)))


def parse_grpcurl_output(output: str, error: str = "") -> Tuple[str, bool]:
    """
    从 grpcurl 合并输出解析 gRPC 状态码。
    返回 (status_code_key, is_success)。
    """
    text = f"{output or ''}\n{error or ''}"
    if not text.strip():
        return "unknown", False

    # rpc error: code = NotFound desc = ...
    m = re.search(r"code\s*=\s*([A-Za-z_]+)", text)
    if m:
        code = grpc_name_to_code(m.group(1))
        return code, is_grpc_success_code(code)

    # ERROR: Code: Unavailable
    m = re.search(r"Code:\s*([A-Za-z]+)", text)
    if m:
        code = grpc_name_to_code(m.group(1))
        return code, is_grpc_success_code(code)

    # 无错误输出且有条目 → 视为 OK
    lower = text.lower()
    if "error invoking" not in lower and "failed" not in lower and "code =" not in lower:
        if output and output.strip():
            return "0", True

    return "unknown", False
