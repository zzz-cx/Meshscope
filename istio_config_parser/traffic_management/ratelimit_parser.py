import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

def parse_ratelimit(configs: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析限流规则
    返回结构示例：{service_name: [{type: 'local', requests_per_unit: 100, unit: 'minute', conditions: []}]}
    """
    ratelimits = {}
    # 确保我们处理的是正确的配置格式
    items = configs.get('items', []) if isinstance(configs, dict) else configs
    
    for item in items:
        # 检查是否是单个配置项
        if isinstance(item, dict) and item.get('kind') == 'EnvoyFilter':
            namespace = item['metadata'].get('namespace', 'default')
            # 获取服务名
            workload_selector = item['spec'].get('workloadSelector', {})
            if workload_selector and 'labels' in workload_selector:
                app_label = workload_selector['labels'].get('app')
                if app_label:
                    service_name = app_label
                    
                    if service_name not in ratelimits:
                        ratelimits[service_name] = []
                    
                    # 解析限流规则
                    rate_limit = {
                        'type': 'local',
                        'requests_per_unit': None,
                        'unit': None,
                        'conditions': [],
                        'namespace': namespace,
                        'name': item['metadata'].get('name', '')
                    }
                    
                    # 提取限流规则
                    for patch in item['spec'].get('configPatches', []):
                        if patch.get('applyTo') == 'HTTP_FILTER':
                            patch_value = patch.get('patch', {}).get('value', {})
                            if patch_value.get('name') == 'envoy.filters.http.local_ratelimit':
                                typed_config = patch_value.get('typed_config', {})
                                if typed_config and '@type' in typed_config:
                                    token_bucket = typed_config.get('token_bucket', {})
                                    if token_bucket:
                                        rate_limit['requests_per_unit'] = token_bucket.get('max_tokens')
                                        
                                        # 转换填充间隔为时间单位
                                        fill_interval = token_bucket.get('fill_interval')
                                        if fill_interval and 's' in fill_interval:
                                            seconds = int(''.join(filter(str.isdigit, fill_interval)))
                                            if seconds == 60:
                                                rate_limit['unit'] = 'minute'
                                            else:
                                                rate_limit['unit'] = f'{seconds}秒'
                        
                        elif patch.get('applyTo') == 'VIRTUAL_HOST':
                            patch_value = patch.get('patch', {}).get('value', {})
                            rate_limits = patch_value.get('rate_limits', [])
                            for limit in rate_limits:
                                for action in limit.get('actions', []):
                                    if 'request_headers' in action:
                                        header = action['request_headers']
                                        rate_limit['conditions'].append({
                                            'type': 'header',
                                            'name': header.get('header_name'),
                                            'value': header.get('descriptor_key')
                                        })
                    
                    # 只有当成功解析到限流规则时才保存
                    if rate_limit['requests_per_unit'] is not None and rate_limit['unit'] is not None:
                        ratelimits[service_name].append(rate_limit)
    
    return ratelimits 