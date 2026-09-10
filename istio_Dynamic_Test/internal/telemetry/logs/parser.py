"""
EnvoyLogParser —— 解析 Envoy access log，支持流量分布统计和重试/熔断证据检测。

支持格式：
- TEXT: [timestamp] "METHOD path PROTOCOL" code ... "authority" "upstream_host" "upstream_cluster" ...
- JSON: {"start_time":"...","upstream_cluster":"...","response_code":...}
"""

import re
import json
from collections import defaultdict
from typing import Dict, List, Any, Optional


class LogEntry:
    """单条 Envoy 访问日志解析结果。"""
    __slots__ = (
        'timestamp', 'status_code', 'request_time', 'upstream_cluster',
        'authority', 'pod_name', 'response_flags', 'grpc_status', 'request_path',
    )

    def __init__(
        self,
        timestamp='',
        status_code=0,
        request_time=0.0,
        upstream_cluster='',
        authority='',
        pod_name='',
        response_flags='',
        grpc_status=None,
        request_path='',
    ):
        self.timestamp = timestamp
        self.status_code = status_code
        self.request_time = request_time
        self.upstream_cluster = upstream_cluster
        self.authority = authority
        self.pod_name = pod_name
        self.response_flags = response_flags or ''
        self.grpc_status = grpc_status
        self.request_path = request_path or ''

    @property
    def is_error(self):
        if self.grpc_status is not None:
            try:
                return int(self.grpc_status) != 0
            except (TypeError, ValueError):
                gs = str(self.grpc_status)
                return gs not in ('0', 'OK', '-', '')
        return self.status_code >= 500 or self.status_code == 0

    @property
    def is_upstream_overflow(self):
        """response_flags=UO 表示 Upstream Overflow，熔断触发的直接证据"""
        return 'UO' in (self.response_flags or '')

    @property
    def is_grpc(self) -> bool:
        if self.grpc_status is not None:
            return True
        p = self.request_path or ''
        return 'grpc' in p.lower() or (p.count('/') >= 2 and '.' in p.split('/', 1)[0])

    @property
    def is_success(self):
        if self.grpc_status is not None:
            try:
                return int(self.grpc_status) == 0
            except (TypeError, ValueError):
                return str(self.grpc_status) in ('0', 'OK', '-')
        if self.is_grpc and 200 <= self.status_code < 300:
            return True
        return 200 <= self.status_code < 300

    @property
    def version(self):
        """从 upstream_cluster 或 pod_name 提取版本。
        - outbound|9080|v2|reviews... -> v2
        - inbound|9080|| 时从 pod_name 提取，如 reviews-v1-xxx -> v1
        """
        if self.upstream_cluster:
            parts = self.upstream_cluster.split('|')
            if len(parts) >= 3 and parts[2]:
                return parts[2]
        if self.pod_name:
            m = re.search(r'-v(\d+)-', self.pod_name)
            if m:
                return 'v' + m.group(1)
        return ''


