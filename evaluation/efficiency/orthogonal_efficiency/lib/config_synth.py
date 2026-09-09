# -*- coding: utf-8 -*-
"""Synthesize Istio configs under (service_scale × config_scale)."""

from typing import Any, Dict, List, Tuple

# 配置规模：策略集合递增（与 Dynamic_Test enabled_policies / strategies 对齐）
CONFIG_LEVELS = {
    "C1": {
        "label": "routing",
        "policies": ["routing"],
        "description": "routing / match only",
    },
    "C2": {
        "label": "routing+reliability",
        "policies": ["routing", "retry", "timeout", "traffic_split"],
        "description": "routing + retry/timeout/split",
    },
    "C3": {
        "label": "resilience",
        "policies": [
            "routing",
            "retry",
            "timeout",
            "traffic_split",
            "circuit_breaker",
            "connection_pool",
        ],
        "description": "C2 + circuit breaker / connection pool",
    },
    "C4": {
        "label": "full",
        "policies": [
            "routing",
            "retry",
            "timeout",
            "traffic_split",
            "circuit_breaker",
            "connection_pool",
            "fault_injection",
            "rate_limit",
        ],
        "description": "C3 + fault injection / rate limit",
    },
    "C5": {
        "label": "full+mirror+authz",
        "policies": [
            "routing",
            "retry",
            "timeout",
            "traffic_split",
            "circuit_breaker",
            "connection_pool",
            "fault_injection",
            "rate_limit",
            "mirroring",
            "authorization",
        ],
        "description": "C4 + traffic mirroring / authorization checks",
    },
}

SERVICE_SCALES = (5, 10, 15, 20, 30, 40, 50)


def svc_name(i: int) -> str:
    return "meshscope-svc-{0:04d}".format(i)


def count_config_items(istio_config: Dict[str, Any]) -> int:
    """Fine-grained configuration item count (x-axis for reduction figure)."""
    n = 0
    for vs in istio_config.get("virtualServices") or []:
        spec = vs.get("spec") or {}
        n += 1  # VS resource
        for block in spec.get("http") or []:
            n += 1  # route block
            if block.get("match"):
                n += len(block["match"])
            if block.get("retries"):
                n += 1
            if block.get("timeout"):
                n += 1
            if block.get("fault"):
                n += 1
            if block.get("mirror"):
                n += 1
            route = block.get("route") or []
            n += max(len(route), 1)
    for dr in istio_config.get("destinationRules") or []:
        spec = dr.get("spec") or {}
        n += 1
        n += len(spec.get("subsets") or [])
        tp = spec.get("trafficPolicy") or {}
        if tp.get("connectionPool"):
            n += 2
        if tp.get("outlierDetection"):
            n += 2
        if tp.get("loadBalancer"):
            n += 1
    ep = istio_config.get("enabled_policies") or {}
    if ep.get("rate_limit"):
        # EnvoyFilter-equivalent local rate limit knobs per service
        n += len(istio_config.get("virtualServices") or [])
    if ep.get("mirroring"):
        n += len(istio_config.get("virtualServices") or [])
    if ep.get("authorization"):
        n += len(istio_config.get("virtualServices") or [])
    return n


def synthesize_istio_config(n_services: int, config_level: str) -> Dict[str, Any]:
    if config_level not in CONFIG_LEVELS:
        raise ValueError("unknown config_level {0}".format(config_level))
    policies = set(CONFIG_LEVELS[config_level]["policies"])
    vs_list = []  # type: List[Dict[str, Any]]
    dr_list = []  # type: List[Dict[str, Any]]

    for i in range(1, n_services + 1):
        name = svc_name(i)
        http = []  # type: List[Dict[str, Any]]

        # header-match branch -> v2
        blk = {
            "match": [
                {
                    "uri": {"prefix": "/s{0}/".format(i)},
                    "headers": {"x-meshscope-user": {"exact": "vip"}},
                }
            ],
            "route": [{"destination": {"host": name, "subset": "v2"}}],
        }
        if "retry" in policies:
            blk["retries"] = {"attempts": 3, "perTryTimeout": "2s", "retryOn": "5xx"}
        if "timeout" in policies:
            blk["timeout"] = "3s"
        if "fault_injection" in policies and i % 2 == 1:
            blk["fault"] = {
                "abort": {"httpStatus": 503, "percentage": {"value": 100}}
            }
        http.append(blk)

        # alt header match
        http.append(
            {
                "match": [
                    {
                        "uri": {"prefix": "/s{0}/alt/".format(i)},
                        "headers": {"x-meshscope-role": {"exact": "admin"}},
                    }
                ],
                "route": [{"destination": {"host": name, "subset": "v2"}}],
            }
        )

        # default / traffic split
        if "traffic_split" in policies:
            split_blk = {
                "match": [{"uri": {"prefix": "/s{0}/".format(i)}}],
                "route": [
                    {
                        "destination": {"host": name, "subset": "v1"},
                        "weight": 70,
                    },
                    {
                        "destination": {"host": name, "subset": "v2"},
                        "weight": 30,
                    },
                ],
            }
            if "mirroring" in policies:
                split_blk["mirror"] = {"host": name, "subset": "v2"}
                split_blk["mirrorPercentage"] = {"value": 10.0}
            http.append(split_blk)
        else:
            http.append(
                {
                    "match": [{"uri": {"prefix": "/s{0}/".format(i)}}],
                    "route": [{"destination": {"host": name, "subset": "v1"}}],
                }
            )

        if "authorization" in policies:
            http.append(
                {
                    "match": [
                        {
                            "uri": {"prefix": "/s{0}/admin/".format(i)},
                            "headers": {"x-meshscope-auth": {"exact": "deny"}},
                        }
                    ],
                    "fault": {
                        "abort": {"httpStatus": 403, "percentage": {"value": 100}}
                    },
                    "route": [{"destination": {"host": name, "subset": "v1"}}],
                }
            )

        vs_list.append({"name": name, "spec": {"hosts": [name], "http": http}})

        tp = {"loadBalancer": {"simple": "ROUND_ROBIN"}}  # type: Dict[str, Any]
        if "connection_pool" in policies or "circuit_breaker" in policies:
            tp["connectionPool"] = {
                "tcp": {"maxConnections": 50},
                "http": {
                    "http1MaxPendingRequests": 10,
                    "maxRequestsPerConnection": 2,
                },
            }
        if "circuit_breaker" in policies:
            tp["outlierDetection"] = {
                "consecutive5xxErrors": 3,
                "interval": "5s",
                "baseEjectionTime": "30s",
                "maxEjectionPercent": 50,
            }
        dr_list.append(
            {
                "name": name,
                "spec": {
                    "host": name,
                    "subsets": [
                        {"name": "v1", "labels": {"version": "v1"}},
                        {"name": "v2", "labels": {"version": "v2"}},
                    ],
                    "trafficPolicy": tp,
                },
            }
        )

    enabled = {p: True for p in policies}
    enabled["routing"] = True
    return {
        "description": "orthogonal_efficiency N={0} {1}".format(n_services, config_level),
        "enabled_policies": enabled,
        "virtualServices": vs_list,
        "destinationRules": dr_list,
        "metadata": {
            "n_services": n_services,
            "config_level": config_level,
            "policies": sorted(policies),
        },
    }


def iter_scale_grid(
    service_scales=None, config_levels=None
):
    # type: (...) -> List[Tuple[int, str]]
    ss = list(service_scales or SERVICE_SCALES)
    cs = list(config_levels or CONFIG_LEVELS.keys())
    return [(n, c) for n in ss for c in cs]
