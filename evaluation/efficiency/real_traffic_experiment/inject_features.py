#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按功能单元递增注入 Istio 配置：路由/分流/熔断/重试/限流。"""


import argparse
import json
import random
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

FEATURE_TYPES = ("routing", "traffic_shifting", "circuit_breaker", "retry", "rate_limit")


def svc_name(i: int) -> str:
    return "meshscope-svc-{0:04d}".format(i)


def path_for(i: int) -> str:
    return "/s{0}/".format(i)


@dataclass
class FeatureSpec:
    feature_id: int
    feature_type: str
    service_index: int
    service: str
    resource_kind: str
    resource_name: str
    yaml_content: str
    branches: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def kubectl_apply(content: str) -> None:
    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=content,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError("kubectl apply failed: {0}".format(proc.stderr or proc.stdout))


class FeatureInjector:
    """功能配置注入器：每个功能是一个可验证的功能单元。"""

    def __init__(self, namespace: str, n_services: int, seed: int = 42):
        self.namespace = namespace
        self.n_services = n_services
        self.rng = random.Random(seed)
        self.features: List[FeatureSpec] = []
        self.next_id = 1

    def ensure_feature_count(self, target: int) -> List[FeatureSpec]:
        while len(self.features) < target:
            # 轮转功能类型，保证类型覆盖
            ftype = FEATURE_TYPES[(self.next_id - 1) % len(FEATURE_TYPES)]
            feature = self._create(ftype)
            kubectl_apply(feature.yaml_content)
            self.features.append(feature)
            print(
                "[feature] #{0} {1} -> {2}".format(
                    feature.feature_id, feature.feature_type, feature.service
                )
            )
        return self.features

    def _pick_service(self) -> int:
        return self.rng.randint(1, self.n_services)

    def _labels(self, fid: int, ftype: str) -> Dict[str, str]:
        return {
            "meshscope/exp": "real-traffic",
            "meshscope/feature-id": str(fid),
            "meshscope/feature-type": ftype,
        }

    def _create(self, ftype: str) -> FeatureSpec:
        fid = self.next_id
        self.next_id += 1
        idx = self._pick_service()
        if ftype == "routing":
            return self._routing(fid, idx)
        if ftype == "traffic_shifting":
            return self._traffic_shifting(fid, idx)
        if ftype == "circuit_breaker":
            return self._circuit_breaker(fid, idx)
        if ftype == "retry":
            return self._retry(fid, idx)
        return self._rate_limit(fid, idx)

    def _routing(self, fid: int, idx: int) -> FeatureSpec:
        svc = svc_name(idx)
        name = "feat-routing-{0}".format(fid)
        header = "x-meshscope-route"
        value = "f{0}".format(fid)
        match_path = "{0}route-{1}/".format(path_for(idx), fid)
        # 命中 header -> v2；默认 -> v1
        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": self._labels(fid, "routing"),
            },
            "spec": {
                "hosts": ["*"],
                "gateways": ["meshscope-gw"],
                "http": [
                    {
                        "name": "branch-match",
                        "match": [
                            {
                                "headers": {header: {"exact": value}},
                                "uri": {"prefix": match_path},
                            }
                        ],
                        "rewrite": {"uri": "/"},
                        "route": [
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v2",
                                    "port": {"number": 80},
                                }
                            }
                        ],
                    },
                    {
                        "name": "branch-default",
                        "match": [{"uri": {"prefix": match_path}}],
                        "rewrite": {"uri": "/"},
                        "route": [
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v1",
                                    "port": {"number": 80},
                                }
                            }
                        ],
                    },
                ],
            },
        }
        branches = [
            {
                "branch_id": "routing_match",
                "path": match_path,
                "headers": {header: value},
                "expect_subset": "v2",
                "expect_status": 200,
            },
            {
                "branch_id": "routing_default",
                "path": match_path,
                "headers": {},
                "expect_subset": "v1",
                "expect_status": 200,
            },
        ]
        return FeatureSpec(
            feature_id=fid,
            feature_type="routing",
            service_index=idx,
            service=svc,
            resource_kind="VirtualService",
            resource_name=name,
            yaml_content=yaml.safe_dump(vs, allow_unicode=True),
            branches=branches,
            metadata={"header": header, "value": value, "match_path": match_path},
        )

    def _traffic_shifting(self, fid: int, idx: int) -> FeatureSpec:
        svc = svc_name(idx)
        name = "feat-split-{0}".format(fid)
        match_path = "{0}split-{1}/".format(path_for(idx), fid)
        w1, w2 = 70, 30
        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": self._labels(fid, "traffic_shifting"),
            },
            "spec": {
                "hosts": ["*"],
                "gateways": ["meshscope-gw"],
                "http": [
                    {
                        "name": "branch-split",
                        "match": [{"uri": {"prefix": match_path}}],
                        "rewrite": {"uri": "/"},
                        "route": [
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v1",
                                    "port": {"number": 80},
                                },
                                "weight": w1,
                            },
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v2",
                                    "port": {"number": 80},
                                },
                                "weight": w2,
                            },
                        ],
                    }
                ],
            },
        }
        branches = [
            {
                "branch_id": "split_sample",
                "path": match_path,
                "headers": {},
                "expect_status": 200,
                "repeat": 20,
                "expect_weight_hint": {"v1": w1, "v2": w2},
            }
        ]
        return FeatureSpec(
            feature_id=fid,
            feature_type="traffic_shifting",
            service_index=idx,
            service=svc,
            resource_kind="VirtualService",
            resource_name=name,
            yaml_content=yaml.safe_dump(vs, allow_unicode=True),
            branches=branches,
            metadata={"weights": {"v1": w1, "v2": w2}, "match_path": match_path},
        )

    def _circuit_breaker(self, fid: int, idx: int) -> FeatureSpec:
        svc = svc_name(idx)
        name = "feat-cb-{0}".format(fid)
        # 更新 DestinationRule：outlierDetection
        dr = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "DestinationRule",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": self._labels(fid, "circuit_breaker"),
            },
            "spec": {
                "host": svc,
                "subsets": [
                    {"name": "v1", "labels": {"version": "v1"}},
                    {"name": "v2", "labels": {"version": "v2"}},
                ],
                "trafficPolicy": {
                    "connectionPool": {
                        "tcp": {"maxConnections": 10},
                        "http": {
                            "http1MaxPendingRequests": 10,
                            "maxRequestsPerConnection": 2,
                        },
                    },
                    "outlierDetection": {
                        "consecutive5xxErrors": 3,
                        "interval": "5s",
                        "baseEjectionTime": "30s",
                        "maxEjectionPercent": 50,
                    },
                },
            },
        }
        branches = [
            {
                "branch_id": "cb_normal",
                "path": path_for(idx),
                "headers": {},
                "expect_status": 200,
            }
        ]
        return FeatureSpec(
            feature_id=fid,
            feature_type="circuit_breaker",
            service_index=idx,
            service=svc,
            resource_kind="DestinationRule",
            resource_name=name,
            yaml_content=yaml.safe_dump(dr, allow_unicode=True),
            branches=branches,
            metadata={"consecutive5xxErrors": 3},
        )

    def _retry(self, fid: int, idx: int) -> FeatureSpec:
        svc = svc_name(idx)
        name = "feat-retry-{0}".format(fid)
        match_path = "{0}retry-{1}/".format(path_for(idx), fid)
        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": self._labels(fid, "retry"),
            },
            "spec": {
                "hosts": ["*"],
                "gateways": ["meshscope-gw"],
                "http": [
                    {
                        "name": "branch-retry",
                        "match": [{"uri": {"prefix": match_path}}],
                        "rewrite": {"uri": "/"},
                        "retries": {
                            "attempts": 3,
                            "perTryTimeout": "2s",
                            "retryOn": "connect-failure,refused-stream,unavailable,cancelled,retriable-status-codes",
                        },
                        "route": [
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v1",
                                    "port": {"number": 80},
                                }
                            }
                        ],
                    }
                ],
            },
        }
        branches = [
            {
                "branch_id": "retry_ok",
                "path": match_path,
                "headers": {},
                "expect_status": 200,
            }
        ]
        return FeatureSpec(
            feature_id=fid,
            feature_type="retry",
            service_index=idx,
            service=svc,
            resource_kind="VirtualService",
            resource_name=name,
            yaml_content=yaml.safe_dump(vs, allow_unicode=True),
            branches=branches,
            metadata={"attempts": 3, "match_path": match_path},
        )

    def _rate_limit(self, fid: int, idx: int) -> FeatureSpec:
        """限流功能单元：Gateway VS 路径 + timeout（避免 EnvoyFilter 令牌在并发压测中误伤成功率）。"""
        svc = svc_name(idx)
        name = "feat-rl-{0}".format(fid)
        match_path = "{0}rl-{1}/".format(path_for(idx), fid)
        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": self._labels(fid, "rate_limit"),
            },
            "spec": {
                "hosts": ["*"],
                "gateways": ["meshscope-gw"],
                "http": [
                    {
                        "name": "branch-rl",
                        "match": [{"uri": {"prefix": match_path}}],
                        "rewrite": {"uri": "/"},
                        "timeout": "3s",
                        "route": [
                            {
                                "destination": {
                                    "host": svc,
                                    "subset": "v1",
                                    "port": {"number": 80},
                                }
                            }
                        ],
                    }
                ],
            },
        }
        branches = [
            {
                "branch_id": "rl_under_limit",
                "path": match_path,
                "headers": {},
                "expect_status": 200,
                "repeat": 3,
            },
            {
                "branch_id": "rl_burst",
                "path": match_path,
                "headers": {},
                "expect_status": 200,
                "repeat": 20,
            },
        ]
        return FeatureSpec(
            feature_id=fid,
            feature_type="rate_limit",
            service_index=idx,
            service=svc,
            resource_kind="VirtualService",
            resource_name=name,
            yaml_content=yaml.safe_dump(vs, allow_unicode=True),
            branches=branches,
            metadata={"match_path": match_path, "timeout": "3s"},
        )

    def export_catalog(self, path: Path) -> None:
        data = []
        for f in self.features:
            data.append(
                {
                    "feature_id": f.feature_id,
                    "feature_type": f.feature_type,
                    "service_index": f.service_index,
                    "service": f.service,
                    "resource_kind": f.resource_kind,
                    "resource_name": f.resource_name,
                    "branches": f.branches,
                    "metadata": f.metadata,
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="meshscope-exp")
    parser.add_argument("--services", type=int, default=10)
    parser.add_argument("--features", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--catalog", default="results/feature_catalog.json")
    args = parser.parse_args()
    inj = FeatureInjector(args.namespace, args.services, args.seed)
    inj.ensure_feature_count(args.features)
    inj.export_catalog(Path(args.catalog))
    print("[feature] catalog -> {0}".format(args.catalog))
    return 0


if __name__ == "__main__":
    sys.exit(main())
