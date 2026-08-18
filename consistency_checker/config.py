"""
全局配置管理
"""

import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict, fields


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
    traffic_split_tolerance: float = 0.1  # 流量分配容差
    statistical_confidence: float = 0.95  # 统计置信度
    
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
        self.control_plane_config_dir = self._resolve_path(self.control_plane_config_dir)
        self.data_plane_config_dir = self._resolve_path(self.data_plane_config_dir)
        self.ingress_plane_config_dir = self._resolve_path(self.ingress_plane_config_dir)
        self.test_matrix_file = self._resolve_path(self.test_matrix_file)
        self.envoy_logs_dir = self._resolve_path(self.envoy_logs_dir)
        self.http_results_dir = self._resolve_path(self.http_results_dir)
        self.verification_dir = self._resolve_path(self.verification_dir)
        self.consistency_output_dir = self._resolve_path(self.consistency_output_dir)
        self.visualization_output_dir = self._resolve_path(self.visualization_output_dir)
        self.service_dependencies_file = self._resolve_path(self.service_dependencies_file)
        self.istio_config_file = self._resolve_path(self.istio_config_file)
    
    def get_ingress_url(self, host: Optional[str] = None, port: Optional[int] = None, path: str = "/productpage") -> Optional[str]:
        """获取Ingress URL"""
        if self.ingress_url and host is None and port is None:
            return self.ingress_url
        host = host or self.ssh_host or self.k8s_host
        port = port or self.ingress_port
        if not host:
            return None
        return f"http://{host}:{port}{path}"
        
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
                "traffic_split_tolerance": self.traffic_split_tolerance,
                "statistical_confidence": self.statistical_confidence,
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
    "traffic_split_tolerance": "traffic_split_tolerance",
    "statistical_confidence": "statistical_confidence",
}

WEB_KEY_MAP = {
    "port": "web_port",
    "enable_interactive_graph": "enable_interactive_graph",
}


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
            {"key": "ingress_url", "env": "ISTIO_INGRESS_URL", "label": "Ingress 入口", "placeholder": "http://host:30476/productpage"},
            {"key": "ingress_port", "env": "INGRESS_PORT", "label": "Ingress 端口", "placeholder": "30476"},
        ],
    },
    {
        "id": "consistency",
        "title": "一致性判定",
        "hint": "之后跑流水线时生效。流量分配容差是声明权重与实测的允许偏差。",
        "fields": [
            {
                "key": "traffic_split_tolerance",
                "env": "",
                "label": "流量分配容差",
                "placeholder": "0.1",
                "hint": "0.1 表示实测权重偏离声明超过 10% 则判不一致",
            },
            {
                "key": "statistical_confidence",
                "env": "",
                "label": "统计置信度",
                "placeholder": "0.95",
                "hint": "动态抽样判定的置信水平，常用 0.95",
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

ENDPOINT_FIELDS = [field for group in SETTINGS_GROUPS for field in group["fields"]]
SECRET_KEYS = {field["key"] for field in ENDPOINT_FIELDS if field.get("secret")}
ENDPOINT_INT_KEYS = {"ssh_port", "ingress_port", "k8s_port"}
ENDPOINT_FLOAT_KEYS = {"traffic_split_tolerance", "statistical_confidence"}
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
        "ingress_url": f"http://{host}:{ingress_port}/productpage",
    }


def _clean_endpoint_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in SECRET_KEYS:
        text = str(value).strip()
        return text or None
    if key in ENDPOINT_INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if key in ENDPOINT_FLOAT_KEYS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, number))
    text = str(value).strip()
    return text or None


def apply_endpoints(cfg: GlobalConfig, data: Dict[str, Any], persist: bool = True, sync_env: bool = True) -> GlobalConfig:
    payload = data.get("values") if isinstance(data.get("values"), dict) else data
    old_host = cfg.ssh_host
    editable = [field["key"] for field in ENDPOINT_FIELDS]
    for key in editable:
        if key not in payload:
            continue
        if key in SECRET_KEYS and not str(payload.get(key) or "").strip():
            continue
        value = _clean_endpoint_value(key, payload.get(key))
        if key in ENDPOINT_INT_KEYS or key in ENDPOINT_FLOAT_KEYS:
            if value is None:
                continue
            setattr(cfg, key, value)
        elif key in SECRET_KEYS:
            setattr(cfg, key, value)
        else:
            setattr(cfg, key, value)
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

