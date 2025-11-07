# MeshScope 模块架构与通信设计

## 📐 三大模块概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MeshScope 系统架构                            │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │   Istio Monitor          │
                    │   (配置监控器)            │
                    └──────────────────────────┘
                        │                 │
                        │ 控制面配置       │ 数据面配置
                        ▼                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  模块一：静态解析和分析模块 (Static Parsing & Analysis)              │
│  istio_config_parser/                                               │
├────────────────────────────────────────────────────────────────────┤
│  输入: YAML配置文件                                                  │
│  输出: control_plane_graph.json + data_plane_graph.json            │
└────────────────────────────────────────────────────────────────────┘
                        │                 │
                        ▼                 │
┌────────────────────────────────────────────────────────────────────┐
│  模块二：动态测试和验证模块 (Dynamic Testing & Verification)         │
│  istio_Dynamic_Test/                                                │
├────────────────────────────────────────────────────────────────────┤
│  输入: control_plane_graph.json + test_requirements.json           │
│  输出: test_matrix.json + collected_data.json                      │
└────────────────────────────────────────────────────────────────────┘
                        │                 │
                        ▼                 ▼
┌────────────────────────────────────────────────────────────────────┐
│  模块三：一致性检验和可视化模块 (Consistency Verification & Viz)     │
│  consistency_verification/                                          │
├────────────────────────────────────────────────────────────────────┤
│  输入: 两个graph.json + test_matrix.json + collected_data.json     │
│  输出: consistency_report.html + inconsistency_graph.json          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 模块一：静态解析和分析模块

### 职责
解析 Istio 配置文件，构建控制平面和数据平面的依赖关系图谱。

### 输入

#### 1. 控制平面配置（由监控器采集）
**来源**: `istio_monitor/istio_control_config/`

```
istio_control_config/
├── services/            # K8s Service 配置
├── virtualservices/     # VirtualService 路由规则
├── destinationrules/    # DestinationRule 流量策略
├── gateways/            # Gateway 网关配置
├── envoyfilters/        # EnvoyFilter 自定义配置
├── serviceentries/      # ServiceEntry 外部服务
└── authorizationpolicies/ # 授权策略
```

**格式**: YAML 文件

#### 2. 数据平面配置（由监控器采集）
**来源**: `istio_monitor/istio_sidecar_config/`

```json
{
  "routes": [
    {
      "name": "9080",
      "virtualHosts": [
        {
          "name": "reviews.default.svc.cluster.local:9080",
          "domains": ["reviews", "reviews.default.svc.cluster.local"],
          "routes": [...]
        }
      ]
    }
  ]
}
```

**格式**: JSON 格式的 Envoy 配置

### 处理流程

```python
# main_parser.py 核心流程
def parse_static_configs():
    # 1. 解析控制平面配置
    control_plane_data = parse_control_plane_from_dir('istio_control_config/')
    
    # 2. 解析数据平面配置
    data_plane_data = parse_data_plane_from_dir('istio_sidecar_config/')
    
    # 3. 构建依赖图
    control_graph = build_control_plane_graph(control_plane_data)
    data_graph = build_data_plane_graph(data_plane_data)
    
    # 4. 输出标准化格式
    return {
        'control_plane_graph': control_graph,
        'data_plane_graph': data_graph,
        'timestamp': datetime.now().isoformat()
    }
```

### 输出

#### 输出文件 1: `control_plane_graph.json`

