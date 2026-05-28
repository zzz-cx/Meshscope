"""
全局配置管理
"""

import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class GlobalConfig:
    """全局配置类"""
    
    # 基础路径配置
    project_root: str = field(default_factory=lambda: os.path.dirname(os.path.dirname(__file__)))
    
    # 静态分析配置
    control_plane_config_dir: str = "istio_config_parser/istio_monitor/istio_control_config"
    data_plane_config_dir: str = "istio_config_parser/istio_monitor/istio_sidecar_config"
    
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
    ssh_user: Optional[str] = "root"
    ssh_password: Optional[str] = None
    k8s_host: Optional[str] = None
    k8s_port: int = 6443
    k8s_token: Optional[str] = None
    namespace: str = "default"
    
    # Ingress配置
    ingress_port: int = 30476
    ingress_url_template: str = "http://{host}:{port}/productpage"
    
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
    
    def __post_init__(self):
        """初始化后处理：从环境变量填充敏感配置，转换相对路径为绝对路径"""
        # 敏感配置优先从环境变量读取
        if self.ssh_password is None:
            self.ssh_password = os.getenv("SSH_PASSWORD")
        if self.k8s_token is None:
            self.k8s_token = os.getenv("K8S_TOKEN")
        if self.ssh_host is None:
            self.ssh_host = os.getenv("SSH_HOST", "192.168.92.131")
        if self.k8s_host is None:
            self.k8s_host = os.getenv("K8S_HOST", self.ssh_host)
        self.control_plane_config_dir = self._resolve_path(self.control_plane_config_dir)
        self.data_plane_config_dir = self._resolve_path(self.data_plane_config_dir)
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
    
    @classmethod
    def from_file(cls, config_file: str) -> 'GlobalConfig':
        """从JSON配置文件加载配置"""
        with open(config_file, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        return cls(**config_dict)
    
    def to_file(self, config_file: str):
        """保存配置到JSON文件"""
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


# 全局配置单例
_global_config: Optional[GlobalConfig] = None


def get_config() -> GlobalConfig:
    """获取全局配置单例"""
    global _global_config
    if _global_config is None:
        _global_config = GlobalConfig()
    return _global_config


def set_config(config: GlobalConfig):
    """设置全局配置"""
    global _global_config
    _global_config = config


def load_config_from_file(config_file: str):
    """从文件加载全局配置"""
    config = GlobalConfig.from_file(config_file)
    set_config(config)
    return config


