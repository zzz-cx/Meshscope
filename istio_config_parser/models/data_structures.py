from typing import Dict, List, Any, TypedDict, Optional, Union

class ServicePort(TypedDict):
    name: str
    port: int
    targetPort: int
    protocol: str

class ServiceSelector(TypedDict):
    app: str

class BaseService(TypedDict):
    name: str
    namespace: str
    type: str
    ports: List[ServicePort]
    selector: Dict[str, str]
    labels: Dict[str, str]
    annotations: Dict[str, str]
    clusterIP: str
    sessionAffinity: str

class GatewayInfo(TypedDict):
    name: str
    type: str
    virtualService: str
    namespace: str

class RouteRule(TypedDict):
    name: str
    namespace: str
    rules: List[Dict[str, Any]]

class HttpConnectionPool(TypedDict, total=False):
    http1MaxPendingRequests: int
    http2MaxRequests: int
    maxRequestsPerConnection: int
    maxRetries: int

class TcpConnectionPool(TypedDict, total=False):
    maxConnections: int
    connectTimeout: str

class ConnectionPoolConfig(TypedDict, total=False):
    http: HttpConnectionPool
    tcp: TcpConnectionPool

class OutlierDetectionConfig(TypedDict, total=False):
    baseEjectionTime: str
    consecutive5xxErrors: int
    interval: str
    maxEjectionPercent: int
    minHealthPercent: int

class CircuitBreakerPolicy(TypedDict, total=False):
    connectionPool: ConnectionPoolConfig
    outlierDetection: OutlierDetectionConfig

class CircuitBreakerConfig(TypedDict):
    global_: Optional[CircuitBreakerPolicy]
    subsets: Dict[str, Optional[CircuitBreakerPolicy]]

class TrafficPolicyConfig(TypedDict):
    connectionPool: ConnectionPoolConfig
    outlierDetection: OutlierDetectionConfig

class SubsetInfo(TypedDict):
    name: str
    version: str
    labels: Dict[str, str]
    trafficPolicy: Optional[TrafficPolicyConfig]

class WeightInfo(TypedDict):
    weight: int
    namespace: str

class ServiceRelation(TypedDict):
    incomingVirtualServices: List[RouteRule]
    subsets: List[SubsetInfo]
    rateLimit: List[Dict[str, Any]]
    gateways: List[GatewayInfo]
    weights: Dict[str, WeightInfo]
    trafficPolicy: Optional[TrafficPolicyConfig]
    circuitBreaker: Optional[CircuitBreakerConfig]

class ServiceConfiguration(TypedDict):
    virtualServices: List[Dict[str, Any]]
    destinationRules: List[Dict[str, Any]]
    envoyFilters: List[Dict[str, Any]]
    weights: Dict[str, WeightInfo]
    circuitBreaker: Optional[CircuitBreakerConfig]

class ControlPlaneResult(TypedDict):
    services: List[BaseService]
    serviceRelations: Dict[str, ServiceRelation]
    configurations: Dict[str, ServiceConfiguration]

# 数据平面相关数据结构
class DataPlaneRoute(TypedDict):
    service: str
    port: str
    subset: Optional[str]

class DataPlaneServiceRelation(TypedDict):
    inbound: List[Dict[str, Any]]
    outbound: List[DataPlaneRoute]
    weights: Dict[str, int]

class DataPlaneResult(TypedDict):
    serviceRelations: Dict[str, DataPlaneServiceRelation]

# 常量定义
DEFAULT_NAMESPACE = "default"
DEFAULT_SERVICE_TYPE = "service"
DEFAULT_GATEWAY_TYPE = "ingress"

class OutboundRoute(TypedDict):
    service: str
    port: str
    subset: Optional[str]

class ServiceConfiguration(TypedDict):
    virtualServices: List[Dict[str, Any]]
    destinationRules: List[Dict[str, Any]]
    envoyFilters: List[Dict[str, Any]]
    weights: Dict[str, WeightInfo] 