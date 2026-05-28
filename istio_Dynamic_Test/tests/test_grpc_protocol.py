"""gRPC 协议层单元测试（无需 SSH）。"""

import unittest

from istio_Dynamic_Test.internal.models.protocol import Protocol
from istio_Dynamic_Test.internal.models.testcase import TestCase
from istio_Dynamic_Test.internal.telemetry.logs.parser import EnvoyLogParser
from istio_Dynamic_Test.internal.traffic.protocols.grpc.status import (
    is_grpc_success_code,
    parse_grpcurl_output,
)
from istio_Dynamic_Test.internal.traffic.protocols.grpc.target import (
    resolve_grpc_endpoint,
    resolve_grpc_method,
)


class TestGrpcProtocol(unittest.TestCase):
    def test_parse_grpcurl_ok(self):
        code, ok = parse_grpcurl_output('{"status": "SERVING"}', "")
        self.assertTrue(ok)
        self.assertEqual(code, "0")

    def test_parse_grpcurl_error(self):
        code, ok = parse_grpcurl_output(
            "",
            "Error invoking method: rpc error: code = NotFound desc = missing",
        )
        self.assertFalse(ok)
        self.assertEqual(code, "5")

    def test_resolve_method_from_path(self):
        tc = TestCase(
            case_id="t1",
            name="t1",
            protocol=Protocol.GRPC,
            path="/grpc.health.v1.Health/Check",
            target_url="http://ingress:8080",
            host="reviews",
        )
        self.assertEqual(resolve_grpc_method(tc), "grpc.health.v1.Health/Check")
        host, port, auth, method = resolve_grpc_endpoint(tc)
        self.assertEqual(host, "ingress")
        self.assertEqual(port, 8080)
        self.assertEqual(method, "grpc.health.v1.Health/Check")

    def test_envoy_log_grpc_status_tail(self):
        line = (
            '[2024-01-01T00:00:00.000Z] "POST /reviews.Reviews/GetReviews HTTP/2" 200 - 0 0 5 '
            '0 "-" "-" "-" "-" "outbound|9080|v1|reviews.default.svc.cluster.local" '
            'grpc_status=0'
        )
        parser = EnvoyLogParser()
        entries = parser._parse_log_content(line, "reviews-v1-abc")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].grpc_status, 0)
        self.assertTrue(entries[0].is_success)
        self.assertTrue(is_grpc_success_code("0"))


if __name__ == "__main__":
    unittest.main()
