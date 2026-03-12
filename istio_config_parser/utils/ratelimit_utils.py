"""
限流配置解析工具
统一 token_bucket 解析逻辑，支持 snake_case（EnvoyFilter）和 camelCase（xDS）格式
"""
from typing import Dict, Any, Optional, Tuple


def parse_token_bucket(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析 token_bucket 配置，支持两种格式：
    - snake_case: token_bucket, max_tokens, fill_interval, tokens_per_fill
    - camelCase: tokenBucket, maxTokens, fillInterval, tokensPerFill

    Returns:
        归一化后的 dict: max_tokens, fill_interval, unit (SECOND|MINUTE|HOUR|DAY)
        若 config 为空或无效则返回 None
    """
    if not config:
        return None
    # 兼容 snake_case 与 camelCase
    max_tokens = config.get('max_tokens') or config.get('maxTokens')
    fill_interval = config.get('fill_interval') or config.get('fillInterval', '')
    tokens_per_fill = config.get('tokens_per_fill') or (
        config.get('tokensPerFill') or {}
    ).get('value') if isinstance(config.get('tokensPerFill'), dict) else config.get('tokensPerFill')

    if max_tokens is None and tokens_per_fill is None:
        return None

    unit = _fill_interval_to_unit(fill_interval)
    return {
        'max_tokens': max_tokens,
        'fill_interval': fill_interval,
        'tokens_per_fill': tokens_per_fill,
        'unit': unit,
    }


def _fill_interval_to_unit(fill_interval: str) -> str:
    """将 fill_interval 字符串转换为标准时间单位"""
    if not fill_interval or 's' not in str(fill_interval):
        return 'SECOND'
    seconds = int(''.join(filter(str.isdigit, str(fill_interval))) or '0')
    if seconds >= 86400:
        return 'DAY'
    if seconds >= 3600:
        return 'HOUR'
    if seconds >= 60:
        return 'MINUTE'
    return 'SECOND'


def extract_token_bucket_from_typed_config(typed_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从 typed_config 中提取 token_bucket（snake_case 格式，如 EnvoyFilter）
    """
    tb = typed_config.get('token_bucket', {})
    return parse_token_bucket(tb) if tb else None


def extract_token_bucket_from_filter_config(filter_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从 filter typedConfig 中提取 tokenBucket（camelCase 格式，如 xDS）
    """
    tb = filter_config.get('tokenBucket', {})
    return parse_token_bucket(tb) if tb else None
