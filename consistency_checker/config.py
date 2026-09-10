"""
全局配置管理
"""

import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict, fields
from urllib.parse import urlparse


@dataclass
class GlobalConfig:
    """全局配置类"""
    
    # 基础路径配置
    project_root: str = field(default_factory=lambda: os.path.dirname(os.path.dirname(__file__)))
    
    # 静态分析配置
    control_plane_config_dir: str = "istio_config_parser/istio_monitor/istio_control_config"
    data_plane_config_dir: str = "istio_config_parser/istio_monitor/istio_sidecar_config"
    ingress_plane_config_dir: str = "istio_config_parser/istio_monitor/istio_ingress_config"
    
    # 动态测试配置
    test_matrix_file: str = "istio_Dynamic_Test/configs/output_matrix.json"
    envoy_logs_dir: str = "istio_Dynamic_Test/results/envoy_logs"
    http_results_dir: str = "istio_Dynamic_Test/results/http_results"
    verification_dir: str = "istio_Dynamic_Test/results/verification"
    
    # 一致性检查配置
    consistency_output_dir: str = "results/consistency"
    visualization_output_dir: str = "results/visualization"
    database_path: str = "results/meshscope.db"
    
    # Kubernetes配置（敏感信息优先从环境变量读取）
    ssh_host: Optional[str] = None
    ssh_port: int = 22
    ssh_user: Optional[str] = "root"
    ssh_password: Optional[str] = None
    k8s_host: Optional[str] = None
    k8s_port: int = 6443
    k8s_token: Optional[str] = None
    namespace: str = "default"
    
    # Ingress配置
    ingress_port: int = 30476
    ingress_url_template: str = "http://{host}:{port}/productpage"
    ingress_url: Optional[str] = None

    # 可观测与入口地址（空则按 ssh_host + 默认端口推导）
    prometheus_url: Optional[str] = None
    jaeger_url: Optional[str] = None
    zipkin_url: Optional[str] = None
    kiali_url: Optional[str] = None
    grafana_url: Optional[str] = None
    
    # 动态测试文件路径配置
    service_dependencies_file: str = "istio_Dynamic_Test/service_dependencies.json"
    istio_config_file: str = "istio_Dynamic_Test/configs/istio_config.json"
    
    # 可视化配置
    web_port: int = 8080
    enable_interactive_graph: bool = True
    
    # 阈值配置
    traffic_split_tolerance: float = 0.1  # 运行时流量权重相对容差
    statistical_confidence: float = 0.95  # 动态抽样置信度
    alignment_tau: float = 0.1  # 控制面/数据面数值对齐容差 τ
    timeout_tolerance_seconds: float = 0.5  # 超时绝对容差（秒）
    min_split_requests: int = 30  # 流量分割最少样本
    min_severity: str = "info"  # 报告最低严重级别
    check_layer1: bool = True
    check_layer2: bool = True
    check_layer3: bool = True
    report_unverified_policies: bool = True
    report_scope_gaps: bool = True
    report_partial_matched: bool = True
    check_routing: bool = True
    check_traffic_split: bool = True
    check_retry: bool = True
    check_timeout: bool = True
    check_circuit_breaker: bool = True
    check_rate_limit: bool = True
    check_fault_injection: bool = True
    check_orthogonal_minimize: bool = True
    
    # 日志配置
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # 监控器
    monitor_interval: int = 1200
    monitor_config_types: str = "routes,clusters,listeners"
    data_plane_method: str = "istioctl"
    ingress_method: str = "kubectl-exec"
    enabled_policies: Dict[str, bool] = field(default_factory=lambda: {
        "routing": True,
        "retry": True,
        "circuit_breaker": True,
        "rate_limit": True,
        "fault_injection": True,
        "orthogonal_minimize": True,
    })
    allow_load_test: bool = True
    allow_fault_injection: bool = False
    allow_rollout: bool = False
    config_file: Optional[str] = None
    
    def __post_init__(self):
        """初始化后处理：从环境变量填充敏感配置，转换相对路径为绝对路径"""
        # 敏感配置优先从环境变量读取
        if self.ssh_password is None:
            self.ssh_password = os.getenv("SSH_PASSWORD")
        if self.k8s_token is None:
            self.k8s_token = os.getenv("K8S_TOKEN")
        if self.ssh_host is None:
            self.ssh_host = os.getenv("SSH_HOST", "192.168.92.131")
        env_ssh_port = os.getenv("SSH_PORT")
        if env_ssh_port:
            try:
                self.ssh_port = int(env_ssh_port)
            except ValueError:
                pass
        if self.k8s_host is None:
            self.k8s_host = os.getenv("K8S_HOST", self.ssh_host)
        if not self.prometheus_url:
            self.prometheus_url = os.getenv("PROMETHEUS_URL") or None
        if not self.jaeger_url:
            self.jaeger_url = os.getenv("JAEGER_URL") or None
        if not self.zipkin_url:
            self.zipkin_url = os.getenv("ZIPKIN_URL") or None
        if not self.kiali_url:
            self.kiali_url = os.getenv("KIALI_URL") or None
        if not self.grafana_url:
            self.grafana_url = os.getenv("GRAFANA_URL") or None
        if not self.ingress_url:
            self.ingress_url = os.getenv("ISTIO_INGRESS_URL") or None
        if self.ingress_url:
            parsed_ing = urlparse(
                self.ingress_url if "://" in self.ingress_url else "http://" + self.ingress_url
            )
            if parsed_ing.netloc:
                self.ingress_url = f"{parsed_ing.scheme or 'http'}://{parsed_ing.netloc}"
            if parsed_ing.port:
                self.ingress_port = parsed_ing.port
        self.control_plane_config_dir = self._resolve_path(self.control_plane_config_dir)
        self.data_plane_config_dir = self._resolve_path(self.data_plane_config_dir)
        self.ingress_plane_config_dir = self._resolve_path(self.ingress_plane_config_dir)
        self.test_matrix_file = self._resolve_path(self.test_matrix_file)
        self.envoy_logs_dir = self._resolve_path(self.envoy_logs_dir)
        self.http_results_dir = self._resolve_path(self.http_results_dir)
        self.verification_dir = self._resolve_path(self.verification_dir)
        self.consistency_output_dir = self._resolve_path(self.consistency_output_dir)
        self.visualization_output_dir = self._resolve_path(self.visualization_output_dir)
        self.database_path = self._resolve_path(self.database_path)
        self.service_dependencies_file = self._resolve_path(self.service_dependencies_file)
        self.istio_config_file = self._resolve_path(self.istio_config_file)
    
    def get_ingress_url(self, host: Optional[str] = None, port: Optional[int] = None, path: str = "") -> Optional[str]:
        """Ingress origin，不含 /productpage。业务 path 由测试用例拼接。"""
        from istio_Dynamic_Test.internal.traffic.entry import normalize_ingress_base, resolve_ingress_base

        if host is None and port is None:
            return resolve_ingress_base(self.ingress_url) or None
        host = host or self.ssh_host or self.k8s_host
        port = port or self.ingress_port
        if not host:
            return None
        extra = path if path and path != "/" else ""
        if extra and not extra.startswith("/"):
            extra = "/" + extra
        return normalize_ingress_base(f"http://{host}:{port}") + extra

    def sync_enabled_policies(self) -> None:
        """把一致性功能开关同步到动态测试 enabled_policies。"""
        policies = dict(self.enabled_policies or {})
        for attr, name in POLICY_CHECK_TO_ENABLED.items():
            policies[name] = bool(getattr(self, attr, True))
        self.enabled_policies = policies

    def allows_finding(self, finding: Any) -> bool:
        """按运行时配置决定是否保留一条检验记录。"""
        layer = str(getattr(finding, "layer", "") or "")
        itype = str(getattr(finding, "inconsistency_type", "") or "")
        if layer == "layer1" and not self.check_layer1:
            return False
        if layer == "layer2" and not self.check_layer2:
            return False
        if layer == "layer3" and not self.check_layer3:
            return False
        if itype == "partial_matched" and not self.report_partial_matched:
            return False
        if itype == "policy_not_verified" and not self.report_unverified_policies:
            return False
        if itype == "scope_mismatch" and not self.report_scope_gaps:
            return False
        if itype == "timeout_mismatch" and not self.check_timeout:
            return False
        if itype == "traffic_split_drift" and not self.check_traffic_split:
            return False
        if itype in {"matched", "dynamic_passed", "dynamic_skipped"}:
            pass
        else:
            severity = getattr(finding, "severity", "info")
            sev_name = severity.value if hasattr(severity, "value") else str(severity or "info")
            if _SEVERITY_RANK.get(sev_name.lower(), 0) < _SEVERITY_RANK.get((self.min_severity or "info").lower(), 0):
                return False
        ftype = str(getattr(finding, "function_type", "") or "").lower()
        attr = _FUNCTION_CHECK_ATTR.get(ftype)
        if attr and not bool(getattr(self, attr, True)):
            return False
        if itype == "traffic_split_drift":
            samples = _sample_count(finding)
            if samples is not None and samples < int(self.min_split_requests or 0):
                return False
        return True
        
    def _resolve_path(self, path: str) -> str:
        """将相对路径转换为绝对路径"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.project_root, path)
    
    def _relpath(self, path: str) -> str:
        if not path:
            return path
        root = os.path.abspath(self.project_root)
        abs_path = os.path.abspath(path)
        try:
            rel = os.path.relpath(abs_path, root)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
        return path.replace("\\", "/")

    @classmethod
    def from_file(cls, config_file: str) -> "GlobalConfig":
        with open(config_file, "r", encoding="utf-8") as f:
            config_dict = json.load(f)
        flat = flatten_config_dict(config_dict)
        flat.pop("project_root", None)
        flat.pop("config_file", None)
        valid = {item.name for item in fields(cls)}
        inst = cls(**{k: v for k, v in flat.items() if k in valid})
        inst.config_file = os.path.abspath(config_file)
        return inst

    def to_nested_dict(self) -> Dict[str, Any]:
        return {
            "namespace": self.namespace,
            "log_level": self.log_level,
            "cluster": {
                "ssh_host": self.ssh_host,
                "ssh_port": self.ssh_port,
                "ssh_user": self.ssh_user,
                "ssh_password": None,
                "k8s_host": self.k8s_host,
                "k8s_port": self.k8s_port,
                "k8s_token": None,
            },
            "observability": {
                "prometheus_url": self.prometheus_url or "",
                "jaeger_url": self.jaeger_url or "",
                "zipkin_url": self.zipkin_url or "",
                "kiali_url": self.kiali_url or "",
                "grafana_url": self.grafana_url or "",
                "ingress_url": self.ingress_url or "",
                "ingress_port": self.ingress_port,
            },
            "static": {
                "control_plane_config_dir": self._relpath(self.control_plane_config_dir),
                "data_plane_config_dir": self._relpath(self.data_plane_config_dir),
                "ingress_plane_config_dir": self._relpath(self.ingress_plane_config_dir),
            },
            "dynamic": {
                "istio_config_file": self._relpath(self.istio_config_file),
                "service_dependencies_file": self._relpath(self.service_dependencies_file),
                "test_matrix_file": self._relpath(self.test_matrix_file),
                "envoy_logs_dir": self._relpath(self.envoy_logs_dir),
                "http_results_dir": self._relpath(self.http_results_dir),
                "verification_dir": self._relpath(self.verification_dir),
                "enabled_policies": dict(self.enabled_policies or {}),
                "allow_load_test": bool(self.allow_load_test),
                "allow_fault_injection": bool(self.allow_fault_injection),
                "allow_rollout": bool(self.allow_rollout),
            },
            "monitor": {
                "interval": self.monitor_interval,
                "config_types": self.monitor_config_types,
                "data_plane_method": self.data_plane_method,
                "ingress_method": self.ingress_method,
            },
            "consistency": {
                "output_dir": self._relpath(self.consistency_output_dir),
                "visualization_output_dir": self._relpath(self.visualization_output_dir),
                "database_path": self._relpath(self.database_path),
                "traffic_split_tolerance": self.traffic_split_tolerance,
                "statistical_confidence": self.statistical_confidence,
                "alignment_tau": self.alignment_tau,
                "timeout_tolerance_seconds": self.timeout_tolerance_seconds,
                "min_split_requests": self.min_split_requests,
                "min_severity": self.min_severity,
                "check_layer1": self.check_layer1,
                "check_layer2": self.check_layer2,
                "check_layer3": self.check_layer3,
                "report_unverified_policies": self.report_unverified_policies,
                "report_scope_gaps": self.report_scope_gaps,
                "report_partial_matched": self.report_partial_matched,
                "check_routing": self.check_routing,
                "check_traffic_split": self.check_traffic_split,
                "check_retry": self.check_retry,
                "check_timeout": self.check_timeout,
                "check_circuit_breaker": self.check_circuit_breaker,
                "check_rate_limit": self.check_rate_limit,
                "check_fault_injection": self.check_fault_injection,
                "check_orthogonal_minimize": self.check_orthogonal_minimize,
            },
            "web": {
                "port": self.web_port,
                "enable_interactive_graph": self.enable_interactive_graph,
            },
        }

    def to_file(self, config_file: str):
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(self.to_nested_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        self.config_file = os.path.abspath(config_file)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


NESTED_SECTIONS = {
    "cluster": (
        "ssh_host", "ssh_port", "ssh_user", "ssh_password",
        "k8s_host", "k8s_port", "k8s_token",
    ),
    "observability": (
        "prometheus_url", "jaeger_url", "zipkin_url", "kiali_url",
        "grafana_url", "ingress_url", "ingress_port",
    ),
    "static": (
        "control_plane_config_dir", "data_plane_config_dir", "ingress_plane_config_dir",
    ),
    "dynamic": (
        "istio_config_file", "service_dependencies_file", "test_matrix_file",
        "envoy_logs_dir", "http_results_dir", "verification_dir", "enabled_policies",
        "allow_load_test", "allow_fault_injection", "allow_rollout",
    ),
}

MONITOR_KEY_MAP = {
    "interval": "monitor_interval",
    "config_types": "monitor_config_types",
    "data_plane_method": "data_plane_method",
    "ingress_method": "ingress_method",
}

CONSISTENCY_KEY_MAP = {
    "output_dir": "consistency_output_dir",
    "visualization_output_dir": "visualization_output_dir",
    "database_path": "database_path",
    "traffic_split_tolerance": "traffic_split_tolerance",
    "statistical_confidence": "statistical_confidence",
    "alignment_tau": "alignment_tau",
    "timeout_tolerance_seconds": "timeout_tolerance_seconds",
    "min_split_requests": "min_split_requests",
    "min_severity": "min_severity",
    "check_layer1": "check_layer1",
    "check_layer2": "check_layer2",
    "check_layer3": "check_layer3",
    "report_unverified_policies": "report_unverified_policies",
    "report_scope_gaps": "report_scope_gaps",
    "report_partial_matched": "report_partial_matched",
    "check_routing": "check_routing",
    "check_traffic_split": "check_traffic_split",
    "check_retry": "check_retry",
    "check_timeout": "check_timeout",
    "check_circuit_breaker": "check_circuit_breaker",
    "check_rate_limit": "check_rate_limit",
    "check_fault_injection": "check_fault_injection",
    "check_orthogonal_minimize": "check_orthogonal_minimize",
}

WEB_KEY_MAP = {
    "port": "web_port",
    "enable_interactive_graph": "enable_interactive_graph",
}

POLICY_CHECK_TO_ENABLED = {
    "check_routing": "routing",
    "check_retry": "retry",
    "check_circuit_breaker": "circuit_breaker",
    "check_rate_limit": "rate_limit",
    "check_fault_injection": "fault_injection",
    "check_orthogonal_minimize": "orthogonal_minimize",
}

_FUNCTION_CHECK_ATTR = {
    "routing": "check_routing",
    "traffic_split": "check_traffic_split",
    "traffic_shifting": "check_traffic_split",
    "retry": "check_retry",
    "timeout": "check_timeout",
    "circuit_breaker": "check_circuit_breaker",
    "rate_limit": "check_rate_limit",
    "fault_injection": "check_fault_injection",
}

_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

ALLOWED_SEVERITY = set(_SEVERITY_RANK)


def _sample_count(finding: Any) -> Optional[int]:
    blobs = []
    for attr in ("dynamic_observation", "details", "s_rt"):
        obj = getattr(finding, attr, None)
        if not isinstance(obj, dict):
            continue
        blobs.append(obj)
        for nested_key in ("actual", "observation", "metrics", "constraint"):
            nested = obj.get(nested_key)
            if isinstance(nested, dict):
                blobs.append(nested)
    for blob in blobs:
        for key in ("total", "requests", "sample_count", "count", "n"):
            if blob.get(key) is None:
                continue
            try:
                return int(blob[key])
            except (TypeError, ValueError):
                continue
    return None


def flatten_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = any(key in data for key in ("cluster", "static", "dynamic", "monitor", "observability"))
    if not nested:
        return dict(data)
    flat: Dict[str, Any] = {}
    for key in ("namespace", "log_level", "log_file"):
        if key in data:
            flat[key] = data[key]
    for section, keys in NESTED_SECTIONS.items():
        block = data.get(section) or {}
        if not isinstance(block, dict):
            continue
        for key in keys:
            if key in block:
                flat[key] = block[key]
    for section, mapping in (
        ("monitor", MONITOR_KEY_MAP),
        ("consistency", CONSISTENCY_KEY_MAP),
        ("web", WEB_KEY_MAP),
    ):
        block = data.get(section) or {}
        if not isinstance(block, dict):
            continue
        for src, dest in mapping.items():
            if src in block:
                flat[dest] = block[src]
    return flat


def default_config_path(project_root: Optional[str] = None) -> str:
    root = project_root or os.path.dirname(os.path.dirname(__file__))
    return os.path.join(root, "configpilot.json")


# 页面可改的运行时配置；保存后写回 configpilot.json（密钥只进内存，不写文件）
SETTINGS_GROUPS = [
    {
        "id": "cluster",
        "title": "集群",
        "hint": "SSH 与 Kubernetes 访问信息。保存后立即用于连通探测和采集。",
        "fields": [
            {"key": "namespace", "env": "", "label": "命名空间", "placeholder": "default"},
            {"key": "ssh_host", "env": "SSH_HOST", "label": "SSH / 集群主机", "placeholder": "192.168.92.131"},
            {"key": "ssh_port", "env": "SSH_PORT", "label": "SSH 端口", "placeholder": "22"},
            {"key": "ssh_user", "env": "SSH_USER", "label": "SSH 用户", "placeholder": "root"},
            {"key": "ssh_password", "env": "SSH_PASSWORD", "label": "SSH 密码", "placeholder": "留空则不修改", "secret": True},
            {"key": "k8s_host", "env": "K8S_HOST", "label": "Kubernetes 主机", "placeholder": "192.168.92.131"},
            {"key": "k8s_port", "env": "K8S_PORT", "label": "Kubernetes API 端口", "placeholder": "6443"},
            {"key": "k8s_token", "env": "K8S_TOKEN", "label": "Kubernetes Token", "placeholder": "留空则不修改", "secret": True},
        ],
    },
    {
        "id": "observability",
        "title": "可观测性",
        "hint": "Prometheus、链路追踪和其他控制台地址。可先改主机再点「按主机填充」。",
        "fields": [
            {"key": "prometheus_url", "env": "PROMETHEUS_URL", "label": "Prometheus", "placeholder": "http://host:31012"},
            {"key": "jaeger_url", "env": "JAEGER_URL", "label": "Jaeger", "placeholder": "http://host:16686"},
            {"key": "zipkin_url", "env": "ZIPKIN_URL", "label": "Zipkin", "placeholder": "http://host:9411"},
            {"key": "kiali_url", "env": "KIALI_URL", "label": "Kiali", "placeholder": "http://host:20001"},
            {"key": "grafana_url", "env": "GRAFANA_URL", "label": "Grafana", "placeholder": "http://host:3000"},
            {"key": "ingress_url", "env": "ISTIO_INGRESS_URL", "label": "Ingress 入口", "placeholder": "http://host:32469"},
            {"key": "ingress_port", "env": "INGRESS_PORT", "label": "Ingress 端口", "placeholder": "32469"},
        ],
    },
    {
        "id": "consistency",
        "title": "一致性判定",
        "wide": True,
        "hint": "保存后写回 configpilot.json，下次静态对齐和一致性检查立即按这些阈值与开关执行。",
        "fields": [
            {"type": "heading", "label": "判定阈值"},
            {
                "key": "traffic_split_tolerance",
                "env": "",
                "label": "流量分配容差",
                "placeholder": "0.1",
                "hint": "运行时实测权重相对声明权重的允许偏差。0.1 表示偏离超过 10% 判为流量分割漂移。",
            },
            {
                "key": "alignment_tau",
                "env": "",
                "label": "平面对齐容差 τ",
                "placeholder": "0.1",
                "hint": "控制面 Sdecl 与数据面 Sdp 比较数值约束时的相对容差，独立于运行时流量容差。",
            },
            {
                "key": "timeout_tolerance_seconds",
                "env": "",
                "label": "超时绝对容差（秒）",
                "placeholder": "0.5",
                "hint": "timeout 字段差值不超过该秒数时不判超时不一致，避免 2s 与 2.05s 一类抖动。",
            },
            {
                "key": "statistical_confidence",
                "env": "",
                "label": "统计置信度",
                "placeholder": "0.95",
                "hint": "动态抽样判定的置信水平，常用 0.95。",
            },
            {
                "key": "min_split_requests",
                "env": "",
                "label": "流量分割最少样本",
                "placeholder": "30",
                "hint": "观测请求数低于该值时不报流量分割漂移，避免样本过少造成误报。",
            },
            {
                "key": "min_severity",
                "env": "",
                "type": "select",
                "label": "最低报告级别",
                "hint": "低于该级别的检验记录不会写入报告。",
                "options": [
                    {"value": "info", "label": "info（全部）"},
                    {"value": "low", "label": "low"},
                    {"value": "medium", "label": "medium"},
                    {"value": "high", "label": "high"},
                    {"value": "critical", "label": "critical"},
                ],
            },
            {"type": "heading", "label": "检验层次"},
            {
                "key": "check_layer1",
                "type": "checkbox",
                "label": "第一层 · 控制面 / 数据面对齐",
                "hint": "比较 YAML 声明与 Envoy dump 是否对齐。",
            },
            {
                "key": "check_layer2",
                "type": "checkbox",
                "label": "第二层 · 运行时行为",
                "hint": "用动态测试观测核对路由、分割、重试、超时等是否按声明生效。",
            },
            {
                "key": "check_layer3",
                "type": "checkbox",
                "label": "第三层 · 跨资源冲突",
                "hint": "检查 subset 缺失、Gateway 选择器、路由优先级等配置冲突。",
            },
            {"type": "heading", "label": "报告内容"},
            {
                "key": "report_partial_matched",
                "type": "checkbox",
                "label": "报告部分匹配",
                "hint": "平面对齐中仅部分字段超出容差 τ 的记录。",
            },
            {
                "key": "report_unverified_policies",
                "type": "checkbox",
                "label": "报告未验证策略",
                "hint": "声明了策略但没有对应动态测试覆盖。",
            },
            {
                "key": "report_scope_gaps",
                "type": "checkbox",
                "label": "报告作用范围缺口",
                "hint": "策略作用的 subset 未被测试覆盖。",
            },
            {"type": "heading", "label": "检查功能"},
            {
                "key": "check_routing",
                "type": "checkbox",
                "label": "路由",
            },
            {
                "key": "check_traffic_split",
                "type": "checkbox",
                "label": "流量分割",
            },
            {
                "key": "check_retry",
                "type": "checkbox",
                "label": "重试",
            },
            {
                "key": "check_timeout",
                "type": "checkbox",
                "label": "超时",
            },
            {
                "key": "check_circuit_breaker",
                "type": "checkbox",
                "label": "熔断",
            },
            {
                "key": "check_rate_limit",
                "type": "checkbox",
                "label": "限流",
            },
            {
                "key": "check_fault_injection",
                "type": "checkbox",
                "label": "故障注入",
            },
            {
                "key": "check_orthogonal_minimize",
                "type": "checkbox",
                "label": "正交用例压缩",
                "hint": "同时写入动态测试 enabled_policies，控制是否做正交最小化。",
            },
        ],
    },
    {
        "id": "dynamic",
        "title": "动态验证开关",
        "wide": True,
        "hint": "完整流水线第二阶段会真正打入探测流量。路由、分流和限流基线始终尽量打入；高压、故障注入、rollout 需单独打开。关闭后对应用例会跳过并写明原因。",
        "fields": [
            {
                "key": "allow_load_test",
                "type": "checkbox",
                "label": "高压测试",
                "hint": "关闭后跳过限流高压、连接池打满。限流基线仍会发少量请求。",
            },
            {
                "key": "allow_fault_injection",
                "type": "checkbox",
                "label": "故障注入",
                "hint": "关闭后不会改 VirtualService 注入 abort/delay。熔断（outlier）、超时、重试无法诱发异常，将跳过动态验证。",
            },
            {
                "key": "allow_rollout",
                "type": "checkbox",
                "label": "允许 rollout",
                "hint": "关闭后不会 patch Deployment / 重启 sidecar 来打开 Envoy access log。etcd 不稳时请保持关闭。",
            },
        ],
    },
]

ENDPOINT_ENV = {
    "ssh_host": "SSH_HOST",
    "ssh_port": "SSH_PORT",
    "ssh_user": "SSH_USER",
    "ssh_password": "SSH_PASSWORD",
    "k8s_host": "K8S_HOST",
    "k8s_port": "K8S_PORT",
    "k8s_token": "K8S_TOKEN",
    "prometheus_url": "PROMETHEUS_URL",
    "jaeger_url": "JAEGER_URL",
    "zipkin_url": "ZIPKIN_URL",
    "kiali_url": "KIALI_URL",
    "grafana_url": "GRAFANA_URL",
    "ingress_url": "ISTIO_INGRESS_URL",
    "ingress_port": "INGRESS_PORT",
}

ENDPOINT_FIELDS = [field for group in SETTINGS_GROUPS for field in group["fields"] if field.get("key")]
SECRET_KEYS = {field["key"] for field in ENDPOINT_FIELDS if field.get("secret")}
ENDPOINT_INT_KEYS = {"ssh_port", "ingress_port", "k8s_port", "min_split_requests"}
ENDPOINT_RATIO_KEYS = {"traffic_split_tolerance", "statistical_confidence", "alignment_tau"}
ENDPOINT_UNBOUNDED_FLOAT_KEYS = {"timeout_tolerance_seconds"}
ENDPOINT_FLOAT_KEYS = ENDPOINT_RATIO_KEYS | ENDPOINT_UNBOUNDED_FLOAT_KEYS
ENDPOINT_BOOL_KEYS = {
    field["key"] for field in ENDPOINT_FIELDS if field.get("type") == "checkbox"
}
ENDPOINT_SELECT_KEYS = {
    field["key"] for field in ENDPOINT_FIELDS if field.get("type") == "select"
}
DEFAULT_PROM_PORT = 31012
DEFAULT_JAEGER_PORT = 16686
DEFAULT_ZIPKIN_PORT = 9411
DEFAULT_KIALI_PORT = 20001
DEFAULT_GRAFANA_PORT = 3000

_global_config: Optional[GlobalConfig] = None


def derived_endpoint_urls(host: str, ingress_port: int = 30476) -> Dict[str, str]:
    if not host:
        return {}
    return {
        "prometheus_url": f"http://{host}:{DEFAULT_PROM_PORT}",
        "jaeger_url": f"http://{host}:{DEFAULT_JAEGER_PORT}",
        "zipkin_url": f"http://{host}:{DEFAULT_ZIPKIN_PORT}",
        "kiali_url": f"http://{host}:{DEFAULT_KIALI_PORT}",
        "grafana_url": f"http://{host}:{DEFAULT_GRAFANA_PORT}",
        "ingress_url": f"http://{host}:{ingress_port}",
    }


def _clean_endpoint_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in SECRET_KEYS:
        text = str(value).strip()
        return text or None
    if key in ENDPOINT_BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if key in ENDPOINT_INT_KEYS:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None
    if key in ENDPOINT_UNBOUNDED_FLOAT_KEYS:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
    if key in ENDPOINT_RATIO_KEYS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, number))
    if key in ENDPOINT_SELECT_KEYS:
        text = str(value).strip().lower()
        if key == "min_severity":
            return text if text in ALLOWED_SEVERITY else None
        return text or None
    text = str(value).strip()
    return text or None


def apply_endpoints(cfg: GlobalConfig, data: Dict[str, Any], persist: bool = True, sync_env: bool = True) -> GlobalConfig:
    payload = data.get("values") if isinstance(data.get("values"), dict) else data
    old_host = cfg.ssh_host
    editable = [field["key"] for field in ENDPOINT_FIELDS]
    numeric_keys = ENDPOINT_INT_KEYS | ENDPOINT_FLOAT_KEYS | ENDPOINT_SELECT_KEYS
    for key in editable:
        if key not in payload:
            continue
        if key in SECRET_KEYS and not str(payload.get(key) or "").strip():
            continue
        value = _clean_endpoint_value(key, payload.get(key))
        if key in numeric_keys:
            if value is None:
                continue
            setattr(cfg, key, value)
        elif key in ENDPOINT_BOOL_KEYS:
            setattr(cfg, key, bool(value))
        elif key in SECRET_KEYS:
            setattr(cfg, key, value)
        else:
            setattr(cfg, key, value)
    cfg.sync_enabled_policies()
    if "k8s_host" not in payload and cfg.ssh_host and (not cfg.k8s_host or cfg.k8s_host == old_host):
        cfg.k8s_host = cfg.ssh_host
    if sync_env:
        for key, env_name in ENDPOINT_ENV.items():
            value = getattr(cfg, key, None)
            if value is None or value == "":
                if key in SECRET_KEYS:
                    continue
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = str(value)
    if persist:
        path = cfg.config_file or default_config_path(cfg.project_root)
        cfg.to_file(path)
    return cfg


def export_endpoints(cfg: GlobalConfig) -> Dict[str, Any]:
    host = cfg.ssh_host or ""
    derived = derived_endpoint_urls(host, cfg.ingress_port or 30476)
    values = {
        "namespace": cfg.namespace or "default",
        "ssh_host": cfg.ssh_host or "",
        "ssh_port": cfg.ssh_port or 22,
        "ssh_user": cfg.ssh_user or "root",
        "ssh_password": "",
        "k8s_host": cfg.k8s_host or "",
        "k8s_port": cfg.k8s_port or 6443,
        "k8s_token": "",
        "prometheus_url": cfg.prometheus_url or derived.get("prometheus_url", ""),
        "jaeger_url": cfg.jaeger_url or derived.get("jaeger_url", ""),
        "zipkin_url": cfg.zipkin_url or "",
        "kiali_url": cfg.kiali_url or derived.get("kiali_url", ""),
        "grafana_url": cfg.grafana_url or derived.get("grafana_url", ""),
        "ingress_url": cfg.ingress_url or derived.get("ingress_url", ""),
        "ingress_port": cfg.ingress_port or 30476,
        "traffic_split_tolerance": cfg.traffic_split_tolerance,
        "statistical_confidence": cfg.statistical_confidence,
        "alignment_tau": cfg.alignment_tau,
        "timeout_tolerance_seconds": cfg.timeout_tolerance_seconds,
        "min_split_requests": cfg.min_split_requests,
        "min_severity": cfg.min_severity or "info",
        "check_layer1": bool(cfg.check_layer1),
        "check_layer2": bool(cfg.check_layer2),
        "check_layer3": bool(cfg.check_layer3),
        "report_unverified_policies": bool(cfg.report_unverified_policies),
        "report_scope_gaps": bool(cfg.report_scope_gaps),
        "report_partial_matched": bool(cfg.report_partial_matched),
        "check_routing": bool(cfg.check_routing),
        "check_traffic_split": bool(cfg.check_traffic_split),
        "check_retry": bool(cfg.check_retry),
        "check_timeout": bool(cfg.check_timeout),
        "check_circuit_breaker": bool(cfg.check_circuit_breaker),
        "check_rate_limit": bool(cfg.check_rate_limit),
        "check_fault_injection": bool(cfg.check_fault_injection),
        "check_orthogonal_minimize": bool(cfg.check_orthogonal_minimize),
        "allow_load_test": bool(cfg.allow_load_test),
        "allow_fault_injection": bool(cfg.allow_fault_injection),
        "allow_rollout": bool(cfg.allow_rollout),
    }
    return {
        "values": values,
        "groups": SETTINGS_GROUPS,
        "fields": ENDPOINT_FIELDS,
        "derived": derived,
        "file": cfg.config_file or default_config_path(cfg.project_root),
        "secrets": {
            "ssh_password": bool(cfg.ssh_password),
            "k8s_token": bool(cfg.k8s_token),
        },
    }


def fill_args_from_config(args: Any, mapping: Dict[str, str]) -> None:
    """把 argparse 里空着的参数填成 configpilot.json 中的值。"""
    cfg = get_config()
    for dest, attr in mapping.items():
        current = getattr(args, dest, None)
        if current not in (None, ""):
            continue
        value = getattr(cfg, attr, None)
        if value not in (None, ""):
            setattr(args, dest, value)


def get_config() -> GlobalConfig:
    global _global_config
    if _global_config is None:
        path = os.getenv("CONFIGPILOT_CONFIG") or default_config_path()
        if os.path.isfile(path):
            _global_config = GlobalConfig.from_file(path)
        else:
            _global_config = GlobalConfig()
            _global_config.config_file = path
    return _global_config


def set_config(config: GlobalConfig):
    global _global_config
    _global_config = config


def load_config_from_file(config_file: str):
    config = GlobalConfig.from_file(config_file)
    set_config(config)
    return config

