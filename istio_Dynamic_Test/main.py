#!/usr/bin/env python3
"""
DynamicTester —— Istio 动态验证统一流水线入口。

四层流水线架构::

    ┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌───────────┐
    │  Generator   │ ──▶ │ Executor │ ──▶ │ Collector │ ──▶ │ Validator │
    └─────────────┘     └──────────┘     └───────────┘     └───────────┘
         TestCase      ExecutionResult   CollectionResult  ValidationResult

使用方式::

    # 方式 1: 编程调用
    tester = DynamicTester(
        generator=ConfigGenerator("istio_config.json", ingress_url="http://..."),
        executor=HttpExecutor(ssh_client),
        collector=EnvoyCollector(ssh_client),
        validator=CompositeValidator(),
    )
    results = tester.run()

    # 方式 2: CLI
    python -m istio_Dynamic_Test.main -i istio_config.json --ingress-url http://...

    # 方式 3: 从旧版矩阵文件加载
    python -m istio_Dynamic_Test.main --matrix output_matrix.json
"""

from __future__ import annotations

import argparse
import atexit
import io
import json
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

def _ensure_utf8_stdio():
    """Windows 控制台 UTF-8 兼容（仅在尚未设置时执行）。"""
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream and hasattr(stream, "buffer") and getattr(stream, "encoding", "").lower() != "utf-8":
            try:
                setattr(sys, attr, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass

_ensure_utf8_stdio()

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from istio_Dynamic_Test.models.test_case import (
    ExecutionResult,
    PipelineResult,
    TestCase,
    TestSuite,
    TestType,
)
from istio_Dynamic_Test.generators.base import BaseGenerator
from istio_Dynamic_Test.models.test_case import PolicyType
from istio_Dynamic_Test.executors.base import BaseExecutor
from istio_Dynamic_Test.executors.http_executor import HttpExecutor
from istio_Dynamic_Test.executors.load_executor import LoadExecutor
from istio_Dynamic_Test.executors.mesh_executor import MeshExecutor
from istio_Dynamic_Test.executors.fault_injector import FaultInjector
from istio_Dynamic_Test.collectors.base import BaseCollector
from istio_Dynamic_Test.validators.base import BaseValidator
from istio_Dynamic_Test.validators.composite_validator import CompositeValidator
from istio_Dynamic_Test.validators.report_generator import ReportGenerator
from istio_Dynamic_Test.utils.ssh_utils import SSHClient


class DynamicTester:
    """
    统一流水线入口：Generator → Executor → Collector → Validator。

    对于不同的 TestType 自动选择合适的 Executor：
    - SINGLE_REQUEST → HttpExecutor
    - LOAD_TEST → LoadExecutor

    对于不同的 PolicyType 自动选择合适的 Validator：
    - 由 CompositeValidator 内部分发

    Args:
        generator: 测试用例生成器（可选，也可直接传入 TestSuite）。
        executor: 自定义执行器（可选，默认按 TestType 自动选择）。
        collector: 数据采集器（可选）。
        validator: 验证器（可选，默认 CompositeValidator）。
        ssh_config: SSH 配置字典。
        namespace: K8s 命名空间。
    """

    def __init__(
        self,
        generator: Optional[BaseGenerator] = None,
        executor: Optional[BaseExecutor] = None,
        collector: Optional[BaseCollector] = None,
        validator: Optional[BaseValidator] = None,
        ssh_config: Optional[dict] = None,
        namespace: str = "default",
    ):
        self._generator = generator
        self._custom_executor = executor
        self._collector = collector
        self._validator = validator or CompositeValidator()
        self._namespace = namespace

        # SSH 客户端
        self._ssh = SSHClient(**(ssh_config or {}))

        # 按 TestType / PolicyType 的默认执行器
        self._http_executor = HttpExecutor(self._ssh)
        self._load_executor = LoadExecutor(self._ssh)
        self._mesh_executor = MeshExecutor(self._ssh, namespace=namespace)

        # 故障注入器缓存
        self._fault_injectors: dict[str, FaultInjector] = {}

        # 报告生成器
        self._reporter = ReportGenerator()

    # ── 核心流水线 ────────────────────────────────────────────────────────

    def run(self, suite: Optional[TestSuite] = None) -> List[PipelineResult]:
        """
        运行完整流水线。

        Args:
            suite: 测试套件。如果为 None，则使用 generator 生成。

        Returns:
            每个用例的完整流水线结果列表。
        """
        if suite is None and self._generator:
            suite = self._generator.generate_suite()
        if suite is None or not suite.cases:
            print("[ERROR] 没有测试用例可执行。")
            return []

        total = len(suite.cases)
        print(f"\n{'=' * 60}")
        print(f"  Istio 动态验证流水线")
        print(f"  用例数量: {total}")
        print(f"  入口URL: {suite.ingress_url}")
        print(f"{'=' * 60}\n")

        # 预热 Collector（启用 access log）
        if self._collector and hasattr(self._collector, "warmup_for_suite"):
            self._collector.warmup_for_suite(suite.cases)

        results: List[PipelineResult] = []
        start_time = time.time()

        for i, tc in enumerate(suite.cases, 1):
            print(f"\n[{i}/{total}] {tc.case_id}: {tc.description}")
            print(f"  策略: {[p.value for p in tc.policy_types]}")
            result = self._run_single(tc)
            results.append(result)

            # 打印即时状态
            if result.validation:
                status = result.validation.overall_status.value.upper()
                print(f"  => {status}: {result.validation.summary}")

        elapsed = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"  流水线完成  耗时: {elapsed:.1f}s")
        self._print_summary(results)
        print(f"{'=' * 60}")

        # 生成报告
        self._reporter.generate(results)

        # 故障恢复：确保所有注入的故障已清理
        self._clear_all_faults()

        # 清理
        self._ssh.close()

        return results

    def run_single(self, test_case: TestCase) -> PipelineResult:
        """运行单个测试用例的完整流水线。"""
        return self._run_single(test_case)

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _run_single(self, tc: TestCase) -> PipelineResult:
        injector = None
        execution = None
        collection = None
        validation = None

        try:
            # Phase 1: 故障注入（如果需要）
            injector = self._inject_fault(tc)

            # Phase 1.5: 记录执行前各 Pod 的日志行数（用于后续只采集新增部分）
            pre_log_lines = {}
            if self._collector and hasattr(self._collector, 'snapshot_log_lines'):
                pre_log_lines = self._collector.snapshot_log_lines(tc)

            # Phase 2: 执行
            executor = self._select_executor(tc)
            execution = executor.execute(tc)
            self._save_http_result(tc.case_id, execution)

            # Phase 3: 数据采集（只采集执行期间新增的日志）
            if self._collector:
                # 流量分割需更多时间让 sidecar 日志落盘
                wait = 2 if PolicyType.TRAFFIC_SPLIT in tc.policy_types else 1
                time.sleep(wait)
                collection = self._collector.collect(tc, pre_snapshot=pre_log_lines)

            # Phase 4: 验证
            validation = self._validator.validate(tc, execution, collection)

        except Exception as e:
            print(f"  [ERROR] {tc.case_id}: {e}")
        finally:
            # 故障恢复：每个用例执行后立即恢复
            if injector:
                print(f"  [CLEANUP] 清理故障注入")
                injector.clear_faults()

        return PipelineResult(
            test_case=tc,
            execution=execution,
            collection=collection,
            validation=validation,
        )

    def _select_executor(self, tc: TestCase) -> BaseExecutor:
        if self._custom_executor:
            return self._custom_executor
        # 流量分割需要从 mesh 内部发起请求，才能触发内部 VirtualService 路由规则
        if PolicyType.TRAFFIC_SPLIT in tc.policy_types:
            return self._mesh_executor
        if tc.test_type == TestType.LOAD_TEST:
            return self._load_executor
        return self._http_executor

    def _inject_fault(self, tc: TestCase) -> Optional[FaultInjector]:
        trigger = tc.trigger_condition
        if not trigger:
            return None

        svc = tc.host or tc.source_service
        key = f"{svc}_{svc}"
        if key not in self._fault_injectors:
            self._fault_injectors[key] = FaultInjector(
                self._ssh, vs_name=svc, route_host=svc, namespace=self._namespace,
            )
        injector = self._fault_injectors[key]
        params = tc.fault_params

        if trigger == "simulate_503_error":
            injector.inject_http_fault(error_code=503)
        elif trigger == "simulate_config_fault":
            ft = params.get("fault_type", "abort")
            if ft == "abort":
                injector.inject_config_fault(
                    fault_type="abort",
                    status_code=params.get("fault_status", 503),
                    percentage=params.get("fault_percentage", 100),
                )
            elif ft == "delay":
                injector.inject_config_fault(
                    fault_type="delay",
                    delay=params.get("fault_delay", "1s"),
                    percentage=params.get("fault_percentage", 100),
                )
        elif trigger == "simulate_high_load_with_errors":
            injector.inject_upstream_error_scenario(error_percentage=80)
        elif trigger == "simulate_config_fault_with_timeout":
            injector.inject_fault_with_timeout(
                status_code=params.get("fault_status", 503),
                percentage=params.get("fault_percentage", 100),
                timeout=params.get("timeout_limit", "2s"),
            )

        return injector

    def _clear_all_faults(self):
        """确保所有故障注入器已恢复，避免遗留故障配置。"""
        for key, injector in self._fault_injectors.items():
            if injector._injected or injector._created:
                print(f"  [CLEANUP] 清理遗留故障: {key}")
                injector.clear_faults()

    @staticmethod
    def _save_http_result(case_id: str, result: ExecutionResult):
        results_dir = "results/http_results"
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(results_dir, f"{case_id}_http_result_{ts}.json")
        data = {
            "case_id": case_id,
            "timestamp": ts,
            "http_result": {
                "status_codes": result.status_codes,
                "total_requests": result.total_requests,
                "success_rate": result.success_rate,
                "avg_response_time": result.avg_response_time,
                "error_count": result.error_count,
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _print_summary(results: List[PipelineResult]):
        passed = sum(1 for r in results if r.validation and r.validation.passed)
        total = len(results)
        failed = total - passed
        rate = passed / total * 100 if total else 0
        print(f"  通过: {passed}  失败: {failed}  通过率: {rate:.1f}%")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Istio 动态验证流水线")
    parser.add_argument("-i", "--input", help="Istio 配置文件路径")
    parser.add_argument("--matrix", help="旧版测试矩阵文件路径 (output_matrix.json)")
    parser.add_argument("--ingress-url", default="", help="集群入口 URL")
    parser.add_argument("--service-deps", help="服务依赖 JSON 路径")
    parser.add_argument("--namespace", default="default", help="K8s 命名空间")
    parser.add_argument(
        "--control-plane-config",
        default="istio_config_parser/istio_monitor/istio_control_config",
        help="控制面配置目录，动态验证前会从此目录同步最新 VS/DR 到 istio_config（默认: istio_config_parser/istio_monitor/istio_control_config）",
    )
    parser.add_argument("--ssh-host", help="SSH 主机")
    parser.add_argument("--ssh-user", help="SSH 用户名")
    parser.add_argument("--ssh-password", help="SSH 密码")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH 端口")
    parser.add_argument("--single-case", help="只运行指定用例 (如 case_005)")
    args = parser.parse_args()

    # SSH 配置
    ssh_config = {}
    if args.ssh_host:
        ssh_config = {
            "hostname": args.ssh_host,
            "username": args.ssh_user,
            "password": args.ssh_password,
            "port": args.ssh_port,
        }

    # 构建流水线
    generator = None
    suite = None

    if args.matrix:
        suite = TestSuite.from_matrix_file(args.matrix)
    elif args.input:
        from istio_Dynamic_Test.generators.config_generator import ConfigGenerator
        generator = ConfigGenerator(
            args.input,
            service_deps_path=args.service_deps,
            ingress_url=args.ingress_url,
            namespace=args.namespace,
            control_plane_config_path=args.control_plane_config,
        )

    ssh = SSHClient(**(ssh_config or {}))

    from istio_Dynamic_Test.collectors.envoy_log_collector import EnvoyCollector
    collector = EnvoyCollector(ssh_client=ssh, namespace=args.namespace)

    tester = DynamicTester(
        generator=generator,
        collector=collector,
        ssh_config=ssh_config,
        namespace=args.namespace,
    )
    # 进程退出时（含 Ctrl+C）确保故障恢复
    atexit.register(tester._clear_all_faults)

    if args.single_case and suite:
        tc = next((c for c in suite.cases if c.case_id == args.single_case), None)
        if tc:
            tester.run_single(tc)
        else:
            print(f"[ERROR] 未找到用例: {args.single_case}")
    else:
        tester.run(suite)


if __name__ == "__main__":
    main()
