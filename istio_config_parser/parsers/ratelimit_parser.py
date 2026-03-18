"""
限流功能解析器
解析控制平面和数据平面的限流配置，生成统一的 RateLimitFunctionModel

Istio 限流两种机制:
- 本地限流(Local): EnvoyFilter → envoy.filters.http.local_ratelimit, token_bucket
- 全局限流(Global): EnvoyFilter → envoy.filters.http.ratelimit, rate_limit_service

控制面→数据面映射:
  EnvoyFilter HTTP_FILTER + local_ratelimit  → listeners http_filters local_ratelimit
  EnvoyFilter HTTP_FILTER + ratelimit         → listeners http_filters ratelimit
  token_bucket (控制面)                        → token_bucket / tokenBucket (数据面)
  rate_limits (descriptor)                   → route.rate_limits
"""
import logging
from typing import Dict, List, Any, Optional
from istio_config_parser.parsers.base_parser import FunctionParser
from istio_config_parser.utils.ratelimit_utils import parse_token_bucket
from istio_config_parser.models.function_models import (
    RateLimitFunctionModel, RateLimitRule, FunctionType, PlaneType,
    MatchCondition, RateLimitType
)

logger = logging.getLogger(__name__)


def _extract_token_bucket_from_typed_config(typed_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从 typed_config 提取 token_bucket，兼容多种格式:
    - 直接: typed_config.token_bucket
    - TypedStruct: typed_config.value.token_bucket
    - camelCase: typed_config.tokenBucket
    """
    if not typed_config:
        return None
    # 直接 token_bucket / tokenBucket
    tb = typed_config.get('token_bucket') or typed_config.get('tokenBucket')
    if tb:
        return parse_token_bucket(tb)
    # TypedStruct 包装: value.token_bucket
    value = typed_config.get('value', {})
    if isinstance(value, dict):
        tb = value.get('token_bucket') or value.get('tokenBucket')
        if tb:
            return parse_token_bucket(tb)
    return None


def _extract_listeners(config: Any) -> List[Dict]:
    """从 listeners 配置提取 listener 列表，兼容多种格式"""
    if isinstance(config, list):
        return config
    if isinstance(config, dict):
        return config.get('dynamicListeners') or config.get('dynamic_listeners') or []
    return []


def _extract_listener_obj(item: Dict) -> Optional[Dict]:
    """从 listener 项提取 listener 对象"""
    if not item:
        return None
    # activeState.listener / active_state.listener
    active = item.get('activeState') or item.get('active_state', {})
    if active:
        return active.get('listener')
    return item.get('listener') or item


def _extract_http_filters_from_listener(listener: Dict) -> List[Dict]:
    """从 listener 提取所有 HTTP filter 配置"""
    filters = []
    for fc in listener.get('filterChains', listener.get('filter_chains', [])):
        for nf in fc.get('filters', []):
            if nf.get('name') in ('envoy.filters.network.http_connection_manager',):
                tc = nf.get('typedConfig') or nf.get('typed_config', {})
                hf = tc.get('httpFilters') or tc.get('http_filters', [])
                filters.extend(hf)
    # default_filter_chain
    dfc = listener.get('defaultFilterChain') or listener.get('default_filter_chain', {})
    if dfc:
        for nf in dfc.get('filters', []):
            if nf.get('name') in ('envoy.filters.network.http_connection_manager',):
                tc = nf.get('typedConfig') or nf.get('typed_config', {})
                hf = tc.get('httpFilters') or tc.get('http_filters', [])
                filters.extend(hf)
    return filters


def _infer_service_from_listener(listener: Dict) -> tuple:
    """从 listener 推断 (service_name, namespace)，用于数据平面"""
    name = listener.get('name', '')
    # 尝试从 route_config virtual_hosts 获取
    for fc in listener.get('filterChains', listener.get('filter_chains', [])):
        for nf in fc.get('filters', []):
            tc = nf.get('typedConfig') or nf.get('typed_config', {})
            rc = tc.get('routeConfig') or tc.get('route_config', {})
            vhosts = rc.get('virtualHosts') or rc.get('virtual_hosts', [])
            if vhosts:
                domains = vhosts[0].get('domains', [])
                if domains:
                    parts = domains[0].split('.')
                    if len(parts) >= 2:
                        return parts[0], parts[1]
                    if parts:
                        return parts[0], 'default'
    return 'unknown', 'default'


class RateLimitParser(FunctionParser):
    """限流解析器"""

    def __init__(self):
        super().__init__(FunctionType.RATE_LIMIT)

    def parse_control_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RateLimitFunctionModel]:
        """
        解析控制平面限流配置（EnvoyFilter）

        支持:
        - 本地限流: applyTo=HTTP_FILTER, name=envoy.filters.http.local_ratelimit
        - 全局限流: applyTo=HTTP_FILTER, name=envoy.filters.http.ratelimit
        - VIRTUAL_HOST rate_limits + CLUSTER rate_limit_service
        """
        models = []
        items = config.get('items', []) if isinstance(config, dict) else config

        for item in items:
            if item.get('kind') != 'EnvoyFilter':
                continue

            namespace, name = self._extract_namespace_and_service(item)
            spec = item.get('spec', {})

            # 从 workloadSelector 获取服务名
            workload_selector = spec.get('workloadSelector', {})
            labels = workload_selector.get('labels', {})
            service_name = labels.get('app', name)

            model = RateLimitFunctionModel(
                function_type=FunctionType.RATE_LIMIT,
                service_name=service_name,
                namespace=namespace,
                plane_type=PlaneType.CONTROL_PLANE,
                raw_config=item
            )

            for patch in spec.get('configPatches', []):
                apply_to = patch.get('applyTo')
                patch_value = patch.get('patch', {}).get('value', {})

                # HTTP_FILTER: 本地或全局限流
                if apply_to == 'HTTP_FILTER':
                    filter_name = patch_value.get('name', '')
                    typed_config = patch_value.get('typed_config', patch_value.get('typedConfig', {}))

                    # 本地限流: local_ratelimit
                    if 'local_ratelimit' in filter_name:
                        model.rate_limit_type = RateLimitType.LOCAL
                        parsed = _extract_token_bucket_from_typed_config(typed_config)
                        if parsed:
                            rule = RateLimitRule(
                                requests_per_unit=parsed.get('max_tokens') or parsed.get('tokens_per_fill') or 0,
                                unit=parsed.get('unit', 'SECOND')
                            )
                            model.rules.append(rule)

                    # 全局限流: ratelimit (不含 local)
                    elif filter_name == 'envoy.filters.http.ratelimit':
                        model.rate_limit_type = RateLimitType.GLOBAL
                        rls = typed_config.get('rate_limit_service') or typed_config.get('rateLimitService')
                        if rls:
                            model.rate_limit_service = rls
                        # TypedStruct value
                        value = typed_config.get('value', {})
                        if isinstance(value, dict):
                            rls = value.get('rate_limit_service') or value.get('rateLimitService')
                            if rls:
                                model.rate_limit_service = rls

                # VIRTUAL_HOST: rate_limits (descriptor)
                elif apply_to == 'VIRTUAL_HOST':
                    model.rate_limit_type = RateLimitType.GLOBAL
                    rate_limits = patch_value.get('rate_limits', patch_value.get('rateLimits', []))
                    for limit in rate_limits:
                        match_condition = MatchCondition()
                        for action in limit.get('actions', []):
                            if 'request_headers' in action:
                                h = action['request_headers']
                                hn = h.get('header_name', h.get('headerName', ''))
                                dk = h.get('descriptor_key', h.get('descriptorKey', ''))
                                if hn:
                                    match_condition.headers[hn] = {'descriptor_key': dk}
                        rule = RateLimitRule(
                            requests_per_unit=0,
                            unit='MINUTE',
                            match_conditions=match_condition if match_condition.headers else None
                        )
                        model.rules.append(rule)

                # CLUSTER: rate_limit_service
                elif apply_to == 'CLUSTER':
                    if 'rate_limit_service' in patch_value or 'rateLimitService' in patch_value:
                        model.rate_limit_type = RateLimitType.GLOBAL
                        model.rate_limit_service = patch_value.get('rate_limit_service') or patch_value.get('rateLimitService')

            if model.rules or model.rate_limit_service:
                models.append(model)

        return models

    def parse_data_plane(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[RateLimitFunctionModel]:
        """
        解析数据平面限流配置（Envoy Listener HTTP Filters）

        数据平面体现:
        - 本地限流: envoy.filters.http.local_ratelimit, token_bucket
        - 全局限流: envoy.filters.http.ratelimit, rate_limit_service
        """
        models = []
        listeners = _extract_listeners(config)

        # 按 (namespace, service_name) 聚合，支持同一服务多种限流
        service_configs: Dict[str, Dict] = {}

        for item in listeners:
            listener = _extract_listener_obj(item)
            if not listener:
                continue

            service_name, namespace = _infer_service_from_listener(listener)
            key = f"{namespace}.{service_name}"

            for http_filter in _extract_http_filters_from_listener(listener):
                filter_name = http_filter.get('name', '')
                typed_config = http_filter.get('typedConfig') or http_filter.get('typed_config', {})

                # 本地限流
                if 'local_ratelimit' in filter_name:
                    if key not in service_configs:
                        service_configs[key] = {
                            'service_name': service_name,
                            'namespace': namespace,
                            'rules': [],
                            'rate_limit_type': RateLimitType.LOCAL,
                            'rate_limit_service': None
                        }
                    parsed = _extract_token_bucket_from_typed_config(typed_config)
                    if parsed:
                        service_configs[key]['rules'].append({
                            'requests_per_unit': parsed.get('max_tokens') or parsed.get('tokens_per_fill') or 0,
                            'unit': parsed.get('unit', 'SECOND')
                        })
                    service_configs[key]['rate_limit_type'] = RateLimitType.LOCAL

                # 全局限流
                elif filter_name == 'envoy.filters.http.ratelimit':
                    if key not in service_configs:
                        service_configs[key] = {
                            'service_name': service_name,
                            'namespace': namespace,
                            'rules': [],
                            'rate_limit_type': RateLimitType.GLOBAL,
                            'rate_limit_service': None
                        }
                    rls = typed_config.get('rate_limit_service') or typed_config.get('rateLimitService')
                    value = typed_config.get('value', {})
                    if isinstance(value, dict):
                        rls = rls or value.get('rate_limit_service') or value.get('rateLimitService')
                    if rls:
                        service_configs[key]['rate_limit_service'] = rls
                    service_configs[key]['rate_limit_type'] = RateLimitType.GLOBAL

        for key, info in service_configs.items():
            model = RateLimitFunctionModel(
                function_type=FunctionType.RATE_LIMIT,
                service_name=info['service_name'],
                namespace=info['namespace'],
                plane_type=PlaneType.DATA_PLANE,
                rate_limit_type=info['rate_limit_type'],
                rate_limit_service=info['rate_limit_service'],
                raw_config={'listener_key': key}
            )
            for r in info['rules']:
                model.rules.append(RateLimitRule(
                    requests_per_unit=r['requests_per_unit'],
                    unit=r['unit']
                ))
            if model.rules or model.rate_limit_service:
                models.append(model)

        return models