```json
{
  "metadata": {
    "generated_at": "2025-01-15T10:30:00Z",
    "namespace": "default",
    "total_services": 5
  },
  "services": [
    {
      "name": "reviews",
      "namespace": "default",
      "type": "ClusterIP",
      "ports": [{"name": "http", "port": 9080}],
      "versions": ["v1", "v2", "v3"]
    }
  ],
  "policies": [
    {
      "id": "reviews-vs-001",
      "type": "VirtualService",
      "service": "reviews",
      "namespace": "default",
      "config": {
        "routing": {
          "match": [{"headers": {"user-agent": {"exact": "jason"}}}],
          "route": [{"destination": {"host": "reviews", "subset": "v2"}}]
        },
        "retry": {"attempts": 3, "perTryTimeout": "2s"},
        "timeout": "5s"
      },
      "scope": "local",
      "priority": 1
    },
    {
      "id": "reviews-dr-001",
      "type": "DestinationRule",
      "service": "reviews",
      "namespace": "default",
      "config": {
        "subsets": [
          {"name": "v1", "labels": {"version": "v1"}},
          {"name": "v2", "labels": {"version": "v2"}},
          {"name": "v3", "labels": {"version": "v3"}}
        ],
        "trafficPolicy": {
          "loadBalancer": {"simple": "ROUND_ROBIN"},
          "connectionPool": {
            "tcp": {"maxConnections": 100},
            "http": {"http1MaxPendingRequests": 100}
          },
          "outlierDetection": {
            "consecutiveErrors": 5,
            "interval": "10s",
            "baseEjectionTime": "30s"
          }
        }
      },
      "scope": "global",
      "priority": 2
    }
  ],
  "dependencies": [
    {
      "source": "productpage",
      "target": "reviews",
      "type": "calls",
      "protocol": "HTTP"
    },
    {
      "source": "reviews",
      "target": "ratings",
      "type": "calls",
      "protocol": "HTTP"
    }
  ],
  "policy_relations": [
    {
      "policy_id": "reviews-vs-001",
      "depends_on": ["reviews-dr-001"],
      "affects": ["reviews"],
      "conflict_with": []
    }
  ]
}
```

#### 输出文件 2: `data_plane_graph.json`

```json
{
  "metadata": {
    "generated_at": "2025-01-15T10:30:00Z",
    "source": "envoy_config_dump",
    "pod": "reviews-v2-xxx"
  },
  "routes": [
    {
      "name": "9080",
      "service": "reviews",
      "virtual_hosts": [
        {
          "name": "reviews.default.svc.cluster.local:9080",
          "domains": ["reviews", "reviews.default.svc.cluster.local"],
          "routes": [
            {
              "match": {
                "prefix": "/",
                "headers": [
                  {"name": "user-agent", "exact_match": "jason"}
                ]
              },
              "route": {
                "cluster": "outbound|9080|v2|reviews.default.svc.cluster.local",
                "timeout": "5s",
                "retry_policy": {
                  "retry_on": "5xx",
                  "num_retries": 3,
                  "per_try_timeout": "2s"
                }
              },
              "priority": 1
            },
            {
              "match": {"prefix": "/"},
              "route": {
                "weighted_clusters": {
                  "clusters": [
                    {
                      "name": "outbound|9080|v1|reviews.default.svc.cluster.local",
                      "weight": 80
                    },
                    {
                      "name": "outbound|9080|v3|reviews.default.svc.cluster.local",
                      "weight": 20
                    }
                  ]
                }
              },
              "priority": 2
            }
          ]
        }
      ]
    }
  ],
  "clusters": [
    {
      "name": "outbound|9080|v2|reviews.default.svc.cluster.local",
      "type": "EDS",
      "lb_policy": "ROUND_ROBIN",
      "circuit_breakers": {
        "thresholds": [
          {
            "max_connections": 100,
            "max_pending_requests": 100,
            "max_requests": 1000
          }
        ]
      },
      "outlier_detection": {
        "consecutive_5xx": 5,
        "interval": "10s",
        "base_ejection_time": "30s"
      }
    }
  ]
}
```

### 实现代码