class EnvoyLogParser:
    """Envoy access log 解析器。"""

    # TEXT 格式: [ts] "METHOD path PROTOCOL" code response_flags ... "auth" "upstream_host" upstream_cluster ...
    # 注意：upstream_cluster 可能无引号；response_flags 含 UO 表示熔断(Upstream Overflow)
    _TEXT_RE = re.compile(
        r'\[([^\]]+)\]\s+"[^"]+"\s+(\d+)\s+(\S+)\s+.*"([^"]+)"\s+"([^"]+)"\s+(\S+)(?:\s|$)'
    )

    def parse_logs_batch(self, envoy_logs: Dict[str, str]) -> Dict[str, List[LogEntry]]:
        """
        解析 envoy_logs (pod_name -> log_content)，返回 {pod_name: [LogEntry, ...]}。
        """
        result = {}
        for pod_name, content in (envoy_logs or {}).items():
            entries = self._parse_log_content(content, pod_name)
            if entries:
                result[pod_name] = entries
        return result

    def _parse_log_content(self, content: str, pod_name: str = '') -> List[LogEntry]:
        entries = []
        for line in (content or '').strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            entry = self._parse_line(line, pod_name)
            if entry:
                entries.append(entry)
        return entries

    def _parse_line(self, line: str, pod_name: str = '') -> Optional[LogEntry]:
        if line.startswith('{'):
            return self._parse_json_line(line, pod_name)
        return self._parse_text_line(line, pod_name)

    @staticmethod
    def _extract_grpc_status(d: dict) -> Optional[int]:
        for key in ('grpc_status', 'grpc-status', 'grpcStatus', 'GRPC_STATUS'):
            if key in d and d[key] not in (None, '', '-'):
                try:
                    return int(d[key])
                except (TypeError, ValueError):
                    pass
        return None

    def _parse_json_line(self, line: str, pod_name: str) -> Optional[LogEntry]:
        try:
            d = json.loads(line)
            path = str(
                d.get('path')
                or d.get('request_path')
                or d.get('uri')
                or d.get(':path', '')
            )
            return LogEntry(
                timestamp=str(d.get('start_time', d.get('timestamp', ''))),
                status_code=int(d.get('response_code', d.get('response_code', 0)) or 0),
                request_time=float(d.get('duration', d.get('request_duration', 0)) or 0) / 1000000.0,
                upstream_cluster=str(d.get('upstream_cluster', '')),
                authority=str(d.get('authority', d.get(':authority', ''))),
                pod_name=pod_name,
                response_flags=str(d.get('response_flags', '')),
                grpc_status=self._extract_grpc_status(d),
                request_path=path,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    _GRPC_STATUS_TAIL_RE = re.compile(r'grpc[_-]?status=(\d+|-)', re.I)
    _REQUEST_PATH_RE = re.compile(r'"([A-Z]+)\s+([^"]+)\s+HTTP')

    def _parse_text_line(self, line: str, pod_name: str) -> Optional[LogEntry]:
        grpc_status = None
        gm = self._GRPC_STATUS_TAIL_RE.search(line)
        if gm:
            raw = gm.group(1)
            if raw != '-':
                try:
                    grpc_status = int(raw)
                except ValueError:
                    pass

        request_path = ''
        pm = self._REQUEST_PATH_RE.search(line)
        if pm:
            request_path = pm.group(2)

        m = self._TEXT_RE.match(line)
        if m:
            ts, code, response_flags, authority, upstream_host, upstream_cluster = m.groups()
            return LogEntry(
                timestamp=ts,
                status_code=int(code),
                request_time=0.0,
                upstream_cluster=upstream_cluster or '',
                authority=authority or '',
                pod_name=pod_name,
                response_flags=response_flags or '',
                grpc_status=grpc_status,
                request_path=request_path,
            )
        return None

    def analyze_grpc_metrics(self, parsed: Dict[str, List[LogEntry]]) -> Dict[str, Any]:
        """汇总 gRPC 状态码分布与成功率（基于 Envoy 日志中的 grpc_status）。"""
        status_counts: Dict[int, int] = defaultdict(int)
        version_counts: Dict[str, int] = defaultdict(int)
        total = 0
        success = 0
        for _pod, entries in parsed.items():
            for e in entries:
                if e.grpc_status is None and not e.is_grpc:
                    continue
                total += 1
                gs = e.grpc_status
                if gs is None:
                    gs = 0 if e.is_success else -1
                status_counts[int(gs)] = status_counts.get(int(gs), 0) + 1
                if int(gs) == 0:
                    success += 1
                ver = e.version or 'unknown'
                version_counts[ver] += 1
        return {
            'total_grpc_requests': total,
            'grpc_status_distribution': {str(k): v for k, v in status_counts.items()},
            'grpc_success_rate': (success / total) if total else 0.0,
            'version_distribution': dict(version_counts),
        }

    def analyze_distribution(self, parsed: Dict[str, List[LogEntry]], svc: str) -> Dict[str, Any]:
        """
        分析流量分布，返回 total_requests, version_percentages, version_distribution。
        仅统计目标服务 svc 的出站请求（upstream_cluster 包含 svc）。
        """
        version_counts = defaultdict(int)
        total = 0
        for pod, entries in parsed.items():
            for e in entries:
                if not svc or svc in (e.upstream_cluster or '') or svc in (e.authority or ''):
                    ver = e.version or 'unknown'
                    version_counts[ver] += 1
                    total += 1
        if total == 0:
            return {'total_requests': 0, 'version_percentages': {}, 'version_distribution': {}}
        version_percentages = {k: v / total for k, v in version_counts.items()}
        return {
            'total_requests': total,
            'version_percentages': version_percentages,
            'version_distribution': dict(version_counts),
        }

    def detect_retry_evidence(
        self,
        parsed: Dict[str, List[LogEntry]],
        client_request_count: int = 0,
        service_name: str = '',
    ) -> Dict[str, Any]:
        """
        检测重试证据：backend 入站请求数 > client 请求数，或同一 request_id 多次 5xx。
        """
        all_entries = [e for entries in parsed.values() for e in entries]
        total_inbound = len(all_entries)
        retry_detected = total_inbound > client_request_count and client_request_count > 0
        return {
            'retry_detected': retry_detected,
            'total_inbound_entries': total_inbound,
            'retry_request_count': max(0, total_inbound - client_request_count),
            'indicators': [],
        }
