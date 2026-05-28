"""grpcurl 命令构建与输出解析。"""

import json
import shlex
from typing import Dict, Optional, Tuple

from istio_Dynamic_Test.internal.models.testcase import TestCase
from istio_Dynamic_Test.internal.traffic.protocols.grpc.status import parse_grpcurl_output
from istio_Dynamic_Test.internal.traffic.protocols.grpc.target import resolve_grpc_endpoint


def _normalize_payload(raw: str) -> str:
    text = (raw or "").strip() or "{}"
    try:
        return json.dumps(json.loads(text), separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return "{}"


def build_grpcurl_header_args(test_case: TestCase) -> str:
    """生成 grpcurl -H 参数片段。"""
    parts = []
    host, _, authority, _ = resolve_grpc_endpoint(test_case)
    if authority and authority != host:
        parts.append(f'-H {shlex.quote(f":authority: {authority}")}')
    skip = {":authority", "host"}
    for key, val in (test_case.headers or {}).items():
        if key.lower() in skip:
            continue
        parts.append(f"-H {shlex.quote(f'{key}: {val}')}")
    return " ".join(parts) + (" " if parts else "")


def build_grpcurl_cmd(
    test_case: TestCase,
    *,
    max_time: int = 10,
    endpoint_override: Optional[str] = None,
) -> Tuple[str, str]:
    """
    构建远程执行的 grpcurl 命令。

    Returns:
        (command, target_label)  target_label 用于日志，如 host:port/method
    """
    host, port, _, method = resolve_grpc_endpoint(test_case)
    target = endpoint_override or f"{host}:{port}"
    plaintext = "-plaintext " if test_case.grpc_plaintext else ""
    header_str = build_grpcurl_header_args(test_case)
    payload = _normalize_payload(test_case.grpc_payload)
    payload_q = shlex.quote(payload)
    cmd = (
        f"grpcurl {plaintext}{header_str}-max-time {max_time} "
        f"-d {payload_q} {shlex.quote(target)} {shlex.quote(method)}"
    )
    return cmd, f"{target}/{method}"


def run_grpcurl_once(
    ssh_client,
    test_case: TestCase,
    *,
    max_time: int = 10,
    endpoint_override: Optional[str] = None,
) -> Tuple[str, str, str, bool]:
    """执行一次 grpcurl，返回 (status_code, output, error, is_success)。"""
    cmd, _label = build_grpcurl_cmd(
        test_case, max_time=max_time, endpoint_override=endpoint_override
    )
    output, error = ssh_client.run_command(cmd)
    code, ok = parse_grpcurl_output(output, error)
    return code, output or "", error or "", ok
