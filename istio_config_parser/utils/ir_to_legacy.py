"""
SystemIR 到 Legacy 格式的适配器
将 UnifiedParser 输出转换为 ControlPlaneResult/DataPlaneResult 供 StaticAnalyzer 等使用
"""
import logging
from typing import Dict, List, Any, Tuple, Optional
from istio_config_parser.models.ir_models import SystemIR, ServiceIR
from istio_config_parser.models.data_structures import (
    ControlPlaneResult,
    DataPlaneResult,
    ServiceRelation,
    DataPlaneServiceRelation,
)
from istio_config_parser.models.function_models import FunctionType

logger = logging.getLogger(__name__)


def _convert_circuit_breaker_from_raw(dr_item: Dict) -> Dict:
    """从 DestinationRule raw 解析熔断配置"""
    result = {'global_': None, 'subsets': {}}
    spec = dr_item.get('spec', {})
    if 'trafficPolicy' in spec:
        policy = spec['trafficPolicy']
        result['global_'] = {
            'connectionPool': policy.get('connectionPool', {}),
            'outlierDetection': policy.get('outlierDetection', {})
        }
    for subset in spec.get('subsets', []):
        name = subset.get('name')
        if 'trafficPolicy' in subset:
            policy = subset['trafficPolicy']
            result['subsets'][name] = {
                'connectionPool': policy.get('connectionPool', {}),
                'outlierDetection': policy.get('outlierDetection', {})
            }
        else:
            result['subsets'][name] = None
    return result


def _convert_rate_limit_to_legacy(model_dict: Dict) -> List[Dict]:
    """将 RateLimitFunctionModel 转为 legacy 格式"""
    rules = model_dict.get('rules', [])
    result = []
    for r in rules:
        if isinstance(r, dict):
            result.append({
                'type': 'local',
                'requests_per_unit': r.get('requests_per_unit'),
                'unit': r.get('unit', 'SECOND').lower(),
                'conditions': []
            })
    return result


