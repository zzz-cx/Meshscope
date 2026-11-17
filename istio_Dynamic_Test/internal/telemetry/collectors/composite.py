"""CompositeCollector —— 按用例选择采集方式。

分流观察链：
1. 响应体/响应头能认出版本时，Executor 已经统计，这里可以跳过
2. 否则采 Prometheus 增量（istio_requests_total by revision/version/workload）
3. 再解析已有 Envoy access log（不 enable、不 rollout sidecar）
4. 再查 Jaeger / Zipkin 调用链上的 subset
"""

from collections import Counter
from typing import Any, Dict, List, Optional
import os

import requests

from istio_Dynamic_Test.internal.models.testcase import CollectionResult, TestCase
from istio_Dynamic_Test.internal.models.testcase import PolicyType
from istio_Dynamic_Test.internal.telemetry.metrics.prometheus import query_traffic_distribution_ex
from istio_Dynamic_Test.internal.telemetry.collectors.base import BaseCollector
from istio_Dynamic_Test.internal.telemetry.collectors.envoy import EnvoyCollector
from istio_Dynamic_Test.internal.telemetry.logs.parser import EnvoyLogParser
from istio_Dynamic_Test.internal.traffic.split_observe import short_service_name, version_from_workload


class CompositeCollector(BaseCollector):
    """组合采集器：分流走可观测回退，其余用 Envoy 日志。"""

    def __init__(
        self,
        envoy_collector: Optional[EnvoyCollector] = None,
        prometheus_url: Optional[str] = None,
        namespace: str = "default",
        ssh_client=None,
        jaeger_url: Optional[str] = None,
        zipkin_url: Optional[str] = None,
    ):
        self._envoy = envoy_collector or EnvoyCollector(
            ssh_client=ssh_client, namespace=namespace
        )
        self._prometheus_url = prometheus_url
        self._jaeger_url = jaeger_url
        self._zipkin_url = zipkin_url
        self._namespace = namespace
        self._split_queries: Dict[str, str] = {}

    def collect(
        self,
        test_case: TestCase,
        pre_snapshot: Optional[dict] = None,
        pre_prometheus: Optional[Dict[str, int]] = None,
        skip_telemetry: bool = False,
    ) -> CollectionResult:
        if PolicyType.TRAFFIC_SPLIT in test_case.policy_types and test_case.expected_distribution:
            if skip_telemetry:
                return CollectionResult(
                    case_id=test_case.case_id,
                    metadata={"observer": "http_body", "skipped_telemetry": True},
                )
            return self._collect_split_telemetry(
                test_case,
                pre_prometheus=pre_prometheus,
                pre_snapshot=pre_snapshot,
            )
        return self._envoy.collect(test_case, pre_snapshot=pre_snapshot)

    def _collect_split_telemetry(
        self,
        test_case: TestCase,
        pre_prometheus: Optional[Dict[str, int]] = None,
        pre_snapshot: Optional[dict] = None,
    ) -> CollectionResult:
        metadata: Dict[str, Any] = {"observer": "telemetry_fallback", "tried": []}
        prometheus_metrics: Dict[str, Any] = {}

        if self._prometheus_url:
            metadata["tried"].append("prometheus")
            prom = self._collect_prometheus(test_case, pre_prometheus)
            prometheus_metrics = prom.prometheus_metrics or {}
            if prometheus_metrics.get("_error"):
                metadata["prometheus_error"] = prometheus_metrics.get("_error")
            else:
                metadata["prometheus_distribution"] = prometheus_metrics.get("traffic_distribution") or {}

        envoy_dist = self._collect_envoy_distribution(test_case, pre_snapshot)
        metadata["tried"].append("envoy_access_log")
        metadata["envoy_distribution"] = envoy_dist
        if envoy_dist.get("error"):
            metadata["envoy_error"] = envoy_dist.get("error")

        tracing_url = self._jaeger_url or self._zipkin_url
        if tracing_url:
            metadata["tried"].append("jaeger")
            jaeger_dist = self._collect_jaeger_distribution(test_case, tracing_url)
            metadata["jaeger_distribution"] = jaeger_dist
            if jaeger_dist.get("error"):
                metadata["jaeger_error"] = jaeger_dist.get("error")

        return CollectionResult(
            case_id=test_case.case_id,
            prometheus_metrics=prometheus_metrics,
            metadata=metadata,
        )

    def _collect_prometheus(
        self,
        test_case: TestCase,
        pre_prometheus: Optional[Dict[str, int]],
    ) -> CollectionResult:
        svc = short_service_name(test_case.host, test_case.source_service) or "unknown"
        versions = list(test_case.expected_distribution.keys())
        hint = self._split_queries.get(test_case.case_id)

        try:
            after, used = query_traffic_distribution_ex(
                self._prometheus_url, svc, versions, self._namespace, promql=hint
            )
            self._split_queries[test_case.case_id] = used
        except Exception as e:
            return CollectionResult(
                case_id=test_case.case_id,
                prometheus_metrics={"_error": str(e)},
            )

        if pre_prometheus is not None:
            delta = {
                v: max(0, after.get(v, 0) - pre_prometheus.get(v, 0))
                for v in set(versions) | set(after.keys()) | set(pre_prometheus.keys())
            }
        else:
            delta = {}

        total = sum(max(0, int(delta.get(v, 0) or 0)) for v in versions)
        version_percentages = (
            {v: delta[v] / total for v in versions if total > 0}
            if total > 0
            else {}
        )

        return CollectionResult(
            case_id=test_case.case_id,
            prometheus_metrics={
                "traffic_distribution": delta,
                "version_percentages": version_percentages,
                "total_requests": total,
                "promql": self._split_queries.get(test_case.case_id, ""),
            },
        )

    def _collect_envoy_distribution(
        self,
        test_case: TestCase,
        pre_snapshot: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """读已有 sidecar / gateway access log，不 enable、不 rollout。"""
        svc = short_service_name(test_case.host, test_case.source_service)
        versions = list((test_case.expected_distribution or {}).keys())
        tail = max(int(test_case.request_count or 1) * 3, 200)
        logs: Dict[str, str] = {}
        try:
            for ver in versions:
                if not svc:
                    break
                part = self._envoy._impl.collect_envoy_logs(
                    test_case.case_id, svc, subset=ver, tail_lines=tail, deployment=None
                )
                logs.update(part or {})
            if svc and not versions:
                logs.update(
                    self._envoy._impl.collect_envoy_logs(
                        test_case.case_id, svc, subset=None, tail_lines=tail, deployment=None
                    ) or {}
                )
            gw = self._envoy._impl.collect_gateway_logs(test_case.case_id, tail)
            logs.update(gw or {})
            if pre_snapshot and logs:
                logs = self._envoy._diff_logs(logs, pre_snapshot)
            parser = EnvoyLogParser()
            parsed = parser.parse_logs_batch(logs)
            dist = parser.analyze_distribution(parsed, svc)
            dist["pods"] = list(logs.keys())
            return dist
        except Exception as e:
            return {"total_requests": 0, "version_distribution": {}, "error": str(e)}

    def _collect_jaeger_distribution(self, test_case: TestCase, tracing_url: str) -> Dict[str, Any]:
        svc = short_service_name(test_case.host, test_case.source_service)
        if not svc:
            return {"total_requests": 0, "version_distribution": {}, "error": "no service"}
        names = [
            f"{svc}.{self._namespace}",
            svc,
            "istio-ingressgateway.istio-system",
            "istio-ingressgateway",
        ]
        try:
            traces = []
            used = ""
            for name in names:
                traces = _fetch_jaeger_traces(tracing_url, name, limit=80)
                if traces:
                    used = name
                    break
            counts: Counter = Counter()
            for trace in traces:
                for span in trace.get("spans") or []:
                    ver = _span_version(span, svc)
                    if ver:
                        counts[ver] += 1
            total = sum(counts.values())
            percents = {k: v / total for k, v in counts.items()} if total else {}
            return {
                "total_requests": total,
                "version_distribution": dict(counts),
                "version_percentages": percents,
                "trace_count": len(traces),
                "jaeger_service": used,
            }
        except Exception as e:
            return {"total_requests": 0, "version_distribution": {}, "error": str(e)}

    def snapshot_log_lines(self, test_case: TestCase) -> dict:
        """分流也拍 sidecar 日志末行，便于打流后做增量；不会 enable access log。"""
        return self._envoy.snapshot_log_lines(test_case)

    def warmup_for_suite(self, cases: List[TestCase]) -> None:
        """分流不预热 access log（避免 sidecar rollout 打满 etcd）。"""
        others = [
            c for c in cases
            if PolicyType.TRAFFIC_SPLIT not in (c.policy_types or [])
        ]
        if others:
            self._envoy.warmup_for_suite(others)

    def snapshot_prometheus(self, test_case: TestCase) -> Optional[Dict[str, int]]:
        if not self._prometheus_url or PolicyType.TRAFFIC_SPLIT not in (test_case.policy_types or []):
            return None
        svc = short_service_name(test_case.host, test_case.source_service) or "unknown"
        versions = list((test_case.expected_distribution or {}).keys())
        try:
            data, used = query_traffic_distribution_ex(
                self._prometheus_url, svc, versions, self._namespace
            )
            self._split_queries[test_case.case_id] = used
            return data
        except Exception as e:
            print(f"  [COLLECTOR] prometheus snapshot failed: {e}")
            return None


def _span_version(span: Dict[str, Any], service: str) -> str:
    tags_raw = span.get("tags") or []
    if isinstance(tags_raw, dict):
        tags = tags_raw
    else:
        tags = {t.get("key"): t.get("value") for t in tags_raw if isinstance(t, dict) and t.get("key")}
    cluster = str(tags.get("upstream_cluster") or tags.get("node_id") or "")
    if "|" in cluster:
        parts = cluster.split("|")
        if len(parts) >= 3 and parts[2]:
            if not service or service in cluster:
                return parts[2]
    ver = str(tags.get("version") or tags.get("istio.canonical.revision") or "")
    if ver:
        return ver
    proc = span.get("process") or {}
    if isinstance(proc, dict):
        name = str(proc.get("serviceName") or "")
        if service and service in name:
            found = version_from_workload(name)
            if found != "unknown":
                return found
    return ""


def _fetch_jaeger_traces(base_url: str, service: str, limit: int = 50) -> List[Dict[str, Any]]:
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    paths = []
    env_path = os.environ.get("JAEGER_BASE_PATH", None)
    if env_path is not None:
        prefix = env_path.rstrip("/")
        paths.append(f"{base}{prefix}/api/traces" if prefix.startswith("/") else f"{base}/{prefix}/api/traces")
    paths.extend([
        f"{base}/jaeger/api/traces",
        f"{base}/api/traces",
    ])
    seen = set()
    for url in paths:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = requests.get(url, params={"service": service, "limit": limit}, timeout=8)
            if resp.status_code != 200:
                continue
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" not in ctype and not (resp.text or "").lstrip().startswith("{"):
                continue
            data = resp.json()
            traces = data.get("data") if isinstance(data, dict) else data
            if traces:
                return traces
        except Exception:
            continue
    return []