```python
# istio_config_parser/graph_builder.py

from typing import Dict, List, Any
import json
from datetime import datetime

class ControlPlaneGraphBuilder:
    """构建控制平面配置依赖图"""
    
    def __init__(self, control_plane_data: Dict):
        self.data = control_plane_data
        self.graph = {
            'metadata': {},
            'services': [],
            'policies': [],
            'dependencies': [],
            'policy_relations': []
        }
    
    def build(self) -> Dict:
        """构建完整的控制平面图谱"""
        self._build_metadata()
        self._build_services()
        self._build_policies()
        self._build_dependencies()
        self._build_policy_relations()
        return self.graph
    
    def _build_services(self):
        """提取服务信息"""
        for service in self.data.get('services', []):
            service_node = {
                'name': service['name'],
                'namespace': service['namespace'],
                'type': service['type'],
                'ports': service['ports'],
                'versions': self._extract_versions(service['name'])
            }
            self.graph['services'].append(service_node)
    
    def _build_policies(self):
        """提取策略配置"""
        # 处理 VirtualService
        for service, relations in self.data['serviceRelations'].items():
            for vs in relations.get('incomingVirtualServices', []):
                policy = {
                    'id': f"{service}-vs-{vs['name']}",
                    'type': 'VirtualService',
                    'service': service,
                    'namespace': vs['namespace'],
                    'config': self._extract_vs_config(vs),
                    'scope': 'local',
                    'priority': 1
                }
                self.graph['policies'].append(policy)
        
        # 处理 DestinationRule
        for service, config in self.data['configurations'].items():
            if config.get('circuitBreaker'):
                policy = {
                    'id': f"{service}-dr-001",
                    'type': 'DestinationRule',
                    'service': service,
                    'config': config['circuitBreaker'],
                    'scope': 'global',
                    'priority': 2
                }
                self.graph['policies'].append(policy)
    
    def save_to_file(self, output_path: str):
        """保存图谱到文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.graph, f, indent=2, ensure_ascii=False)


class DataPlaneGraphBuilder:
    """构建数据平面配置依赖图"""
    
    def __init__(self, data_plane_data: Dict):
        self.data = data_plane_data
        self.graph = {
            'metadata': {},
            'routes': [],
            'clusters': []
        }
    
    def build(self) -> Dict:
        """构建完整的数据平面图谱"""
        self._build_metadata()
        self._build_routes()
        self._build_clusters()
        return self.graph
    
    def _build_routes(self):
        """提取路由配置"""
        for route_config in self.data.get('routes', []):
            route_node = {
                'name': route_config.get('name'),
                'service': self._extract_service_from_route(route_config),
                'virtual_hosts': self._process_virtual_hosts(route_config.get('virtualHosts', []))
            }
            self.graph['routes'].append(route_node)
    
    def save_to_file(self, output_path: str):
        """保存图谱到文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.graph, f, indent=2, ensure_ascii=False)
```

---

## 🚀 模块二：动态测试和验证模块

### 职责
基于控制平面配置和测试需求，生成正交测试用例，执行测试并收集运行时数据。

### 输入

#### 输入文件 1: `control_plane_graph.json`
（来自模块一的输出）

#### 输入文件 2: `test_requirements.json`

```json
{
  "test_scope": {
    "namespace": "default",
    "services": ["reviews", "ratings", "productpage"],
    "policies_to_test": [
      "routing",
      "traffic_split",
      "retry",
      "circuit_breaker",
      "timeout"
    ]
  },
  "test_config": {
    "ingress_url": "http://192.168.92.131:30476/productpage",
    "ssh_config": {
      "host": "192.168.92.131",
      "username": "root",
      "password": "12345678"
    },
    "test_duration": "5m",
    "enable_fault_injection": true
  }
}
```

### 处理流程

```python
# istio_Dynamic_Test/test_orchestrator.py

class DynamicTestOrchestrator:
    """动态测试编排器"""
    
    def __init__(self, control_graph_file: str, test_requirements_file: str):
        self.control_graph = self._load_json(control_graph_file)
        self.test_requirements = self._load_json(test_requirements_file)
    
    def run_tests(self) -> Dict:
        """执行完整的测试流程"""
        # 步骤1：生成正交测试用例
        test_matrix = self._generate_test_matrix()
        
        # 步骤2：执行测试用例（并行收集数据）
        execution_results = self._execute_tests(test_matrix)
        
        # 步骤3：收集运行时数据
        collected_data = self._collect_runtime_data(execution_results)
        
        # 步骤4：输出结果
        return {
            'test_matrix': test_matrix,
            'collected_data': collected_data
        }
    
    def _generate_test_matrix(self) -> Dict:
        """生成正交测试矩阵"""
        generator = TestCaseGenerator(
            config=self._convert_graph_to_config(self.control_graph),
            test_scope=self.test_requirements['test_scope']
        )
        return generator.generate()
    
    def _execute_tests(self, test_matrix: Dict) -> Dict:
        """执行测试并同时收集数据"""
        driver = TrafficDriver(
            matrix=test_matrix,
            ssh_config=self.test_requirements['test_config']['ssh_config']
        )
        return driver.run_with_collection()
```

