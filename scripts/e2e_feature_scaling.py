#!/usr/bin/env python3
"""
MeshScope 端到端功能阶梯实验脚本
=================================

功能：
- 随机注入路由 / 分流 / 熔断等功能单元到 Kubernetes 集群
- 按 5 → 10 → 15 → 20 的阶梯逐步增加功能数量
- 每次注入后触发 `e2e_validator.py` 运行完整端到端流程
- 收集静态、动态及总耗时，分析动态阶段是否呈线性增长
- 生成实验结果摘要，便于后续分析

使用示例：
    python scripts/e2e_feature_scaling.py \
        --vm-host ${SSH_HOST} \
        --vm-user ${SSH_USER:-root} \
        --vm-password ${SSH_PASSWORD} \
        --namespace default \
        --output-dir results/e2e_feature_scaling
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from consistency_checker.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("e2e_feature_scaling.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("e2e_feature_scaling")

try:
    import paramiko  # type: ignore

    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

PROFILE_CONFIGS: Dict[str, Dict[str, List[str]]] = {
    "bookinfo": {
        "routing_services": ["productpage", "details"],
        "traffic_services": ["reviews"],
        "rate_limit_services": ["productpage", "reviews", "ratings"],
        "circuit_breaker_services": ["ratings", "reviews"],
        "header_key": "end-user",
    },
    "online-boutique": {
        "routing_services": [
            "frontend",
            "productcatalogservice",
            "checkoutservice",
            "cartservice",
        ],
        "traffic_services": ["frontend", "recommendationservice"],
        "rate_limit_services": [
            "frontend",
            "cartservice",
            "checkoutservice",
            "productcatalogservice",
        ],
        "circuit_breaker_services": [
            "checkoutservice",
            "cartservice",
            "recommendationservice",
        ],
        "header_key": "x-meshscope-exp",
    },
}


@dataclass
class FeatureSpec:
    feature_id: int
    feature_type: str
    resource_kind: str
    resource_name: str
    yaml_content: str
    service: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class KubectlExecutor:
    """封装 kubectl 执行逻辑，优先使用本地命令，否则回退到 SSH。"""

    def __init__(self, namespace: str, vm_host: str, vm_user: str, vm_password: str):
        self.namespace = namespace
        self.vm_host = vm_host
        self.vm_user = vm_user
        self.vm_password = vm_password
        self.use_local_kubectl = self._check_local_kubectl()

    def _check_local_kubectl(self) -> bool:
        """检测本地 kubectl 是否可用且可访问目标集群。"""
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False

            result = subprocess.run(
                ["kubectl", "get", "nodes"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("检测到本地 kubectl 可用，将直接使用本地命令。")
                return True
            logger.warning(
                "本地 kubectl 存在但无法访问集群，将尝试使用 SSH 执行命令。"
            )
            return False
        except FileNotFoundError:
            logger.info("本地未找到 kubectl，尝试使用 SSH。")
            return False
        except subprocess.SubprocessError as exc:
            logger.warning(f"检查本地 kubectl 失败，原因：{exc}")
            return False

    def execute(self, command: str, stdin_input: Optional[str] = None) -> str:
        if self.use_local_kubectl:
            return self._execute_local(command, stdin_input)
        return self._execute_remote(command, stdin_input)

    def _execute_local(self, command: str, stdin_input: Optional[str]) -> str:
        cmd_parts = command.split()
        try:
            if stdin_input is not None:
                process = subprocess.Popen(
                    cmd_parts,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = process.communicate(input=stdin_input, timeout=60)
                exit_code = process.returncode
            else:
                result = subprocess.run(
                    cmd_parts,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                stdout, stderr = result.stdout, result.stderr
                exit_code = result.returncode
            if exit_code != 0:
                raise RuntimeError(
                    f"kubectl 执行失败 (exit={exit_code}): {stderr or stdout}"
                )
            return stdout
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"kubectl 命令超时: {command}")

    def _execute_remote(self, command: str, stdin_input: Optional[str]) -> str:
        if not HAS_PARAMIKO:
            raise RuntimeError("未安装 paramiko，无法通过 SSH 执行 kubectl 命令。")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self.vm_host,
                port=22,
                username=self.vm_user,
                password=self.vm_password,
                timeout=10,
            )

            stdin, stdout, stderr = client.exec_command(command, get_pty=False)
            if stdin_input is not None:
                stdin.write(stdin_input)
                stdin.channel.shutdown_write()

            output = stdout.read().decode("utf-8")
            error = stderr.read().decode("utf-8")
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                raise RuntimeError(
                    f"SSH 命令执行失败 (exit={exit_status}): {error or output}"
                )
            return output.strip()
        finally:
            client.close()


class FeatureInjector:
    """负责随机生成并注入功能配置。"""

    def __init__(
        self,
        executor: KubectlExecutor,
        namespace: str,
        profile: str,
        random_seed: Optional[int] = None,
    ):
        self.executor = executor
        self.namespace = namespace
        self.random = random.Random(random_seed)
        self.features: List[FeatureSpec] = []
        self.next_id = 1
        profile = profile.lower()
        if profile not in PROFILE_CONFIGS:
            raise ValueError(f"未知的应用配置: {profile}")
        self.profile = profile
        self.profile_config = PROFILE_CONFIGS[profile]
        self.SUPPORTED_TYPES = ("routing", "traffic_shifting", "rate_limit", "circuit_breaker")
        self.type_weights: Dict[str, float] = {
            "routing": 0.45,
            "traffic_shifting": 0.35,
            "rate_limit": 0.15,
            "circuit_breaker": 0.05,
        }

    def ensure_feature_count(self, target_count: int) -> List[FeatureSpec]:
        """确保集群中已注入的功能数量达到指定目标（逐步增加）。"""
        while len(self.features) < target_count:
            feature = self._create_random_feature()
            self._apply_feature(feature)
            self.features.append(feature)
            logger.info(
                "已注入功能 #%s: %s (%s)",
                feature.feature_id,
                feature.feature_type,
                feature.resource_name,
            )
        return self.features

    def _create_random_feature(self) -> FeatureSpec:
        feature_type = self._choose_feature_type()
        feature_id = self.next_id
        self.next_id += 1

        if feature_type == "routing":
            spec = self._generate_routing_feature(feature_id)
        elif feature_type == "traffic_shifting":
            spec = self._generate_traffic_shifting_feature(feature_id)
        elif feature_type == "rate_limit":
            spec = self._generate_rate_limit_feature(feature_id)
        else:
            spec = self._generate_circuit_breaker_feature(feature_id)
        return spec

    def _choose_feature_type(self) -> str:
        roll = self.random.random()
        cumulative = 0.0
        for feature_type in self.SUPPORTED_TYPES:
            weight = self.type_weights.get(feature_type, 0.0)
            cumulative += weight
            if roll <= cumulative:
                return feature_type
        return "routing"

    def _base_labels(self, feature_id: int, feature_type: str) -> Dict[str, str]:
        return {
            "meshscope/feature-experiment": "e2e-feature-scaling",
            "meshscope/feature-id": str(feature_id),
            "meshscope/feature-type": feature_type,
        }

    def _generate_routing_feature(self, feature_id: int) -> FeatureSpec:
        routing_pool = self.profile_config["routing_services"]
        service = self.random.choice(routing_pool)
        resource_name = f"feature-routing-{feature_id}"
        labels = self._base_labels(feature_id, "routing")
        match_prefix = f"/feature-{self.profile}-routing-{feature_id}"

        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": resource_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "hosts": [service],
                "http": [
                    {
                        "match": [{"uri": {"prefix": match_prefix}}],
                        "route": [
                            {
                                "destination": {"host": service},
                                "weight": 100,
                            }
                        ],
                    }
                ],
            },
        }
        yaml_content = yaml.safe_dump(vs, sort_keys=False, allow_unicode=True)

        return FeatureSpec(
            feature_id=feature_id,
            feature_type="routing",
            resource_kind="VirtualService",
            resource_name=resource_name,
            yaml_content=yaml_content,
            service=service,
            metadata={"match_prefix": match_prefix},
        )

    def _generate_traffic_shifting_feature(self, feature_id: int) -> FeatureSpec:
        service = self.random.choice(self.profile_config["traffic_services"])
        resource_name = f"feature-traffic-{feature_id}"
        labels = self._base_labels(feature_id, "traffic_shifting")

        weight_primary = self.random.randint(40, 80)
        weight_secondary = 100 - weight_primary
        header_key = self.profile_config.get("header_key", "x-meshscope-exp")
        header_value = f"{self.profile[:3]}-exp-{feature_id}"

        vs = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {
                "name": resource_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "hosts": [service],
                "http": [
                    {
                        "match": [
                            {"headers": {header_key: {"exact": header_value}}}
                        ],
                        "route": [
                            {
                                "destination": {"host": service},
                                "weight": weight_primary,
                            },
                            {
                                "destination": {"host": service},
                                "weight": weight_secondary,
                            },
                        ],
                    }
                ],
            },
        }
        yaml_content = yaml.safe_dump(vs, sort_keys=False, allow_unicode=True)

        return FeatureSpec(
            feature_id=feature_id,
            feature_type="traffic_shifting",
            resource_kind="VirtualService",
            resource_name=resource_name,
            yaml_content=yaml_content,
            service=service,
            metadata={
                "header": header_key,
                "header_value": header_value,
                "weights": [weight_primary, weight_secondary],
            },
        )

    def _generate_rate_limit_feature(self, feature_id: int) -> FeatureSpec:
        service = self.random.choice(self.profile_config["rate_limit_services"])
        resource_name = f"feature-rl-{feature_id}"
        labels = self._base_labels(feature_id, "rate_limit")

        max_tokens = self.random.randint(10, 30)
        fill_interval = f"{self.random.randint(1, 5)}s"
        tokens_per_fill = self.random.randint(max(1, max_tokens // 5), max_tokens)
        stat_prefix = f"http_rl_{service}_{feature_id}"

        envoy_filter = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "EnvoyFilter",
            "metadata": {
                "name": resource_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "workloadSelector": {
                    "labels": {
                        "app": service
                    }
                },
                "configPatches": [
                    {
                        "applyTo": "HTTP_FILTER",
                        "match": {
                            "context": "SIDECAR_INBOUND",
                            "listener": {
                                "filterChain": {
                                    "filter": {
                                        "name": "envoy.filters.network.http_connection_manager",
                                        "subFilter": {
                                            "name": "envoy.filters.http.router"
                                        },
                                    }
                                }
                            },
                        },
                        "patch": {
                            "operation": "INSERT_BEFORE",
                            "value": {
                                "name": "envoy.filters.http.local_ratelimit",
                                "typed_config": {
                                    "@type": "type.googleapis.com/envoy.extensions.filters.http.local_ratelimit.v3.LocalRateLimit",
                                    "stat_prefix": stat_prefix,
                                    "token_bucket": {
                                        "max_tokens": max_tokens,
                                        "tokens_per_fill": tokens_per_fill,
                                        "fill_interval": fill_interval,
                                    },
                                    "filter_enabled": {
                                        "runtime_key": "local_rate_limit_enabled",
                                        "default_value": {
                                            "numerator": 100,
                                            "denominator": "HUNDRED",
                                        },
                                    },
                                    "filter_enforced": {
                                        "runtime_key": "local_rate_limit_enforced",
                                        "default_value": {
                                            "numerator": 100,
                                            "denominator": "HUNDRED",
                                        },
                                    },
                                    "response_headers_to_add": [
                                        {
                                            "header": {
                                                "key": "x-meshscope-rate-limit",
                                                "value": str(max_tokens),
                                            }
                                        }
                                    ],
                                },
                            },
                        },
                    }
                ],
            },
        }
        yaml_content = yaml.safe_dump(envoy_filter, sort_keys=False, allow_unicode=True)

        return FeatureSpec(
            feature_id=feature_id,
            feature_type="rate_limit",
            resource_kind="EnvoyFilter",
            resource_name=resource_name,
            yaml_content=yaml_content,
            service=service,
            metadata={
                "max_tokens": max_tokens,
                "tokens_per_fill": tokens_per_fill,
                "fill_interval": fill_interval,
            },
        )

    def _generate_circuit_breaker_feature(self, feature_id: int) -> FeatureSpec:
        service = self.random.choice(self.profile_config["circuit_breaker_services"])
        resource_name = f"feature-cb-{feature_id}"
        labels = self._base_labels(feature_id, "circuit_breaker")

        max_connections = self.random.randint(1, 5)
        max_pending = self.random.randint(1, 10)
        interval = f"{self.random.randint(1, 5)}s"
        base_ejection = f"{self.random.randint(5, 15)}s"

        dr = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "DestinationRule",
            "metadata": {
                "name": resource_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "host": service,
                "trafficPolicy": {
                    "connectionPool": {
                        "http": {
                            "http1MaxPendingRequests": max_pending,
                            "maxRequestsPerConnection": 1,
                        }
                    },
                    "outlierDetection": {
                        "consecutive5xxErrors": 3,
                        "interval": interval,
                        "baseEjectionTime": base_ejection,
                        "maxEjectionPercent": 50,
                    },
                },
            },
        }
        yaml_content = yaml.safe_dump(dr, sort_keys=False, allow_unicode=True)

        return FeatureSpec(
            feature_id=feature_id,
            feature_type="circuit_breaker",
            resource_kind="DestinationRule",
            resource_name=resource_name,
            yaml_content=yaml_content,
            service=service,
            metadata={
                "max_pending": max_pending,
                "interval": interval,
                "base_ejection_time": base_ejection,
            },
        )

    def _apply_feature(self, feature: FeatureSpec) -> None:
        command = f"kubectl apply -n {self.namespace} -f -"
        logger.debug("应用功能配置: %s", feature.resource_name)
        self.executor.execute(command, stdin_input=feature.yaml_content)


class E2EFeatureScalingRunner:
    """组织功能注入与端到端测试的高层调度器。"""

    def __init__(
        self,
        namespace: str,
        vm_host: str,
        vm_user: str,
        vm_password: str,
        output_dir: Path,
        app_profile: str,
        random_seed: Optional[int] = None,
    ):
        self.namespace = namespace
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.executor = KubectlExecutor(namespace, vm_host, vm_user, vm_password)
        self.injector = FeatureInjector(
            self.executor,
            namespace=namespace,
            profile=app_profile,
            random_seed=random_seed,
        )

        self.e2e_output_dir = Path("results") / "e2e_validation"
        self.e2e_output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, steps: List[int]) -> Dict[str, Any]:
        logger.info("开始执行功能阶梯实验：%s", steps)
        experiment_start = datetime.now()

        summary_records: List[Dict[str, Any]] = []
        detailed_features: List[Dict[str, Any]] = []

        for target in steps:
            logger.info("\n===== 阶梯目标：%s 个功能 =====", target)
            features = self.injector.ensure_feature_count(target)

            detailed_features = [self._feature_to_dict(f) for f in features]

            e2e_result = self._run_e2e_validator()
            summary_records.append(
                {
                    "target_features": target,
                    "static_duration": e2e_result.get("static_pipeline_duration"),
                    "dynamic_duration": e2e_result.get("dynamic_pipeline_duration"),
                    "total_duration": e2e_result.get("total_duration"),
                    "success": e2e_result.get("success"),
                    "timestamp": e2e_result.get("timestamp"),
                    "result_file": e2e_result.get("result_file"),
                }
            )

        analysis = self._analyze_trend(summary_records)

        experiment_result = {
            "experiment_start": experiment_start.isoformat(),
            "experiment_end": datetime.now().isoformat(),
            "namespace": self.namespace,
            "steps": steps,
            "records": summary_records,
            "analysis": analysis,
            "features": detailed_features,
        }

        result_path = self._save_summary(experiment_result)
        logger.info("实验结果已保存到：%s", result_path)
        return experiment_result

    def cleanup(self) -> None:
        label_selector = "meshscope/feature-experiment=e2e-feature-scaling"
        for resource in ("virtualservice", "destinationrule", "envoyfilter"):
            command = (
                f"kubectl delete {resource} -n {self.namespace} -l {label_selector}"
            )
            try:
                output = self.executor.execute(command)
                logger.info("已清理 %s:\n%s", resource, output)
            except RuntimeError as exc:
                logger.warning("清理 %s 失败：%s", resource, exc)

    def _feature_to_dict(self, feature: FeatureSpec) -> Dict[str, Any]:
        return {
            "feature_id": feature.feature_id,
            "type": feature.feature_type,
            "resource_kind": feature.resource_kind,
            "resource_name": feature.resource_name,
            "service": feature.service,
            "metadata": feature.metadata,
        }

    def _run_e2e_validator(self) -> Dict[str, Any]:
        logger.info("启动端到端验证流程...")
        cmd = [
            sys.executable,
            str(project_root / "e2e_validator.py"),
            "--namespace",
            self.namespace,
        ]

        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONLEGACYWINDOWSSTDIO", "utf-8")

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
        )

        if process.returncode != 0:
            logger.error("e2e_validator 执行失败：%s", process.stderr)
            raise RuntimeError("e2e_validator 执行失败")

        logger.info("端到端验证完成，解析最新结果...")
        return self._parse_latest_e2e_result()

    def _parse_latest_e2e_result(self) -> Dict[str, Any]:
        result_files = sorted(
            self.e2e_output_dir.glob("e2e_result_*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if not result_files:
            raise FileNotFoundError("未找到任何 e2e_result_* 文件，请确认验证流程是否成功。")

        latest_file = result_files[-1]
        with latest_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        data["result_file"] = str(latest_file)
        return data

    def _analyze_trend(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        dynamic_durations = [
            record["dynamic_duration"] for record in records if record["success"]
        ]
        trend = "unknown"
        details: Dict[str, Any] = {}

        if len(dynamic_durations) >= 3:
            diffs = [
                dynamic_durations[i + 1] - dynamic_durations[i]
                for i in range(len(dynamic_durations) - 1)
            ]
            avg_diff = sum(diffs) / len(diffs)
            variance = (
                sum((diff - avg_diff) ** 2 for diff in diffs) / len(diffs)
                if diffs
                else 0.0
            )

            if avg_diff == 0:
                trend = "flat"
            else:
                relative_std = (variance ** 0.5) / abs(avg_diff)
                trend = "linear" if relative_std <= 0.3 else "non_linear"

            details = {
                "dynamic_durations": dynamic_durations,
                "diffs": diffs,
                "avg_diff": avg_diff,
                "std_dev": variance ** 0.5,
                "relative_std": relative_std,
            }
        else:
            details = {"dynamic_durations": dynamic_durations}

        return {"trend": trend, "details": details}

    def _save_summary(self, data: Dict[str, Any]) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"feature_scaling_summary_{timestamp}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return output_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按功能阶梯执行端到端验证，并分析动态阶段耗时趋势。",
    )
    global_config = get_config()
    default_host = os.getenv("SSH_HOST") or global_config.ssh_host
    parser.add_argument(
        "--vm-host",
        type=str,
        default=default_host,
        help="SSH 主机地址（当本机无法访问 Kubernetes 时使用）。",
    )
    default_user = os.getenv("SSH_USER") or global_config.ssh_user
    default_password = os.getenv("SSH_PASSWORD") or global_config.ssh_password
    
    parser.add_argument(
        "--vm-user",
        type=str,
        default=default_user,
        help="SSH 用户名。",
    )
    parser.add_argument(
        "--vm-password",
        type=str,
        default=default_password,
        help="SSH 密码。",
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="default",
        help="目标命名空间。",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results/e2e_feature_scaling",
        help="实验结果输出目录。",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default="5,10,15,20",
        help="功能阶梯配置，逗号分隔，例如 5,10,15,20。",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help="随机种子，便于复现实验结果。",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="仅清理实验注入的资源，不执行端到端测试。",
    )
    parser.add_argument(
        "--app-profile",
        type=str,
        default="bookinfo",
        choices=list(PROFILE_CONFIGS.keys()),
        help="目标应用配置（bookinfo 或 online-boutique）。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    steps = [int(value.strip()) for value in args.steps.split(",") if value.strip()]

    runner = E2EFeatureScalingRunner(
        namespace=args.namespace,
        vm_host=args.vm_host,
        vm_user=args.vm_user,
        vm_password=args.vm_password,
        output_dir=Path(args.output_dir),
        app_profile=args.app_profile,
        random_seed=args.random_seed,
    )
    if args.cleanup_only:
        runner.cleanup()
        return

    runner.run(steps)


if __name__ == "__main__":
    main()

