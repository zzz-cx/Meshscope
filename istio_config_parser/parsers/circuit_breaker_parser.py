"""
熔断功能解析器
解析控制平面和数据平面的熔断配置，生成统一的CircuitBreakerFunctionModel
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.models.function_models import (
    CircuitBreakerFunctionModel, FunctionType, PlaneType,
    ConnectionPoolSettings, OutlierDetection
)

logger = logging.getLogger(__name__)


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
                else:
                    # 子集没有特定配置，标记为None
                    model.subset_policies[subset_name] = None
            
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
        
        # 按服务聚合cluster配置
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
                    
                    if service_name not in service_clusters:
                        service_clusters[service_name] = []
                    
                    service_clusters[service_name].append({
                        'cluster': cluster,
                        'subset': subset,
                        'namespace': namespace
                    })
        
        # 为每个服务创建熔断模型
        for service_name, clusters in service_clusters.items():
            namespace = clusters[0]['namespace'] if clusters else 'default'
            
            model = CircuitBreakerFunctionModel(
                function_type=FunctionType.CIRCUIT_BREAKER,
                service_name=service_name,
                namespace=namespace,
                plane_type=PlaneType.DATA_PLANE,
                raw_config={'clusters': clusters}
            )
            
            # 解析每个cluster的熔断配置
            for cluster_info in clusters:
                cluster = cluster_info['cluster']
                subset = cluster_info['subset']
                
                # 解析连接池配置
                circuit_breakers_config = cluster.get('circuitBreakers', {})
                thresholds = circuit_breakers_config.get('thresholds', [])
                
                if thresholds:
                    threshold = thresholds[0]
                    
                    conn_pool = ConnectionPoolSettings(
                        max_connections=threshold.get('maxConnections'),
                        http1_max_pending_requests=threshold.get('maxPendingRequests'),
                        http2_max_requests=threshold.get('maxRequests'),
                        max_retries=threshold.get('maxRetries')
                    )
                    
                    # 如果是全局配置（没有subset）
                    if not subset:
                        model.connection_pool = conn_pool
                    else:
                        if subset not in model.subset_policies:
                            model.subset_policies[subset] = {}
                        model.subset_policies[subset]['connection_pool'] = conn_pool.to_dict()
                
                # 解析异常检测配置
                outlier_detection_config = cluster.get('outlierDetection', {})
                if outlier_detection_config:
                    outlier = OutlierDetection(
                        consecutive_5xx_errors=outlier_detection_config.get('consecutive5xx'),
                        consecutive_gateway_errors=outlier_detection_config.get('consecutiveGatewayFailure'),
                        interval=outlier_detection_config.get('interval'),
                        base_ejection_time=outlier_detection_config.get('baseEjectionTime'),
                        max_ejection_percent=outlier_detection_config.get('maxEjectionPercent')
                    )
                    
                    if not subset:
                        model.outlier_detection = outlier
                    else:
                        if subset not in model.subset_policies:
                            model.subset_policies[subset] = {}
                        model.subset_policies[subset]['outlier_detection'] = outlier.to_dict()
            
            if model.connection_pool or model.outlier_detection or model.subset_policies:
                models.append(model)
        
        return models

