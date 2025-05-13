"""
数据平面配置结构说明
"""

DATA_PLANE_SCHEMA = {
    "serviceRelations": {
        "service_name": {              # 服务名称作为键
            "inbound": [               # 入站路由
                {
                    "name": "string",    # 路由名称
                    "domains": [],       # 域名列表
                    "routes": [          # 路由规则
                        {
                            "match": {},  # 匹配条件
                            "route": {    # 路由信息
                                "cluster": "string",  # 单一集群
                                "weightedClusters": { # 加权集群
                                    "clusters": [
                                        {
                                            "name": "string",  # 集群名称
                                            "weight": "int"    # 权重
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            ],
            "outbound": [              # 出站路由
                {
                    "service": "string", # 目标服务
                    "port": "string"    # 目标端口
                }
            ],
            "weights": {               # 版本权重
                "version": "int"       # 版本:权重
            }
        }
    }
}

# 数据平面配置示例
DATA_PLANE_EXAMPLE = {
    "serviceRelations": {
        "reviews": {
            "inbound": [
                {
                    "name": "reviews-route",
                    "domains": ["reviews.default.svc.cluster.local"],
                    "routes": [
                        {
                            "match": {"prefix": "/"},
                            "route": {
                                "weightedClusters": {
                                    "clusters": [
                                        {
                                            "name": "outbound|9080|v1|reviews.default.svc.cluster.local",
                                            "weight": 80
                                        },
                                        {
                                            "name": "outbound|9080|v2|reviews.default.svc.cluster.local",
                                            "weight": 20
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            ],
            "outbound": [
                {
                    "service": "ratings",
                    "port": "9080"
                }
            ],
            "weights": {
                "v1": 80,
                "v2": 20
            }
        }
    }
} 