### 输出

#### 输出文件 1: `test_matrix.json`

```json
{
  "metadata": {
    "generated_at": "2025-01-15T10:35:00Z",
    "source_graph": "control_plane_graph.json",
    "total_test_cases": 8,
    "orthogonal_principle": "4-dimension"
  },
  "global_settings": {
    "ingress_url": "http://192.168.92.131:30476/productpage"
  },
  "test_cases": [
    {
      "case_id": "case_001",
      "description": "正交匹配组合测试(reviews+ratings) -> v2",
      "type": "single_request",
      "test_strategies": ["orthogonal_matching"],
      "target_hosts": ["reviews", "ratings"],
      "request_params": {
        "headers": {"user-agent": "jason"},
        "path": "/test"
      },
      "expected_behavior": {
        "orthogonal_hits": [
          {
            "host": "reviews",
            "destination": "v2",
            "match_condition": {"headers": {"user-agent": "jason"}}
          },
          {
            "host": "ratings",
            "destination": "v2",
            "match_condition": {"path": "/test"}
          }
        ]
      },
      "policy_mapping": {
        "control_plane_policies": ["reviews-vs-001", "ratings-vs-001"],
        "expected_data_plane_routes": [
          "outbound|9080|v2|reviews.default.svc.cluster.local"
        ]
      }
    },
    {
      "case_id": "case_002",
      "description": "流量分割测试 - 80% v1, 20% v3",
      "type": "load_test",
      "test_strategies": ["traffic_split"],
      "target_hosts": ["reviews"],
      "request_params": {
        "host": "reviews",
        "path": "/"
      },
      "load_params": {
        "num_requests": 62,
        "concurrency": 1
      },
      "expected_behavior": {
        "distribution": {"v1": 0.8, "v3": 0.2},
        "margin_of_error": 0.1
      },
      "policy_mapping": {
        "control_plane_policies": ["reviews-vs-002"],
        "expected_data_plane_routes": [
          "outbound|9080|v1|reviews.default.svc.cluster.local",
          "outbound|9080|v3|reviews.default.svc.cluster.local"
        ]
      }
    },
    {
      "case_id": "case_003",
      "description": "全局/局部正交组合测试(circuit_breaker+retry)",
      "type": "load_test",
      "test_strategies": ["circuit_breaker", "retry"],
      "target_hosts": ["reviews"],
      "request_params": {
        "host": "reviews",
        "trigger_condition": "simulate_503_error"
      },
      "load_params": {
        "num_requests": 60,
        "concurrency": 10
      },
      "expected_behavior": {
        "retry_attempts": 3,
        "circuit_breaker_threshold": 5,
        "expected_503_rate": 0.8
      },
      "policy_mapping": {
        "control_plane_policies": ["reviews-vs-001", "reviews-dr-001"],
        "expected_data_plane_config": {
          "retry": {"num_retries": 3, "per_try_timeout": "2s"},
          "outlier_detection": {"consecutive_5xx": 5}
        }
      }
    }
  ]
}
```

#### 输出文件 2: `collected_data.json`

