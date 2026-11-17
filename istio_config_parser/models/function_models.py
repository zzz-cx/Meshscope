"""
统一功能模型（Unified Function Models）
为数据平面和控制平面提供统一的数据表示，便于一致性验证
"""
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class FunctionType(Enum):
    """功能类型枚举"""
    ROUTING = "routing"  # 路由
    LOAD_BALANCING = "load_balancing"  # 负载均衡
    CIRCUIT_BREAKER = "circuit_breaker"  # 熔断
    RATE_LIMIT = "rate_limit"  # 限流
    RETRY = "retry"  # 重试
    TIMEOUT = "timeout"  # 超时
    FAULT_INJECTION = "fault_injection"  # 故障注入
    TRAFFIC_SHIFTING = "traffic_shifting"  # 流量迁移/灰度发布
    TLS = "tls"  # TLS配置
    HEADER_MANIPULATION = "header_manipulation"  # 请求头操作


class PlaneType(Enum):
    """平面类型"""
    CONTROL_PLANE = "control_plane"
    DATA_PLANE = "data_plane"


@dataclass
class FunctionModel:
    """功能模型基类"""
    function_type: FunctionType  # 功能类型
    service_name: str  # 服务名称
    namespace: str  # 命名空间
    plane_type: PlaneType  # 平面类型（控制平面/数据平面）
    raw_config: Dict[str, Any] = field(default_factory=dict)  # 原始配置引用
    
    def get_key(self) -> str:
        """生成唯一标识键"""
        return f"{self.namespace}.{self.service_name}.{self.function_type.value}"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'function_type': self.function_type.value,
            'service_name': self.service_name,
            'namespace': self.namespace,
            'plane_type': self.plane_type.value,
            'raw_config': self.raw_config
        }


@dataclass
class MatchCondition:
    """匹配条件"""
    headers: Dict[str, Any] = field(default_factory=dict)
    uri: Optional[Dict[str, str]] = None
    method: Optional[List[str]] = None
    query_params: Dict[str, Any] = field(default_factory=dict)
    source_labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'headers': self.headers,
            'uri': self.uri,
            'method': self.method,
            'query_params': self.query_params,
            'source_labels': self.source_labels
        }


@dataclass
class RouteDestination:
    """路由目标"""
    host: str  # 目标主机
    subset: Optional[str] = None  # 子集名称
    port: Optional[int] = None  # 端口
    weight: int = 100  # 权重
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'host': self.host,
            'subset': self.subset,
            'port': self.port,
            'weight': self.weight
        }


@dataclass
class RoutingFunctionModel(FunctionModel):
    """路由功能模型"""
    # 路由规则列表
    routes: List[Dict[str, Any]] = field(default_factory=list)
    
    # 每个路由包含：
    # - match: MatchCondition 匹配条件
    # - destinations: List[RouteDestination] 目标列表
    # - priority: int 优先级
    
    gateways: List[str] = field(default_factory=list)  # 关联的网关
    hosts: List[str] = field(default_factory=list)  # 主机列表
    
    def is_gateway_bound(self) -> bool:
        """是否绑定到 Gateway（配置在 ingress gateway 上）"""
        return bool(self.gateways)
    
    def add_route(self, match: Optional[MatchCondition], destinations: List[RouteDestination], priority: int = 0):
        """添加路由规则"""
        self.routes.append({
            'match': match.to_dict() if match else None,
            'destinations': [d.to_dict() for d in destinations],
            'priority': priority
        })
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'routes': self.routes,
            'gateways': self.gateways,
            'hosts': self.hosts
        })
        return base


@dataclass
class LoadBalancingFunctionModel(FunctionModel):
    """负载均衡功能模型"""
    algorithm: str = "ROUND_ROBIN"  # 负载均衡算法: ROUND_ROBIN, LEAST_CONN, RANDOM, PASSTHROUGH
    consistent_hash: Optional[Dict[str, Any]] = None  # 一致性哈希配置
    locality_lb_setting: Optional[Dict[str, Any]] = None  # 地域负载均衡
    
    # 子集配置
    subsets: List[Dict[str, Any]] = field(default_factory=list)
    # 每个子集包含: name, labels, traffic_policy
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'algorithm': self.algorithm,
            'consistent_hash': self.consistent_hash,
            'locality_lb_setting': self.locality_lb_setting,
            'subsets': self.subsets
        })
        return base