def system_ir_to_legacy(
    system_ir: SystemIR,
    services: List[Dict]
) -> Tuple[ControlPlaneResult, DataPlaneResult]:
    """
    将 SystemIR 转换为 legacy 格式 (ControlPlaneResult, DataPlaneResult)
    """
    service_relations: Dict[str, ServiceRelation] = {}
    data_relations: Dict[str, DataPlaneServiceRelation] = {}

    for service_ir in system_ir.get_all_services():
        svc_name = service_ir.service_name
        ns = service_ir.namespace

        rel: ServiceRelation = {
            'incomingVirtualServices': [],
            'subsets': [],
            'rateLimit': [],
            'gateways': [],
            'weights': {},
            'trafficPolicy': None,
            'circuitBreaker': None
        }
        data_rel: DataPlaneServiceRelation = {
            'inbound': [],
            'outbound': [],
            'weights': {}
        }

        seen_vs: set = set()
        for func_type, func_ir in service_ir.functions.items():
            cfg = func_ir.config
            cp = cfg.get('control_plane') or {}
            dp = cfg.get('data_plane') or {}
            pair = func_ir.aligned_pair
            cp_model = pair.control_plane_model if pair else None
            dp_model = pair.data_plane_model if pair else None

            if func_type == FunctionType.ROUTING.value:
                if cp_model and hasattr(cp_model, 'raw_config') and cp_model.raw_config:
                    vs = cp_model.raw_config
                    key = (vs.get('metadata', {}).get('name'), ns)
                    if key not in seen_vs:
                        seen_vs.add(key)
                        rel['incomingVirtualServices'].append({
                            'name': vs.get('metadata', {}).get('name', ''),
                            'namespace': ns,
                            'rules': vs.get('spec', {}).get('http', [])
                        })
                    gateways = cp_model.gateways if hasattr(cp_model, 'gateways') else []
                    for gw in gateways:
                        rel['gateways'].append({
                            'name': gw if isinstance(gw, str) else gw.get('name', ''),
                            'type': 'ingress',
                            'virtualService': cp_model.raw_config.get('metadata', {}).get('name', ''),
                            'namespace': ns
                        })
                if dp_model and hasattr(dp_model, 'routes'):
                    for route in dp_model.routes:
                        for dest in route.get('destinations', []):
                            if isinstance(dest, dict):
                                host = dest.get('host', '')
                                if host and host != 'unknown':
                                    data_rel['outbound'].append({
                                        'service': host.split('.')[0],
                                        'port': str(dest.get('port', 80)),
                                        'subset': dest.get('subset')
                                    })
                                w = dest.get('weight', 100)
                                sub = dest.get('subset')
                                if sub and (len(route.get('destinations', [])) > 1):
                                    data_rel['weights'][sub] = w

            elif func_type == FunctionType.TRAFFIC_SHIFTING.value:
                if cp_model:
                    if hasattr(cp_model, 'subsets') and cp_model.subsets:
                        rel['subsets'] = [s if isinstance(s, dict) else {
                            'name': getattr(s, 'name', s.get('name', '')),
                            'version': getattr(s, 'version', s.get('version', '')),
                            'labels': getattr(s, 'labels', s.get('labels', {}))
                        } for s in cp_model.subsets]
                    elif hasattr(cp_model, 'raw_config') and isinstance(cp_model.raw_config, dict):
                        dr = cp_model.raw_config.get('destination_rule', {})
                        for sub in dr.get('spec', {}).get('subsets', []):
                            rel['subsets'].append({
                                'name': sub.get('name', ''),
                                'version': sub.get('labels', {}).get('version', ''),
                                'labels': sub.get('labels', {})
                            })
                    if hasattr(cp_model, 'destinations'):
                        for d in cp_model.destinations:
                            dest = d if isinstance(d, dict) else (d.to_dict() if hasattr(d, 'to_dict') else {})
                            sub = dest.get('subset')
                            w = dest.get('weight', 100)
                            if sub:
                                rel['weights'][sub] = {'weight': w, 'namespace': ns}
                if dp_model and hasattr(dp_model, 'destinations'):
                    for d in dp_model.destinations:
                        dest = d if isinstance(d, dict) else (d.to_dict() if hasattr(d, 'to_dict') else {})
                        sub = dest.get('subset')
                        w = dest.get('weight', 100)
                        if sub:
                            data_rel['weights'][sub] = w

            elif func_type == FunctionType.CIRCUIT_BREAKER.value:
                if cp_model and hasattr(cp_model, 'raw_config') and cp_model.raw_config:
                    rel['circuitBreaker'] = _convert_circuit_breaker_from_raw(cp_model.raw_config)

            elif func_type == FunctionType.RATE_LIMIT.value:
                if cp_model:
                    legacy_rl = _convert_rate_limit_to_legacy(cp if isinstance(cp, dict) else (cp_model.to_dict() if hasattr(cp_model, 'to_dict') else {}))
                    rel['rateLimit'].extend(legacy_rl)

        if any([rel['incomingVirtualServices'], rel['subsets'], rel['rateLimit'], rel['circuitBreaker'], rel['weights']]):
            service_relations[svc_name] = rel
        if any([data_rel['outbound'], data_rel['weights']]):
            data_relations[svc_name] = data_rel

    control_result: ControlPlaneResult = {
        'services': services,
        'serviceRelations': service_relations,
        'configurations': {k: {
            'virtualServices': v.get('incomingVirtualServices', []),
            'destinationRules': v.get('subsets', []),
            'envoyFilters': v.get('rateLimit', []),
            'weights': v.get('weights', {}),
            'circuitBreaker': v.get('circuitBreaker')
        } for k, v in service_relations.items()}
    }
    data_result: DataPlaneResult = {'serviceRelations': data_relations}
    return control_result, data_result