```json
{
  "metadata": {
    "collection_time": "2025-01-15T10:40:00Z",
    "duration": "5m",
    "total_requests": 200
  },
  "http_results": {
    "case_001": {
      "status_codes": {"200": 1},
      "total_requests": 1,
      "success_rate": 100.0,
      "avg_response_time": 0.045,
      "details": {
        "reviews_response": {"status": 200, "time": 0.043},
        "ratings_response": {"status": 200, "time": 0.047}
      }
    },
    "case_002": {
      "status_codes": {"200": 62},
      "total_requests": 62,
      "success_rate": 100.0,
      "avg_response_time": 0.052,
      "version_distribution": {
        "v1": {"count": 48, "percentage": 0.774},
        "v3": {"count": 14, "percentage": 0.226}
      }
    },
    "case_003": {
      "status_codes": {"200": 12, "503": 48},
      "total_requests": 60,
      "success_rate": 20.0,
      "avg_response_time": 0.123,
      "circuit_breaker_triggered": true,
      "retry_count": 3
    }
  },
  "envoy_logs": {
    "case_001": {
      "pod": "reviews-v2-xxx",
      "entries": [
        {
          "timestamp": "2025-01-15T10:35:01.123Z",
          "method": "GET",
          "path": "/test",
          "status_code": 200,
          "response_time": 43,
          "upstream_cluster": "outbound|9080|v2|reviews.default.svc.cluster.local",
          "user_agent": "jason"
        }
      ]
    },
    "case_002": {
      "pod": "reviews-v1-yyy",
      "entry_count": 48,
      "pod": "reviews-v3-zzz",
      "entry_count": 14
    }
  },
  "metrics": {
    "case_003": {
      "istio_requests_total": 60,
      "istio_request_duration_p95": 0.156,
      "istio_request_duration_p99": 0.234,
      "circuit_breaker_ejections": 3
    }
  },
  "traces": {
    "case_001": {
      "trace_id": "abc123",
      "spans": [
        {
          "service": "productpage",
          "operation": "GET /test",
          "duration": 45
        },
        {
          "service": "reviews-v2",
          "operation": "GET /reviews/2",
          "duration": 43
        }
      ]
    }
  }
}
```

---

## 🔍 模块三：一致性检验和可视化模块

### 职责
融合静态和动态分析结果，进行多维度一致性检测，生成可视化报告。

### 输入

#### 输入文件 1: `control_plane_graph.json` （来自模块一）
#### 输入文件 2: `data_plane_graph.json` （来自模块一）
#### 输入文件 3: `test_matrix.json` （来自模块二）
#### 输入文件 4: `collected_data.json` （来自模块二）

### 处理流程

```python
# consistency_verification/consistency_engine.py

class ConsistencyEngine:
    """一致性检测引擎"""
    
    def __init__(self, inputs: Dict[str, str]):
        self.control_graph = self._load_json(inputs['control_plane_graph'])
        self.data_graph = self._load_json(inputs['data_plane_graph'])
        self.test_matrix = self._load_json(inputs['test_matrix'])
        self.collected_data = self._load_json(inputs['collected_data'])
    
    def verify_consistency(self) -> Dict:
        """执行完整的一致性检测"""
        results = {
            'static_consistency': {},
            'dynamic_consistency': {},
            'overall_consistency': {}
        }
        
        # 维度1：静态一致性 - 控制平面 vs 数据平面
        results['static_consistency'] = self._check_static_consistency()
        
        # 维度2：动态一致性 - 预期行为 vs 实际行为
        results['dynamic_consistency'] = self._check_dynamic_consistency()
        
        # 维度3：综合一致性评估
        results['overall_consistency'] = self._evaluate_overall_consistency(
            results['static_consistency'],
            results['dynamic_consistency']
        )
        
        return results
    
    def _check_static_consistency(self) -> Dict:
        """检查静态一致性（控制平面 vs 数据平面）"""
        checker = StaticConsistencyChecker(
            self.control_graph,
            self.data_graph
        )
        return checker.check()
    
    def _check_dynamic_consistency(self) -> Dict:
        """检查动态一致性（预期 vs 实际）"""
        checker = DynamicConsistencyChecker(
            self.test_matrix,
            self.collected_data
        )
        return checker.check()
```

### 输出

#### 输出文件 1: `consistency_report.json`