@dataclass
class ConnectionPoolSettings:
    """连接池设置"""
    # TCP连接池
    max_connections: Optional[int] = None
    connect_timeout: Optional[str] = None
    tcp_keepalive: Optional[Dict[str, Any]] = None
    
    # HTTP连接池
    http1_max_pending_requests: Optional[int] = None
    http2_max_requests: Optional[int] = None
    max_requests_per_connection: Optional[int] = None
    max_retries: Optional[int] = None
    idle_timeout: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        def _omit_unlimited(val):
            if val is None or _is_unlimited_threshold(val):
                return None
            return val

        return {
            'tcp': {
                'max_connections': _omit_unlimited(self.max_connections),
                'connect_timeout': self.connect_timeout,
                'tcp_keepalive': self.tcp_keepalive
            },
            'http': {
                'http1_max_pending_requests': _omit_unlimited(self.http1_max_pending_requests),
                'http2_max_requests': _omit_unlimited(self.http2_max_requests),
                'max_requests_per_connection': _omit_unlimited(self.max_requests_per_connection),
                'max_retries': _omit_unlimited(self.max_retries),
                'idle_timeout': self.idle_timeout
            }
        }


@dataclass
class OutlierDetection:
    """异常检测配置"""
    consecutive_5xx_errors: Optional[int] = None
    consecutive_gateway_errors: Optional[int] = None
    interval: Optional[str] = None
    base_ejection_time: Optional[str] = None
    max_ejection_percent: Optional[int] = None
    min_health_percent: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'consecutive_5xx_errors': self.consecutive_5xx_errors,
            'consecutive_gateway_errors': self.consecutive_gateway_errors,
            'interval': self.interval,
            'base_ejection_time': self.base_ejection_time,
            'max_ejection_percent': self.max_ejection_percent,
            'min_health_percent': self.min_health_percent
        }


_ENVOY_UNLIMITED = 4294967295  # Istio 未声明熔断时 Envoy 默认 max=uint32


def _is_unlimited_threshold(val: Any) -> bool:
    if val is None:
        return True
    try:
        return int(val) >= _ENVOY_UNLIMITED
    except (TypeError, ValueError):
        return True


def _connection_pool_is_declared(pool: Any) -> bool:
    """只有显式收紧过的连接池才算熔断意图，忽略 Envoy 默认无限阈值。"""
    if not pool:
        return False
    if isinstance(pool, ConnectionPoolSettings):
        vals = [
            pool.max_connections,
            pool.http1_max_pending_requests,
            pool.http2_max_requests,
            pool.max_requests_per_connection,
        ]
    elif isinstance(pool, dict):
        tcp = pool.get("tcp") if isinstance(pool.get("tcp"), dict) else pool
        http = pool.get("http") if isinstance(pool.get("http"), dict) else pool
        vals = [
            tcp.get("max_connections") or tcp.get("maxConnections"),
            http.get("http1_max_pending_requests") or http.get("http1MaxPendingRequests"),
            http.get("http2_max_requests") or http.get("http2MaxRequests"),
            http.get("max_requests_per_connection") or http.get("maxRequestsPerConnection"),
            pool.get("max_connections"),
            pool.get("http1_max_pending_requests"),
        ]
    else:
        return False
    return any(v is not None and not _is_unlimited_threshold(v) for v in vals)


def _outlier_is_declared(outlier: Any) -> bool:
    if not outlier:
        return False
    data = outlier.to_dict() if hasattr(outlier, "to_dict") else outlier
    if not isinstance(data, dict):
        return False
    return any(v not in (None, "", [], {}) for v in data.values())


@dataclass
class CircuitBreakerFunctionModel(FunctionModel):
    """熔断功能模型"""
    # 全局配置
    connection_pool: Optional[ConnectionPoolSettings] = None
    outlier_detection: Optional[OutlierDetection] = None
    
    # 子集级配置
    subset_policies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # key: subset_name, value: {connection_pool, outlier_detection}

    def has_declared_policy(self) -> bool:
        """DestinationRule 是否真的写了 connectionPool / outlierDetection。"""
        if _connection_pool_is_declared(self.connection_pool) or _outlier_is_declared(self.outlier_detection):
            return True
        for policy in (self.subset_policies or {}).values():
            if not policy:
                continue
            if _connection_pool_is_declared(policy.get("connection_pool")):
                return True
            if _outlier_is_declared(policy.get("outlier_detection")):
                return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'connection_pool': self.connection_pool.to_dict() if self.connection_pool else None,
            'outlier_detection': self.outlier_detection.to_dict() if self.outlier_detection else None,
            'subset_policies': self.subset_policies
        })
        return base


