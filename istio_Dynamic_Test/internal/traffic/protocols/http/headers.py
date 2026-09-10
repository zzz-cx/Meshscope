"""HTTP 请求头 → curl 参数。"""

from typing import Dict, Optional

from istio_Dynamic_Test.internal.models.testcase import TestCase


def build_curl_header_args(
    test_case: TestCase,
    *,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """生成 curl -H 参数串（含 VS 匹配所需的 Host 推断）。"""
    header_parts = []
    host_for_header = test_case.host
    if host_for_header == "*" and test_case.source_service:
        host_for_header = test_case.source_service
    headers = dict(test_case.headers or {})
    if extra_headers:
        headers = {**headers, **extra_headers}
    if (
        host_for_header
        and host_for_header != "*"
        and "Host" not in headers
        and "host" not in headers
    ):
        header_parts.append(f'-H "Host: {host_for_header}"')
    for k, v in headers.items():
        header_parts.append(f'-H "{k}: {v}"')
    return " ".join(header_parts)
