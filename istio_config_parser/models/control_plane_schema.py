"""
控制平面配置结构说明
"""

CONTROL_PLANE_SCHEMA = {
    "services": [
        {
            "name": "string",           # 服务名称
            "namespace": "string",      # 命名空间
            "type": "string",          # 服务类型
            "ports": [                 # 服务端口列表
                {
                    "name": "string",   # 端口名称
                    "port": "int",      # 端口号
                    "targetPort": "int", # 目标端口
                    "protocol": "string" # 协议
                }
            ],
            "selector": {              # 服务选择器
                "app": "string"        # 应用标签
            }
        }
    ],
    "serviceRelations": {
        "service_name": {              # 服务名称作为键
            "incomingVirtualServices": [  # 入站虚拟服务
                {
                    "name": "string",    # 虚拟服务名称
                    "rules": [           # 路由规则
                        {
                            "match": [],  # 匹配条件
                            "route": []   # 路由目标
                        }
                    ]
                }
            ],
            "subsets": [               # 服务子集
                {
                    "name": "string",    # 子集名称
                    "version": "string", # 版本
                    "labels": {},        # 标签
                    "weights": "int"     # 权重
                }
            ],
            "rateLimit": [             # 限流规则
                {
                    "type": "string",    # 限流类型
                    "requests_per_unit": "int", # 请求数
                    "unit": "string",    # 时间单位
                    "conditions": []     # 限流条件
                }
            ],
            "gateways": [              # 网关配置
                {
                    "name": "string",    # 网关名称
                    "type": "string",    # 网关类型
                    "virtualService": "string" # 关联的虚拟服务
                }
            ],
            "circuitBreaker": {        # 熔断规则
                "global": {             # 全局熔断配置
                    "connectionPool": {  # 连接池配置
                        "http": {        # HTTP连接池设置
                            "http1MaxPendingRequests": "int",  # HTTP1.1最大等待请求数
                            "http2MaxRequests": "int",        # HTTP2最大请求数
                            "maxRequestsPerConnection": "int", # 每连接最大请求数
                            "maxRetries": "int"              # 最大重试次数
                        },
                        "tcp": {         # TCP连接池设置
                            "maxConnections": "int",         # 最大连接数
                            "connectTimeout": "string"       # 连接超时时间
                        }
                    },
                    "outlierDetection": { # 异常检测配置
                        "baseEjectionTime": "string",        # 基础驱逐时间
                        "consecutive5xxErrors": "int",       # 连续5xx错误数
                        "interval": "string",                # 检测间隔
                        "maxEjectionPercent": "int",         # 最大驱逐百分比
                        "minHealthPercent": "int"            # 最小健康百分比
                    }
                },
                "subsets": {            # 子集特定的熔断配置
                    "subset_name": {     # 子集名称作为键
                        "connectionPool": {  # 连接池配置
                            "http": {        # HTTP连接池设置
                                "http1MaxPendingRequests": "int",
                                "http2MaxRequests": "int",
                                "maxRequestsPerConnection": "int",
                                "maxRetries": "int"
                            },
                            "tcp": {         # TCP连接池设置
                                "maxConnections": "int",
                                "connectTimeout": "string"
                            }
                        },
                        "outlierDetection": { # 异常检测配置
                            "baseEjectionTime": "string",
                            "consecutive5xxErrors": "int",
                            "interval": "string",
                            "maxEjectionPercent": "int",
                            "minHealthPercent": "int"
                        }
                    }
                }
            }
        }
    },
    "configurations": {
        "service_name": {              # 服务名称作为键
            "virtualServices": [],      # 虚拟服务配置
            "destinationRules": [],     # 目标规则配置
            "envoyFilters": [],          # Envoy过滤器配置
            "circuitBreaker": {         # 熔断配置
                "global": {             # 全局熔断配置
                    "connectionPool": {  # 连接池配置
                        "http": {        # HTTP连接池设置
                            "http1MaxPendingRequests": "int",
                            "http2MaxRequests": "int",
                            "maxRequestsPerConnection": "int",
                            "maxRetries": "int"
                        },
                        "tcp": {         # TCP连接池设置
                            "maxConnections": "int",
                            "connectTimeout": "string"
                        }
                    },
                    "outlierDetection": { # 异常检测配置
                        "baseEjectionTime": "string",
                        "consecutive5xxErrors": "int",
                        "interval": "string",
                        "maxEjectionPercent": "int",
                        "minHealthPercent": "int"
                    }
                },
                "subsets": {            # 子集特定的熔断配置
                    "subset_name": None  # 可能为None表示无特定配置，或者包含完整配置
                }
            }
        }
    }
} 