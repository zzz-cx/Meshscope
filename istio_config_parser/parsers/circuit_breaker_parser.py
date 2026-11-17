"""
熔断功能解析器
解析控制平面和数据平面的熔断配置，生成统一的CircuitBreakerFunctionModel

Istio→Envoy 语义映射（控制平面与数据平面实际匹配）:
  DestinationRule.trafficPolicy.connectionPool.tcp.maxConnections
    → clusters[].cluster.circuit_breakers.thresholds[0].max_connections
  DestinationRule.trafficPolicy.connectionPool.http.http1MaxPendingRequests
    → clusters[].cluster.circuit_breakers.thresholds[0].max_pending_requests
  DestinationRule.trafficPolicy.connectionPool.http.http2MaxRequests
    → clusters[].cluster.circuit_breakers.thresholds[0].max_requests
  DestinationRule.trafficPolicy.connectionPool.http.maxRequestsPerConnection
    → typed_extension_protocol_options[HttpProtocolOptions]
       .common_http_protocol_options.max_requests_per_connection
  DestinationRule.trafficPolicy.outlierDetection
    → clusters[].cluster.outlier_detection
  Envoy uint32 默认 4294967295 视为未声明，不参与对齐
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.models.function_models import (
    CircuitBreakerFunctionModel, FunctionType, PlaneType,
    ConnectionPoolSettings, OutlierDetection,
    _connection_pool_is_declared,
    _is_unlimited_threshold,
)

logger = logging.getLogger(__name__)


def _finite_threshold(val: Any) -> Optional[int]:
    """Envoy uint32 无限阈值不当作声明值。"""
    if val is None or _is_unlimited_threshold(val):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _extract_max_requests_per_connection(cluster: Dict[str, Any]) -> Optional[int]:
    """Istio 把 maxRequestsPerConnection 编到 HttpProtocolOptions，不在 circuit_breakers 里。"""
    opts = (
        cluster.get("typed_extension_protocol_options")
        or cluster.get("typedExtensionProtocolOptions")
        or {}
    )
    if not isinstance(opts, dict):
        return None
    http_opts = opts.get("envoy.extensions.upstreams.http.v3.HttpProtocolOptions") or {}
    if not isinstance(http_opts, dict):
        return None
    common = (
        http_opts.get("common_http_protocol_options")
        or http_opts.get("commonHttpProtocolOptions")
        or {}
    )
    if not isinstance(common, dict):
        value = http_opts.get("value")
        if isinstance(value, dict):
            common = (
                value.get("common_http_protocol_options")
                or value.get("commonHttpProtocolOptions")
                or {}
            )
    if not isinstance(common, dict):
        return None
    return _finite_threshold(
        common.get("max_requests_per_connection") or common.get("maxRequestsPerConnection")
    )


def _pool_from_dict(pool: Any) -> Optional[ConnectionPoolSettings]:
    if isinstance(pool, ConnectionPoolSettings):
        return pool
    if not isinstance(pool, dict):
        return None
    tcp = pool.get("tcp") if isinstance(pool.get("tcp"), dict) else {}
    http = pool.get("http") if isinstance(pool.get("http"), dict) else {}
    return ConnectionPoolSettings(
        max_connections=_finite_threshold(tcp.get("max_connections") or pool.get("max_connections")),
        http1_max_pending_requests=_finite_threshold(
            http.get("http1_max_pending_requests") or pool.get("http1_max_pending_requests")
        ),
        http2_max_requests=_finite_threshold(
            http.get("http2_max_requests") or pool.get("http2_max_requests")
        ),
        max_requests_per_connection=_finite_threshold(
            http.get("max_requests_per_connection") or pool.get("max_requests_per_connection")
        ),
        max_retries=_finite_threshold(http.get("max_retries") or pool.get("max_retries")),
    )


class CircuitBreakerParser(FunctionParser):
    """熔断解析器"""
    
    def __init__(self):
        super().__init__(FunctionType.CIRCUIT_BREAKER)
    
    def _parse_connection_pool(self, pool_config: Dict[str, Any]) -> Optional[ConnectionPoolSettings]:
        """解析连接池配置"""
        if not pool_config:
            return None
        
        tcp = pool_config.get('tcp', {})
        http = pool_config.get('http', {})
        
        return ConnectionPoolSettings(
            max_connections=tcp.get('maxConnections'),
            connect_timeout=tcp.get('connectTimeout'),
            tcp_keepalive=tcp.get('tcpKeepalive'),
            http1_max_pending_requests=http.get('http1MaxPendingRequests'),
            http2_max_requests=http.get('http2MaxRequests'),
            max_requests_per_connection=http.get('maxRequestsPerConnection'),
            max_retries=http.get('maxRetries'),
            idle_timeout=http.get('idleTimeout')
        )
    
    def _parse_outlier_detection(self, outlier_config: Dict[str, Any]) -> Optional[OutlierDetection]:
        """解析异常检测配置"""
        if not outlier_config:
            return None
        
        return OutlierDetection(
            consecutive_5xx_errors=outlier_config.get('consecutive5xxErrors'),
            consecutive_gateway_errors=outlier_config.get('consecutiveGatewayErrors'),
            interval=outlier_config.get('interval'),
            base_ejection_time=outlier_config.get('baseEjectionTime'),
            max_ejection_percent=outlier_config.get('maxEjectionPercent'),
            min_health_percent=outlier_config.get('minHealthPercent')
        )
    
    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[CircuitBreakerFunctionModel]:
        """
        解析控制平面熔断配置（DestinationRule）
        
        Args:
            config: DestinationRule 配置字典
            context: 上下文信息
            
        Returns:
            熔断功能模型列表
        """
        models = []
        items = config.get('items', []) if isinstance(config, dict) else config
        
        for item in items:
            if item.get('kind') != 'DestinationRule':
                continue
            
            namespace, name = self._extract_namespace_and_service(item)
            spec = item.get('spec', {})
            
            # 提取服务名
            host = spec.get('host', '')
            service_name = host.split('.')[0] if host else name
            
            model = CircuitBreakerFunctionModel(
                function_type=FunctionType.CIRCUIT_BREAKER,
                service_name=service_name,
                namespace=namespace,
                plane_type=PlaneType.CONTROL_PLANE,
                raw_config=item
            )
            
            # 解析全局流量策略
            if 'trafficPolicy' in spec:
                traffic_policy = spec['trafficPolicy']
                
                if 'connectionPool' in traffic_policy:
                    model.connection_pool = self._parse_connection_pool(
                        traffic_policy['connectionPool']
                    )
                
                if 'outlierDetection' in traffic_policy:
                    model.outlier_detection = self._parse_outlier_detection(
                        traffic_policy['outlierDetection']
                    )
            
            # 解析子集级别的流量策略
            for subset in spec.get('subsets', []):
                subset_name = subset.get('name')
                if not subset_name:
                    continue
                
                if 'trafficPolicy' in subset:
                    subset_policy = subset['trafficPolicy']
                    
                    policy_dict = {}
                    
                    if 'connectionPool' in subset_policy:
                        conn_pool = self._parse_connection_pool(subset_policy['connectionPool'])
                        if conn_pool:
                            policy_dict['connection_pool'] = conn_pool.to_dict()
                    
                    if 'outlierDetection' in subset_policy:
                        outlier = self._parse_outlier_detection(subset_policy['outlierDetection'])
                        if outlier:
                            policy_dict['outlier_detection'] = outlier.to_dict()
                    
                    if policy_dict:
                        model.subset_policies[subset_name] = policy_dict
            
            # 只有 DR 真正写了连接池/异常检测才算熔断；仅 subsets 的 DR 不是熔断
            if model.has_declared_policy():
                models.append(model)
        
        return models
    
    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[CircuitBreakerFunctionModel]:
        """
        解析数据平面熔断配置（Envoy Cluster配置）
        
        Args:
            config: Envoy clusters.json 配置
            context: 上下文信息
            
        Returns:
            熔断功能模型列表
        """
        models = []
        
        # 数据平面熔断配置通常在cluster配置中
        if isinstance(config, dict):
            clusters = config.get('dynamicActiveClusters', [])
        elif isinstance(config, list):
            clusters = config
        else:
            clusters = []
        
        # 按 namespace.service 聚合，避免 default 与演示网格同名服务混在一起
        service_clusters: Dict[str, List[Dict]] = {}
        
        for cluster_item in clusters:
            cluster = cluster_item.get('cluster', {}) if 'cluster' in cluster_item else cluster_item
            cluster_name = cluster.get('name', '')
            
            # 解析集群名称: outbound|port|subset|host
            if '|' in cluster_name and cluster_name.startswith('outbound|'):
                parts = cluster_name.split('|')
                if len(parts) >= 4:
                    host = parts[3]
                    service_name = host.split('.')[0]
                    namespace = host.split('.')[1] if '.' in host else 'default'
                    subset = parts[2] if parts[2] else None
                    svc_key = f"{namespace}.{service_name}"
                    
                    if svc_key not in service_clusters:
                        service_clusters[svc_key] = []
                    
                    service_clusters[svc_key].append({
                        'cluster': cluster,
                        'subset': subset,
                        'namespace': namespace,
                        'service_name': service_name,
                    })
        
        # 为每个服务创建熔断模型
        for svc_key, clustered in service_clusters.items():
            namespace = clustered[0]['namespace'] if clustered else 'default'
            service_name = clustered[0].get('service_name') or svc_key.split('.', 1)[-1]
            
            model = CircuitBreakerFunctionModel(
                function_type=FunctionType.CIRCUIT_BREAKER,
                service_name=service_name,
                namespace=namespace,
                plane_type=PlaneType.DATA_PLANE,
                raw_config={'clusters': clustered}
            )
            
            # 解析每个cluster的熔断配置（clusters.json 中 circuit_breakers 在 cluster 内）
            for cluster_info in clustered:
                cluster = cluster_info['cluster']
                subset = cluster_info['subset']
                
                circuit_breakers_config = cluster.get('circuitBreakers') or cluster.get('circuit_breakers') or {}
                thresholds = circuit_breakers_config.get('thresholds', [])
                threshold = thresholds[0] if thresholds else {}
                conn_pool = ConnectionPoolSettings(
                    max_connections=_finite_threshold(
                        threshold.get('maxConnections') or threshold.get('max_connections')
                    ),
                    http1_max_pending_requests=_finite_threshold(
                        threshold.get('maxPendingRequests') or threshold.get('max_pending_requests')
                    ),
                    http2_max_requests=_finite_threshold(
                        threshold.get('maxRequests') or threshold.get('max_requests')
                    ),
                    max_requests_per_connection=_extract_max_requests_per_connection(cluster),
                    max_retries=_finite_threshold(
                        threshold.get('maxRetries') or threshold.get('max_retries')
                    ),
                )
                if _connection_pool_is_declared(conn_pool):
                    if not subset:
                        model.connection_pool = conn_pool
                    else:
                        if subset not in model.subset_policies:
                            model.subset_policies[subset] = {}
                        model.subset_policies[subset]['connection_pool'] = conn_pool.to_dict()
                
                outlier_detection_config = cluster.get('outlierDetection') or cluster.get('outlier_detection') or {}
                if outlier_detection_config:
                    outlier = OutlierDetection(
                        consecutive_5xx_errors=outlier_detection_config.get('consecutive5xx') or outlier_detection_config.get('consecutive_5xx'),
                        consecutive_gateway_errors=outlier_detection_config.get('consecutiveGatewayFailure') or outlier_detection_config.get('consecutive_gateway_failure'),
                        interval=outlier_detection_config.get('interval'),
                        base_ejection_time=outlier_detection_config.get('baseEjectionTime') or outlier_detection_config.get('base_ejection_time'),
                        max_ejection_percent=outlier_detection_config.get('maxEjectionPercent') or outlier_detection_config.get('max_ejection_percent')
                    )
                    
                    if not subset:
                        model.outlier_detection = outlier
                    else:
                        if subset not in model.subset_policies:
                            model.subset_policies[subset] = {}
                        model.subset_policies[subset]['outlier_detection'] = outlier.to_dict()

            if model.connection_pool is None:
                for policy in (model.subset_policies or {}).values():
                    lifted = _pool_from_dict(policy.get('connection_pool'))
                    if _connection_pool_is_declared(lifted):
                        model.connection_pool = lifted
                        break
            
            if model.has_declared_policy():
                models.append(model)
        
        return models