```json
{
  "metadata": {
    "generated_at": "2025-01-15T10:45:00Z",
    "total_checks": 15,
    "passed": 12,
    "failed": 3
  },
  "static_consistency": {
    "control_vs_data_plane": {
      "total_policies": 8,
      "consistent": 6,
      "inconsistent": 2,
      "details": [
        {
          "policy_id": "reviews-vs-001",
          "status": "consistent",
          "control_plane_config": {
            "match": [{"headers": {"user-agent": {"exact": "jason"}}}],
            "route": [{"destination": {"host": "reviews", "subset": "v2"}}],
            "retry": {"attempts": 3, "perTryTimeout": "2s"}
          },
          "data_plane_config": {
            "match": {"headers": [{"name": "user-agent", "exact_match": "jason"}]},
            "route": {"cluster": "outbound|9080|v2|reviews.default.svc.cluster.local"},
            "retry_policy": {"num_retries": 3, "per_try_timeout": "2s"}
          },
          "verification": {
            "match_rule": "✓ 一致",
            "route_target": "✓ 一致",
            "retry_policy": "✓ 一致"
          }
        },
        {
          "policy_id": "reviews-dr-001",
          "status": "inconsistent",
          "inconsistency_type": "config_mismatch",
          "severity": "high",
          "control_plane_config": {
            "outlierDetection": {
              "consecutiveErrors": 5,
              "interval": "10s",
              "baseEjectionTime": "30s"
            }
          },
          "data_plane_config": {
            "outlier_detection": {
              "consecutive_5xx": 3,
              "interval": "10s",
              "base_ejection_time": "30s"
            }
          },
          "verification": {
            "consecutive_errors": "✗ 不一致 (期望5, 实际3)",
            "interval": "✓ 一致",
            "base_ejection_time": "✓ 一致"
          },
          "root_cause": "数据平面配置未同步，可能是配置推送延迟或版本不匹配",
          "remediation": "检查 Pilot 配置推送状态，重启 Envoy sidecar"
        }
      ]
    }
  },
  "dynamic_consistency": {
    "behavior_verification": {
      "total_test_cases": 8,
      "passed": 6,
      "failed": 2,
      "details": [
        {
          "case_id": "case_002",
          "status": "passed",
          "test_strategy": "traffic_split",
          "expected_behavior": {
            "distribution": {"v1": 0.8, "v3": 0.2},
            "margin_of_error": 0.1
          },
          "actual_behavior": {
            "distribution": {"v1": 0.774, "v3": 0.226},
            "deviation": {"v1": 0.026, "v3": 0.026}
          },
          "verification": "✓ 流量分布符合预期（偏差 ≤ 10%）"
        },
        {
          "case_id": "case_003",
          "status": "failed",
          "test_strategy": "circuit_breaker+retry",
          "expected_behavior": {
            "retry_attempts": 3,
            "circuit_breaker_threshold": 5
          },
          "actual_behavior": {
            "retry_attempts": 0,
            "circuit_breaker_triggered": false
          },
          "verification": "✗ 重试策略未生效，熔断未触发",
          "root_cause": "VirtualService retry配置在数据平面未生效",
          "remediation": "检查 VirtualService 配置同步状态，验证 Envoy filter chain"
        }
      ]
    }
  },
  "overall_consistency": {
    "consistency_rate": 80.0,
    "status": "warning",
    "critical_issues": 2,
    "summary": "检测到 2 个高严重性不一致问题，建议立即修复"
  }
}
```

#### 输出文件 2: `inconsistency_graph.json`

```json
{
  "nodes": [
    {
      "id": "reviews",
      "type": "service",
      "label": "reviews",
      "consistency_rate": 75.0,
      "color": "#FFC107",
      "issues": [
        {
          "type": "config_mismatch",
          "severity": "high",
          "description": "熔断阈值配置不一致"
        },
        {
          "type": "behavior_deviation",
          "severity": "high",
          "description": "重试策略未生效"
        }
      ]
    },
    {
      "id": "reviews-vs-001",
      "type": "policy",
      "label": "VirtualService",
      "status": "consistent",
      "color": "#81C784"
    },
    {
      "id": "reviews-dr-001",
      "type": "policy",
      "label": "DestinationRule",
      "status": "inconsistent",
      "color": "#E57373"
    }
  ],
  "edges": [
    {
      "source": "reviews",
      "target": "reviews-vs-001",
      "type": "has_policy",
      "color": "#81C784"
    },
    {
      "source": "reviews",
      "target": "reviews-dr-001",
      "type": "has_policy",
      "color": "#E57373",
      "label": "配置不一致"
    }
  ],
  "markers": [
    {
      "position": "reviews-dr-001",
      "type": "inconsistency",
      "severity": "high",
      "icon": "⚠️",
      "tooltip": "控制平面配置 consecutiveErrors=5，数据平面实际为 3"
    }
  ]
}
```