@dataclass
class RateLimitRule:
    """限流规则"""
    requests_per_unit: int  # 每单位时间的请求数
    unit: str  # 时间单位: SECOND, MINUTE, HOUR, DAY
    match_conditions: Optional[MatchCondition] = None  # 匹配条件
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'requests_per_unit': self.requests_per_unit,
            'unit': self.unit,
            'match_conditions': self.match_conditions.to_dict() if self.match_conditions else None
        }


class RateLimitType:
    """限流类型常量"""
    LOCAL = "local"   # 本地限流 envoy.filters.http.local_ratelimit
    GLOBAL = "global"  # 全局限流 envoy.filters.http.ratelimit


@dataclass
class RateLimitFunctionModel(FunctionModel):
    """限流功能模型
    
    支持两种限流机制:
    - 本地限流(LOCAL): EnvoyFilter → local_ratelimit filter, token_bucket
    - 全局限流(GLOBAL): EnvoyFilter → ratelimit filter, rate_limit_service
    """
    rules: List[RateLimitRule] = field(default_factory=list)
    
    # 限流类型: local | global
    rate_limit_type: str = RateLimitType.LOCAL
    
    # 全局限流服务配置（仅 GLOBAL 类型）
    rate_limit_service: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'rules': [r.to_dict() for r in self.rules],
            'rate_limit_type': self.rate_limit_type,
            'rate_limit_service': self.rate_limit_service
        })
        return base


@dataclass
class RetryPolicy:
    """重试策略"""
    attempts: int = 3
    per_try_timeout: Optional[str] = None
    retry_on: str = "5xx"  # 重试条件
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'attempts': self.attempts,
            'per_try_timeout': self.per_try_timeout,
            'retry_on': self.retry_on
        }


@dataclass
class RetryFunctionModel(FunctionModel):
    """重试功能模型"""
    retry_policy: Optional[RetryPolicy] = None
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'retry_policy': self.retry_policy.to_dict() if self.retry_policy else None
        })
        return base


@dataclass
class TimeoutFunctionModel(FunctionModel):
    """超时功能模型"""
    timeout: Optional[str] = None  # 超时时间
    idle_timeout: Optional[str] = None  # 空闲超时
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'timeout': self.timeout,
            'idle_timeout': self.idle_timeout
        })
        return base


@dataclass
class TrafficShiftingFunctionModel(FunctionModel):
    """流量迁移/灰度发布功能模型"""
    # 目标权重分配
    destinations: List[RouteDestination] = field(default_factory=list)

    # 子集定义
    subsets: List[Dict[str, Any]] = field(default_factory=list)
    # 每个子集: {name, version, labels}

    # 关联的网关（若 VirtualService 绑定到 Gateway，配置在 ingress gateway 上而非 sidecar）
    gateways: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'destinations': [d.to_dict() for d in self.destinations],
            'subsets': self.subsets,
            'gateways': self.gateways
        })
        return base

    def is_gateway_bound(self) -> bool:
        """是否绑定到 Gateway（配置在 ingress gateway 上）"""
        return bool(self.gateways)


@dataclass
class FaultInjectionFunctionModel(FunctionModel):
    """故障注入功能模型"""
    # 延迟注入
    delay: Optional[Dict[str, Any]] = None  # {percentage, fixed_delay}
    
    # 中断注入
    abort: Optional[Dict[str, Any]] = None  # {percentage, http_status}
    
    match_conditions: Optional[MatchCondition] = None
    
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({
            'delay': self.delay,
            'abort': self.abort,
            'match_conditions': self.match_conditions.to_dict() if self.match_conditions else None
        })
        return base


# 类型别名
AnyFunctionModel = Union[
    RoutingFunctionModel,
    LoadBalancingFunctionModel,
    CircuitBreakerFunctionModel,
    RateLimitFunctionModel,
    RetryFunctionModel,
    TimeoutFunctionModel,
    TrafficShiftingFunctionModel,
    FaultInjectionFunctionModel
]

