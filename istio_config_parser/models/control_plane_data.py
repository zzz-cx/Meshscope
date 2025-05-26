# istio_graph_config.py

"""
该模块定义了 Istio 控制面中服务与配置之间的抽象数据结构。
可用于拓扑图可视化、配置分析、服务依赖追踪等应用场景。
"""
from pycurl import HTTPAUTH

istio_graph_config = {
    "services": [
        {
            "name": "cartservice",
            "namespace": "online-boutique",
            "ports": [
                {
                    "name": "grpc",
                    "port": 7070
                }
            ],
            "clusterIP": "10.102.39.242",
            "appLabel": "cartservice",
            "selectors": {
                "app": "cartservice"
            },
            "istioConfig": {
                # 虚拟服务定义（路由规则）
                "virtualService": {
                    "hosts": [
                        "cartservice",
                        "cartservice.online-boutique.svc.cluster.local"
                    ],
                    "gateways": ["online-boutique-gateway"],
                    "http": [
                        {
                            "match": [
                                {
                                    "uri": {
                                        "prefix": "/cart"
                                    }
                                }
                            ],
                            "route": [
                                {
                                    "destination": {
                                        "host": "cartservice",
                                        "subset": "v1",
                                        "port": {
                                            "number": 7070
                                        }
                                    }
                                }
                            ],
                            "retries": {
                                "attempts": 3,
                                "perTryTimeout": "2s"
                            },
                            "fault": {
                                "delay": {
                                    "percentage": 10,
                                    "fixedDelay": "5s"
                                }
                            }
                        }
                    ]
                },

                # 目标规则定义（流量策略）
                "destinationRule": {
                    "host": "cartservice",
                    "trafficPolicy": {
                        "loadBalancer": {
                            "simple": "ROUND_ROBIN"
                        },
                        "connectionPool": {
                            "tcp": {
                                "maxConnections": 100
                            },
                            "http": {
                                "http1MaxPendingRequests": 100,
                                "maxRequestsPerConnection": 10
                            }
                        },
                        "outlierDetection": {
                            "consecutiveErrors": 5,
                            "interval": "10s",
                            "baseEjectionTime": "30s"
                        }
                    },
                    "subsets": [
                        {
                            "name": "v1",
                            "labels": {
                                "version": "v1"
                            }
                        },
                        {
                            "name": "v2",
                            "labels": {
                                "version": "v2"
                            }
                        }
                    ]
                },

                # 访问控制策略
                "authorizationPolicy": {
                    "name": "cart-access-policy",
                    "action": "ALLOW",
                    "rules": [
                        {
                            "from": [
                                {
                                    "source": {
                                        "principals": [
                                            "cluster.local/ns/online-boutique/sa/frontend"
                                        ]
                                    }
                                }
                            ],
                            "to": [
                                {
                                    "operation": {
                                        "methods": ["GET", "POST"],
                                        "paths": ["/cart"]
                                    }
                                }
                            ]
                        }
                    ]
                },

                # 服务级别的 mTLS 设置
                "peerAuthentication": {
                    "mtls": {
                        "mode": "STRICT"
                    }
                }
            },

            # 图结构信息（用于服务依赖可视化）
            "graphNode": {
                "id": "cartservice",
                "label": "Cart Service",
                "type": "Service",
                "edges": [
                    {
                        "to": "redis-cart",
                        "type": "uses"
                    },
                    {
                        "to": "checkoutservice",
                        "type": "calls"
                    }
                ],
                "configEdges": [
                    {
                        "to": "destinationRule",
                        "type": "loadBalancer"
                    },
                    {
                        "to": "virtualService",
                        "type": "route"
                    }
                ]
            }
        }
    ]
}
istio_config_model = [
    {
        "function": "service",  # 服务具体信息
        "config_object": "Service",
        "fields": [
            {
                "path": "metadata.name",
                "type": "string",
                "required": True,
                "description": "服务的名称"
            },
            {
                "path": "metadata.namespace",
                "type": "string",
                "required": True,
                "description": "服务所在的命名空间"
            },
            {
                "path": "spec.ports[0].name",
                "type": "string",
                "required": True,
                "description": "服务端口名称"
            },
            {
                "path": "spec.ports[0].port",
                "type": "integer",
                "required": True,
                "description": "服务端口"
            },
            {
                "path": "spec.ports[0].targetPort",
                "type": "integer",
                "required": True,
                "description": "目标端口"
            },
            {
                "path": "spec.clusterIP",
                "type": "string",
                "required": True,
                "description": "服务的 ClusterIP 地址"
            },
            {
                "path": "spec.selector.app",
                "type": "string",
                "required": True,
                "description": "应用标签，标识服务"
            },
            {
                "path": "spec.type",
                "type": "string",
                "required": True,
                "description": "服务的类型（例如 ClusterIP, NodePort, LoadBalancer）"
            }
        ]
    },
    {
        "function": "traffic_routing", # 路由策略（包括HTTP请求的重试、超时、重定向和重写）
        "config_object": "VirtualService",
        "fields": [
            {
                "path": "spec.hosts[]",
                "type": "string",
                "required": True,
                "description": "目标服务主机名"
            },
            {
                "path": "spec.gateways[]",
                "type": "string",
                "required": False,
                "description": "使用的网关名称"
            },
            {
                "path": "spec.http[].match[].uri.exact",
                "type": "string",
                "required": False,
                "description": "匹配精确 URI"
            },
            {
                "path": "spec.http[].match[].uri.prefix",
                "type": "string",
                "required": False,
                "description": "匹配 URI 前缀"
            },
            {
                "path": "spec.http[].match[].headers.<header>.exact",
                "type": "string",
                "required": False,
                "description": "匹配请求头值"
            },
            {
                "path": "spec.http[].match[].headers.<header>.regex",
                "type": "string",
                "required": False,
                "description": "匹配请求头的正则表达式"
            },
            {
                "path": "spec.http[].match[].sourceLabels.<label>",
                "type": "string",
                "required": False,
                "description": "匹配请求来源的标签，如用户身份、版本等"
            },
            {
                "path": "spec.http[].match[].queryParams.<param>.exact",
                "type": "string",
                "required": False,
                "description": "匹配请求查询参数"
            },
            {
                "path": "spec.http[].route[].destination.host",
                "type": "string",
                "required": False,
                "description": "目标服务名"
            },
            {
                "path": "spec.http[].route[].destination.subset",
                "type": "string",
                "required": False,
                "description": "目标服务子集名"
            },
            {
                "path": "spec.http[].route[].weight",
                "type": "integer",
                "required": False,
                "description": "流量权重"
            },
            {
                "path": "spec.http[].timeout",
                "type": "string",
                "required": False,
                "description": "请求超时时间（如 5s）"
            },
            {
                "path": "spec.http[].retries.attempts",
                "type": "integer",
                "required": False,
                "description": "重试次数"
            },
            {
                "path": "spec.http[].retries.perTryTimeout",
                "type": "string",
                "required": False,
                "description": "每次重试超时时间（如 2s）"
            },
            {
                "path": "spec.http[].rewrite.uri",
                "type": "string",
                "required": False,
                "description": "重写后的请求 URI"
            },
            {
                "path": "spec.http[].redirect.uri",
                "type": "string",
                "required": False,
                "description": "重定向目标 URI"
            }
        ]
    },
    {
        "function": "load_balancing", # 负载均衡
        "config_object": "DestinationRule",
        "fields": [
            {
                "path": "trafficPolicy.loadBalancer.simple",
                "type": "string",
                "required": False,
                "description": "负载均衡策略类型，如 ROUND_ROBIN, RANDOM, LEAST_CONN"
            },
            {
                "path": "trafficPolicy.loadBalancer.consistentHash.httpHeaderName",
                "type": "string",
                "required": False,
                "description": "用于保持会话的一致性哈希头部名"
            }
        ]
    },
    {
        "function": "circuit_breaker", # 熔断
        "config_object": "DestinationRule",
        "fields": [
            {
                "path": "trafficPolicy.connectionPool.http.http1MaxPendingRequests",
                "type": "integer",
                "required": False,
                "description": "HTTP1 最大排队请求数"
            },
            {
                "path": "trafficPolicy.outlierDetection.consecutive5xxErrors",
                "type": "integer",
                "required": False,
                "description": "连续 5xx 错误的阈值"
            },
            {
                "path": "trafficPolicy.outlierDetection.interval",
                "type": "string",
                "required": False,
                "description": "检测间隔时间，格式如 5s"
            },
            {
                "path": "trafficPolicy.outlierDetection.baseEjectionTime",
                "type": "string",
                "required": False,
                "description": "剔除时间，格式如 15s"
            }
        ]
    },
    {
        "function": "fault_injection", # 故障注入
        "config_object": "VirtualService",
        "fields": [
            {
                "path": "http[].fault.delay.fixedDelay",
                "type": "string",
                "required": False,
                "description": "注入的固定延迟时间"
            },
            {
                "path": "http[].fault.delay.percentage.value",
                "type": "number",
                "required": False,
                "description": "注入延迟的百分比（0-100）"
            },
            {
                "path": "http[].fault.abort.httpStatus",
                "type": "integer",
                "required": False,
                "description": "返回 HTTP 错误码"
            },
            {
                "path": "http[].fault.abort.percentage.value",
                "type": "number",
                "required": False,
                "description": "注入错误的百分比"
            },
            {
                "path": "http[].route.destination.host",
                "type": "string",
                "required": False,
                "description": "注入错误的目标服务"
            }
        ]
    },
    {
        "function": "traffic_split", # 灰度发布VS
        "config_object": "VirtualService",
        "fields": [
            {
                "path": "metadata.name",
                "type": "string",
                "required": True,
                "description": "服务名称"
            },
            {
                "path": "http[].match[].headers.<header>.exact",
                "type": "string",
                "required": False,
                "description": "匹配请求头值"
            },
            {
                "path": "http[].route[].destination.host",
                "type": "string",
                "required": True,
                "description": "目标服务名"
            },
            {
                "path": "http[].route[].destination.subset",
                "type": "string",
                "required": False,
                "description": "服务子集名"
            },
            {
                "path": "http[].route[].weight",
                "type": "integer",
                "required": False,
                "description": "流量权重"
            }
        ]
    },
    {
        "function": "traffic_split_destination_rule", # 灰度发布DR
        "config_object": "DestinationRule",
        "fields": [
            {
                "path": "metadata.name",
                "type": "string",
                "required": True,
                "description": "DestinationRule 名称"
            },
            {
                "path": "spec.host",
                "type": "string",
                "required": True,
                "description": "服务名称"
            },
            {
                "path": "spec.subsets[].name",
                "type": "string",
                "required": True,
                "description": "子集名称"
            },
            {
                "path": "spec.subsets[].labels.version",
                "type": "string",
                "required": True,
                "description": "版本标签"
            }
        ]
    },
    {
        "function": "rate_limit_local", # 本地限流
        "config_object": "EnvoyFilter",
        "fields": [
            {
                "path": "spec.workloadSelector.labels.<label>",
                "type": "string",
                "required": True,
                "description": "目标工作负载的标签"
            },
            {
                "path": "spec.configPatches[].applyTo",
                "type": "string",
                "required": True,
                "description": "应用对象类型，通常为 HTTP_FILTER"
            },
            {
                "path": "spec.configPatches[].patch.operation",
                "type": "string",
                "required": True,
                "description": "操作类型，如 INSERT_BEFORE 或 INSERT_AFTER"
            },
            {
                "path": "spec.configPatches[].patch.value.name",
                "type": "string",
                "required": True,
                "description": "过滤器名称：envoy.filters.http.local_ratelimit"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.token_bucket.max_tokens",
                "type": "integer",
                "required": True,
                "description": "令牌桶最大容量（每单位时间允许的请求数）"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.token_bucket.tokens_per_fill",
                "type": "integer",
                "required": True,
                "description": "每次填充的令牌数量"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.token_bucket.fill_interval",
                "type": "string",
                "required": True,
                "description": "填充间隔时间（如 1s）"
            }
        ]
    },
    {
        "function": "rate_limit_global", # 全局限流
        "config_object": "EnvoyFilter",
        "fields": [
            {
                "path": "spec.workloadSelector.labels.<label>",
                "type": "string",
                "required": True,
                "description": "目标工作负载标签"
            },
            {
                "path": "spec.configPatches[].applyTo",
                "type": "string",
                "required": True,
                "description": "应用对象类型，如 HTTP_FILTER"
            },
            {
                "path": "spec.configPatches[].patch.operation",
                "type": "string",
                "required": True,
                "description": "操作类型，如 INSERT_BEFORE"
            },
            {
                "path": "spec.configPatches[].patch.value.name",
                "type": "string",
                "required": True,
                "description": "过滤器名称：envoy.filters.http.ratelimit"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.@type",
                "type": "string",
                "required": True,
                "description": "配置类型：type.googleapis.com/envoy.extensions.filters.http.ratelimit.v3.RateLimit"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.domain",
                "type": "string",
                "required": True,
                "description": "限流策略域（对应 Redis 中的 key）"
            },
            {
                "path": "spec.configPatches[].patch.value.typed_config.rate_limit_service.grpc_service.envoy_grpc.cluster_name",
                "type": "string",
                "required": True,
                "description": "调用的限流服务名称"
            }
        ]
    },
    {
        "function": "ingress_gateway",
        "config_object": "Gateway",
        "fields": [
            {
                "path": "metadata.name",
                "type": "string",
                "required": True,
                "description": "网关名称"
            },
            {
                "path": "spec.selector.istio",
                "type": "string",
                "required": True,
                "description": "选择 ingress gateway"
            },
            {
                "path": "spec.servers[].hosts[]",
                "type": "array<string>",
                "required": True,
                "description": "支持的主机名"
            },
            {
                "path": "spec.servers[].port.number",
                "type": "integer",
                "required": True,
                "description": "监听端口号"
            },
            {
                "path": "spec.servers[].port.protocol",
                "type": "string",
                "required": True,
                "description": "协议类型（HTTP/HTTPS）"
            }
        ]
    },
    {
        "function": "egress_control",
        "config_object": "ServiceEntry",
        "fields": [
            {
                "path": "spec.hosts[]",
                "type": "array<string>",
                "required": True,
                "description": "允许访问的外部域名"
            },
            {
                "path": "spec.ports[].number",
                "type": "integer",
                "required": True,
                "description": "端口号"
            },
            {
                "path": "spec.resolution",
                "type": "string",
                "required": True,
                "description": "DNS 解析模式"
            },
            {
                "path": "spec.location",
                "type": "string",
                "required": True,
                "description": "服务类型（MESH_EXTERNAL）"
            }
        ]
    },
    {
        "function": "authorization",
        "config_object": "AuthorizationPolicy",
        "fields": [
            {
                "path": "rules[].from[].source.requestPrincipals[]",
                "type": "array<string>",
                "required": False,
                "description": "允许访问的身份主体（SPIFFE）"
            },
            {
                "path": "rules[].to[].operation.methods[]",
                "type": "array<string>",
                "required": False,
                "description": "允许的方法（GET/POST 等）"
            }
        ]
    },
    {
        "function": "peer_authentication",
        "config_object": "PeerAuthentication",
        "fields": [
            {
                "path": "spec.mtls.mode",
                "type": "string",
                "required": True,
                "description": "mTLS 模式，如 STRICT 或 PERMISSIVE"
            }
        ]
    }
]

# 示例用途：打印服务信息
if __name__ == "__main__":
    for svc in istio_graph_config["services"]:
        print(f"服务: {svc['name']} (命名空间: {svc['namespace']})")
        print("  应用标签:", svc["appLabel"])
        print("  虚拟服务主机:", svc["istioConfig"]["virtualService"]["hosts"])
        print("  依赖服务:")
        for edge in svc["graphNode"]["edges"]:
            print(f"    → {edge['to']} ({edge['type']})")
