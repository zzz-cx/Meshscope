"""curl 命令构建与 HTTP 状态码判定。"""

import sys
from typing import Dict, Optional, Tuple

from istio_Dynamic_Test.internal.traffic.protocols.http.headers import build_curl_header_args
from istio_Dynamic_Test.internal.traffic.protocols.http.url import compose_request_url
from istio_Dynamic_Test.internal.models.testcase import TestCase


def curl_devnull() -> str:
    return "NUL" if sys.platform == "win32" else "/dev/null"


def build_status_curl_cmd(
    test_case: TestCase,
    *,
    extra_flags: str = "",
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """返回 (curl_command, request_url)。"""
    header_str = build_curl_header_args(test_case, extra_headers=extra_headers)
    url = compose_request_url(test_case.target_url, test_case.path or "")
    null = curl_devnull()
    flags = f" {extra_flags}" if extra_flags else ""
    cmd = (
        f'curl -s -o {null} -w "%{{http_code}}"{flags} '
        f"{header_str} \"{url}\""
    )
    return cmd, url


def is_http_success_code(code: str) -> bool:
    return (code or "").strip().startswith("2")


def count_success_from_status_map(codes: dict) -> int:
    return sum(c for k, c in codes.items() if is_http_success_code(str(k)))