---

## 🔄 完整数据流示例

### 端到端流程脚本

```bash
#!/bin/bash
# complete_verification_pipeline.sh

echo "=== MeshScope 完整验证流水线 ==="

# 步骤1：静态解析
echo "[1/4] 静态配置解析..."
python istio_config_parser/main_parser.py \
  --control-config istio_monitor/istio_control_config \
  --data-config istio_monitor/istio_sidecar_config \
  --output-control output/control_plane_graph.json \
  --output-data output/data_plane_graph.json

# 步骤2：动态测试
echo "[2/4] 动态测试执行..."
python istio_Dynamic_Test/test_orchestrator.py \
  --control-graph output/control_plane_graph.json \
  --test-requirements test_requirements.json \
  --output-matrix output/test_matrix.json \
  --output-data output/collected_data.json

# 步骤3：一致性检测
echo "[3/4] 一致性检测..."
python consistency_verification/consistency_engine.py \
  --control-graph output/control_plane_graph.json \
  --data-graph output/data_plane_graph.json \
  --test-matrix output/test_matrix.json \
  --collected-data output/collected_data.json \
  --output-report output/consistency_report.json \
  --output-graph output/inconsistency_graph.json

# 步骤4：可视化报告
echo "[4/4] 生成可视化报告..."
python consistency_verification/report_generator.py \
  --consistency-report output/consistency_report.json \
  --inconsistency-graph output/inconsistency_graph.json \
  --output-html output/consistency_report.html

echo "=== 验证完成 ==="
echo "报告路径: output/consistency_report.html"
```

---

## 📊 接口规范

### 模块间通信接口

#### 接口 1: 静态解析输出接口

```python
# istio_config_parser/interfaces.py

from typing import Dict, List
from dataclasses import dataclass

@dataclass
class StaticAnalysisOutput:
    """静态分析模块输出接口"""
    control_plane_graph: Dict
    data_plane_graph: Dict
    
    def to_files(self, output_dir: str):
        """保存到文件"""
        import json
        with open(f"{output_dir}/control_plane_graph.json", 'w') as f:
            json.dump(self.control_plane_graph, f, indent=2)
        with open(f"{output_dir}/data_plane_graph.json", 'w') as f:
            json.dump(self.data_plane_graph, f, indent=2)
```

#### 接口 2: 动态测试输出接口

```python
# istio_Dynamic_Test/interfaces.py

from typing import Dict
from dataclasses import dataclass

@dataclass
class DynamicTestOutput:
    """动态测试模块输出接口"""
    test_matrix: Dict
    collected_data: Dict
    
    def to_files(self, output_dir: str):
        """保存到文件"""
        import json
        with open(f"{output_dir}/test_matrix.json", 'w') as f:
            json.dump(self.test_matrix, f, indent=2)
        with open(f"{output_dir}/collected_data.json", 'w') as f:
            json.dump(self.collected_data, f, indent=2)
```

#### 接口 3: 一致性检测输入接口

```python
# consistency_verification/interfaces.py

from typing import Dict
from dataclasses import dataclass

@dataclass
class ConsistencyVerificationInput:
    """一致性检测模块输入接口"""
    control_plane_graph: Dict
    data_plane_graph: Dict
    test_matrix: Dict
    collected_data: Dict
    
    @classmethod
    def from_files(cls, file_paths: Dict[str, str]):
        """从文件加载"""
        import json
        return cls(
            control_plane_graph=cls._load_json(file_paths['control_graph']),
            data_plane_graph=cls._load_json(file_paths['data_graph']),
            test_matrix=cls._load_json(file_paths['test_matrix']),
            collected_data=cls._load_json(file_paths['collected_data'])
        )
```

---

**MeshScope** - 模块化、标准化的 Istio 配置验证平台！ 🚀


