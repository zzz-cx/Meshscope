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
    python -m istio_Dynamic_Test.cmd -i configs/istio_config.json --ingress-url http://...

    # 方式 3: 从旧版矩阵文件加载
    python -m istio_Dynamic_Test.cmd --matrix configs/output_matrix.json
"""

import argparse
import atexit
import io
import json
import os
import sys
import time
from typing import Dict, List, Optional

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

# 在部分 Linux (ASCII locale) 下，print 中文会触发 UnicodeEncodeError；
# 这里兜底设置，保证流水线输出不影响实际执行。
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from istio_Dynamic_Test.internal.models.testcase import (
    ExecutionResult,
    PipelineResult,
    TestCase,
    TestSuite,
    TestType,
    requires_controlled_stimulus,
    ValidationDetail,
    ValidationResult,
    ValidationStatus,
)
from istio_Dynamic_Test.internal.testcase.generators.base import BaseGenerator
from istio_Dynamic_Test.internal.models.testcase import PolicyType
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor
from istio_Dynamic_Test.internal.traffic.registry import ExecutorRegistry
from istio_Dynamic_Test.internal.traffic.executors.connection_pool_outlier import ConnectionPoolOutlierExecutor
from istio_Dynamic_Test.internal.traffic.fault.injector import FaultInjector
from istio_Dynamic_Test.internal.traffic.protocols.http.result_store import save_execution_result
from istio_Dynamic_Test.pkg.k8s.meshscope_naming import resolve_meshscope_svc
from istio_Dynamic_Test.internal.pipeline.scheduling.locks import (
    LockManager, tag_case_locks, plan_case_resources, mutation_trigger,
    run_safely_in_parallel,
)
from istio_Dynamic_Test.internal.pipeline.scheduling.queue import ObservationWait
from istio_Dynamic_Test.internal.pipeline.scheduling.orthogonal_fault_bundle import (
    apply_orthogonal_fault_bundling,
    flatten_cases_for_warmup,
    orthogonal_fault_bundle_enabled,
    subcase_to_inject_item,
)
from istio_Dynamic_Test.internal.telemetry.collectors.base import BaseCollector
from istio_Dynamic_Test.internal.validation import BaseValidator
from istio_Dynamic_Test.internal.validation.composite import CompositeValidator
from istio_Dynamic_Test.internal.validation.report import ReportGenerator
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient
from istio_Dynamic_Test.pkg.k8s.ingress_shard import synth_ingress_vs_name_for_case
from istio_Dynamic_Test.internal.pipeline.guards import (
    DynamicSafetyOptions,
    banner_text,
    case_block_reasons,
    options_from_config,
)


def _post_http_collect_sleep_seconds(
    tc: TestCase,
    *,
    has_pre_prometheus: bool,
    prom_url: Optional[str],
    body_usable: bool = False,
) -> float:
    """采集前等待秒数：body 能观察分流时不等 Prometheus 抓取。"""
    try:
        scale = float(os.getenv("DYNAMIC_TEST_SLEEP_SCALE", "1") or "1")
    except ValueError:
        scale = 1.0
    if PolicyType.TRAFFIC_SPLIT in (tc.policy_types or []):
        if body_usable:
            key = "DYNAMIC_TEST_SLEEP_TRAFFIC_SPLIT_BODY_S"
            default = "0"
        elif has_pre_prometheus or prom_url:
            key = "DYNAMIC_TEST_SLEEP_TRAFFIC_SPLIT_PROM_S"
            default = "12"
        else:
            key = "DYNAMIC_TEST_SLEEP_TRAFFIC_SPLIT_NO_PROM_S"
            default = "0"
    elif PolicyType.RATE_LIMIT in (tc.policy_types or []) and prom_url:
        key = "DYNAMIC_TEST_SLEEP_RATE_LIMIT_PROM_S"
        default = "10"
    elif PolicyType.RATE_LIMIT in (tc.policy_types or []):
        key = "DYNAMIC_TEST_SLEEP_RATE_LIMIT_NO_PROM_S"
        default = "3"
    else:
        key = "DYNAMIC_TEST_SLEEP_DEFAULT_S"
        default = "1"
    try:
        base = float(os.getenv(key, default) or default)
    except ValueError:
        base = float(default)
    return max(0.0, base * scale)


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
        prometheus_url: Optional[str] = None,
        ingress_url: Optional[str] = None,
        jaeger_url: Optional[str] = None,
        zipkin_url: Optional[str] = None,
        safety: Optional[DynamicSafetyOptions] = None,
    ):
        self._generator = generator
        self._prometheus_url = prometheus_url
        self._jaeger_url = jaeger_url
        self._safety = safety or options_from_config()
        self._validator = (
            validator
            or CompositeValidator(
                prometheus_url=prometheus_url,
                ingress_url=ingress_url,
                namespace=namespace,
            )
        )
        self._namespace = namespace

        # SSH 客户端
        self._ssh = SSHClient(**(ssh_config or {}))

        if collector is None:
            from istio_Dynamic_Test.internal.telemetry.collectors.composite import CompositeCollector
            collector = CompositeCollector(
                prometheus_url=prometheus_url,
                namespace=namespace,
                ssh_client=self._ssh,
                jaeger_url=jaeger_url,
                zipkin_url=zipkin_url,
            )
        self._collector = collector

        self._executor_registry = ExecutorRegistry(
            self._ssh, namespace=namespace, custom=executor, ingress_url=ingress_url
        )
        self._cp_outlier_executor = ConnectionPoolOutlierExecutor(self._ssh, namespace=namespace)

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

        _raw_case_count = len(suite.cases)
        suite = apply_orthogonal_fault_bundling(suite, self._ssh, self._namespace)
        if orthogonal_fault_bundle_enabled() and len(suite.cases) != _raw_case_count:
            print(
                "  [BUNDLE] 正交故障打包: 调度行数 {0}（展开子用例数仍为 {1}）".format(
                    len(suite.cases), _raw_case_count
                )
            )

        total = len(suite.cases)
        print(f"\n{'=' * 60}")
        print(f"  Istio 动态验证流水线")
        print(f"  用例数量: {total}")
        print(f"  入口URL: {suite.ingress_url}")
        print(banner_text(self._safety))
        print(f"{'=' * 60}\n")

        # Only explicitly allowed rollout may warm up access logs.
        if self._safety.allow_rollout and self._collector and hasattr(self._collector, "warmup_for_suite"):
            warmup = [tc for tc in flatten_cases_for_warmup(suite.cases)
                      if not requires_controlled_stimulus(tc)]
            if warmup:
                self._collector.warmup_for_suite(warmup)
        elif not self._safety.allow_rollout:
            print("  [GUARD] rollout disabled; skipping access-log warmup")

        results: List[PipelineResult] = []
        start_time = time.time()

        # 安全并行开关：默认 1（关闭）
        # 设置环境变量 `DYNAMIC_TEST_MAX_WORKERS=4` 启用并行。
        try:
            max_workers = int(os.getenv("DYNAMIC_TEST_MAX_WORKERS", "1"))
        except Exception:
            max_workers = 1
        if max_workers < 1:
            max_workers = 1
        self._prepare_resource_plans(suite.cases)
        self.scheduler_stats = {}
        event_wait = max_workers > 1 and os.getenv("DYNAMIC_TEST_EVENT_WAIT", "1").lower() not in ("0", "false", "off")
        try:
            inflight = max(max_workers, int(os.getenv("DYNAMIC_TEST_MAX_INFLIGHT", str(max_workers * 4))))
        except ValueError:
            inflight = max_workers * 4
        print(f"  [SCHED] workers={max_workers}, event_wait={event_wait}, max_inflight={inflight}")
        try:
            batches = run_safely_in_parallel(
                cases=suite.cases,
                run_case=self._run_case_steps if event_wait else self._run_case_results,
                max_workers=max_workers,
                max_inflight=inflight,
                lock_manager=LockManager(),
                tagger=lambda case: tag_case_locks(case, self._namespace),
                stats=self.scheduler_stats,
            )
            for batch in batches:
                results.extend(batch)
        finally:
            self._clear_all_faults()
            self._ssh.close()
        print(f"  [SCHED] {json.dumps(self.scheduler_stats, ensure_ascii=False)}")
        elapsed = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"  流水线完成  耗时: {elapsed:.1f}s")
        self._print_summary(results)
        print(f"{'=' * 60}")

        # 生成报告
        self._reporter.generate(results)

        return results

    def _prepare_resource_plans(self, cases):
        inventory = None
        try:
            out, err = self._ssh.run_command(
                "kubectl get virtualservices.networking.istio.io --all-namespaces -o json"
            )
            inventory = json.loads(out)["items"]
        except Exception as exc:
            print(f"  [SCHED] resource discovery unavailable; conservative exclusion: {exc}")
        for case in cases:
            plan_case_resources(case, self._namespace, inventory)
        # Opt-in correlation only. Standard Prometheus counters do not expose
        # this header as a label, so it must never remove observation locks.
        if os.getenv("DYNAMIC_TEST_TRACE_HEADER", "0").lower() in ("1", "true", "on"):
            import uuid
            run_id = uuid.uuid4().hex
            for index, case in enumerate(flatten_cases_for_warmup(cases)):
                case.headers = dict(case.headers or {})
                if not any(k.lower() == "x-configpilot-case-id" for k in case.headers):
                    case.headers["x-configpilot-case-id"] = f"{run_id}-{index}"

    def _run_case_steps(self, tc):
        reasons = self._block_reasons_for_row(tc)
        if reasons:
            return self._skip_row(tc, reasons)
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            return (yield from self._run_orthogonal_fault_bundle_steps(tc.metadata.get("bundle_subcases") or []))
        result = yield from self._run_single_steps(tc)
        return [result]

    def run_single(self, test_case: TestCase) -> PipelineResult:
        """运行单个测试用例的完整流水线。"""
        reasons = [] if requires_controlled_stimulus(test_case) else case_block_reasons(test_case, self._safety)
        if reasons:
            print(f"\n[1/1] {test_case.case_id}: {test_case.description}")
            return self._skip_result(test_case, reasons)
        return self._run_single(test_case)

    def _block_reasons_for_row(self, tc: TestCase) -> List[str]:
        # These legacy cases are retained as INCONCLUSIVE by the controlled
        # stimulus gate; they never reach traffic or configuration mutation.
        if requires_controlled_stimulus(tc) or any(
                requires_controlled_stimulus(sub) for sub in tc.metadata.get("bundle_subcases", [])):
            return []
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            reasons: List[str] = []
            for sub in tc.metadata.get("bundle_subcases") or []:
                reasons.extend(case_block_reasons(sub, self._safety))
            seen = set()
            uniq = []
            for item in reasons:
                if item not in seen:
                    seen.add(item)
                    uniq.append(item)
            return uniq
        return case_block_reasons(tc, self._safety)

    def _skip_result(self, tc: TestCase, reasons: List[str]) -> PipelineResult:
        msg = "；".join(reasons) or "安全开关未打开，跳过动态验证"
        print(f"  [SKIP] {msg}")
        return PipelineResult(
            test_case=tc,
            execution=None,
            collection=None,
            validation=ValidationResult(
                case_id=tc.case_id,
                overall_status=ValidationStatus.SKIPPED,
                details=[
                    ValidationDetail(
                        dimension="safety_guard",
                        status=ValidationStatus.SKIPPED,
                        message=msg,
                    )
                ],
                summary=msg,
            ),
            case_duration_seconds=0.0,
        )

    def _skip_row(self, tc: TestCase, reasons: List[str]) -> List[PipelineResult]:
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            subs = tc.metadata.get("bundle_subcases") or []
            if subs:
                return [self._skip_result(sub, reasons) for sub in subs]
        return [self._skip_result(tc, reasons)]

    def _run_case_results(self, tc: TestCase) -> List[PipelineResult]:
        """单调度行对应的流水线结果（bundle 会展开为多份子用例结果）。"""
        skip_reasons = self._block_reasons_for_row(tc)
        if skip_reasons:
            return self._skip_row(tc, skip_reasons)
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            subs = tc.metadata.get("bundle_subcases") or []
            return self._run_orthogonal_fault_bundle(subs)
        return [self._run_single(tc)]

    def _run_orthogonal_fault_bundle(self, subcases: List[TestCase]) -> List[PipelineResult]:
        return self._consume_steps(self._run_orthogonal_fault_bundle_steps(subcases))

    def _run_orthogonal_fault_bundle_steps(self, subcases):
        """同一入口 VS 一次 patch 多条 match；对每个子用例分别请求、采集与校验。"""
        if any(requires_controlled_stimulus(sc) for sc in subcases):
            results = []
            for sc in subcases:
                results.append((yield from self._run_single_steps(sc)))
            return results
        if not self._safety.allow_fault_injection:
            reasons = [
                "未开启故障注入，无法诱发 5xx/时延；熔断、超时、重试无法做动态验证"
            ]
            return [self._skip_result(sc, reasons) for sc in subcases]
        bundle_start = time.time()
        injector = None  # type: Optional[FaultInjector]
        results: List[PipelineResult] = []
        try:
            first = subcases[0]
            if not all(sc.metadata.get("_scheduler_inventory_known") for sc in subcases):
                self._prepare_resource_plans(subcases)
            if not all(sc.metadata.get("_scheduler_inventory_known") for sc in subcases):
                raise RuntimeError("Cannot safely resolve bundled fault resources")
            svc = first.host or first.source_service
            path_prefix = first.path or ""
            inferred = resolve_meshscope_svc(path_prefix, svc or "")
            ingress_vs = synth_ingress_vs_name_for_case(path_prefix, inferred or (svc or ""))
            if any(sc.metadata["_scheduler_fault_target"]["name"] != ingress_vs for sc in subcases):
                raise RuntimeError("Bundled injection target differs from reserved resource")
            route0 = inferred or (svc or "")
            injector = FaultInjector(
                self._ssh, vs_name=ingress_vs, route_host=route0, namespace=self._namespace
            )
            items = []
            for sc in subcases:
                it = subcase_to_inject_item(sc)
                if not it:
                    raise RuntimeError(
                        "bundle 子用例无法构造注入项: {0}".format(sc.case_id)
                    )
                items.append(it)
            injector.inject_multi_ingress_faults(items)

            pre_log_lines: Dict[str, dict] = {}
            if self._collector and hasattr(self._collector, "snapshot_log_lines"):
                for sc in subcases:
                    pre_log_lines[sc.case_id] = self._collector.snapshot_log_lines(sc)

            executions: Dict[str, ExecutionResult] = {}
            for sc in subcases:
                executor = self._select_executor(sc)
                ex = executor.execute(sc)
                save_execution_result(sc.case_id, ex, sc.protocol)
                executions[sc.case_id] = ex

            wait_max = 0.0
            for sc in subcases:
                ex = executions.get(sc.case_id)
                body_usable = bool(((ex.metadata if ex else {}) or {}).get("body_usable"))
                wait_max = max(
                    wait_max,
                    _post_http_collect_sleep_seconds(
                        sc,
                        has_pre_prometheus=False,
                        prom_url=self._prometheus_url,
                        body_usable=body_usable,
                    ),
                )
            if wait_max > 0:
                yield ObservationWait(wait_max)

            dur = round(time.time() - bundle_start, 2)
            for sc in subcases:
                execution = executions.get(sc.case_id)
                collection = None
                validation = None
                if self._collector:
                    pre = pre_log_lines.get(sc.case_id, {})
                    skip_telemetry = bool(((execution.metadata if execution else {}) or {}).get("body_usable"))
                    collection = self._collector.collect(
                        sc, pre_snapshot=pre, skip_telemetry=skip_telemetry
                    )
                validation = self._validator.validate(sc, execution, collection)
                results.append(
                    PipelineResult(
                        test_case=sc,
                        execution=execution,
                        collection=collection,
                        validation=validation,
                        case_duration_seconds=dur,
                    )
                )
        except Exception as e:
            print("  [ERROR] orthogonal fault bundle: {0}".format(e))
            dur = round(time.time() - bundle_start, 2)
            done_ids = {r.test_case.case_id for r in results}
            for sc in subcases:
                if sc.case_id in done_ids:
                    continue
                results.append(
                    PipelineResult(
                        test_case=sc,
                        execution=None,
                        collection=None,
                        validation=None,
                        case_duration_seconds=dur,
                    )
                )
        finally:
            if injector:
                print("  [CLEANUP] 清理 bundle 故障注入")
                injector.clear_faults()
        return results

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _run_single(self, tc: TestCase) -> PipelineResult:
        """Synchronous compatibility entry point; suite runs can defer waits."""
        return self._consume_steps(self._run_single_steps(tc))

    @staticmethod
    def _consume_steps(steps):
        try:
            while True:
                delay = next(steps)
                time.sleep(delay.seconds)
        except StopIteration as completed:
            return completed.value
        finally:
            steps.close()

    def _run_single_steps(self, tc: TestCase):
        if requires_controlled_stimulus(tc):
            from istio_Dynamic_Test.internal.validation.policies.controlled import unavailable
            return PipelineResult(test_case=tc, validation=unavailable(tc), case_duration_seconds=0.0)
        reasons = case_block_reasons(tc, self._safety)
        if reasons:
            return self._skip_result(tc, reasons)
        injector = None
        pending = None
        execution = None
        collection = None
        validation = None
        case_start = time.time()

        try:
            # Phase 1: 故障注入（如果需要）
            injector = self._inject_fault(tc)

            # Phase 1.5: 记录执行前快照
            pre_log_lines = {}
            pre_prometheus = None
            if self._collector:
                if hasattr(self._collector, 'snapshot_log_lines'):
                    pre_log_lines = self._collector.snapshot_log_lines(tc)
                if (PolicyType.TRAFFIC_SPLIT in tc.policy_types
                        and hasattr(self._collector, 'snapshot_prometheus')):
                    pre_prometheus = self._collector.snapshot_prometheus(tc)

            # Phase 2: 执行（traffic_split 用 MeshExecutor 发固定 N 次请求）
            executor = self._select_executor(tc)
            if (tc.trigger_condition == "connection_pool_outlier_validation"
                    or isinstance(executor, ConnectionPoolOutlierExecutor)):
                if not tc.metadata.get("_scheduler_inventory_known"):
                    self._prepare_resource_plans([tc])
                if not tc.metadata.get("_scheduler_inventory_known"):
                    raise RuntimeError("Cannot safely resolve connection-pool fault resource")
                pending = self._cp_outlier_executor.execute_phase1_clear(tc)
                yield ObservationWait(max(0.0, pending.resume_at - time.time()))
                execution = self._cp_outlier_executor.execute_phase2_recovery(pending)
            else:
                execution = executor.execute(tc)
            save_execution_result(tc.case_id, execution, tc.protocol)

            # Phase 3: 数据采集（traffic_split 用 Prometheus 时等待，时长可由环境变量配置）
            if self._collector:
                body_usable = bool((execution.metadata or {}).get("body_usable"))
                wait = _post_http_collect_sleep_seconds(
                    tc,
                    has_pre_prometheus=pre_prometheus is not None,
                    prom_url=self._prometheus_url,
                    body_usable=body_usable,
                )
                if wait > 0:
                    yield ObservationWait(wait)
                collect_kw = {"pre_snapshot": pre_log_lines, "skip_telemetry": body_usable}
                if pre_prometheus is not None:
                    collect_kw["pre_prometheus"] = pre_prometheus
                collection = self._collector.collect(tc, **collect_kw)

            # Phase 4: 验证
            validation = self._validator.validate(tc, execution, collection)

        except Exception as e:
            print(f"  [ERROR] {tc.case_id}: {e}")
        finally:
            # 故障恢复：每个用例执行后立即恢复
            if injector:
                print(f"  [CLEANUP] 清理故障注入")
                injector.clear_faults()

        case_duration = time.time() - case_start
        return PipelineResult(
            test_case=tc,
            execution=execution,
            collection=collection,
            validation=validation,
            case_duration_seconds=round(case_duration, 2),
        )

    def _select_executor(self, tc: TestCase) -> BaseExecutor:
        return self._executor_registry.select(tc)

    def _inject_fault(self, tc: TestCase) -> Optional[FaultInjector]:
        if requires_controlled_stimulus(tc) or not self._safety.allow_fault_injection:
            return None
        trigger = mutation_trigger(tc)
        if not trigger or trigger == "connection_pool_outlier_validation":
            return None
        if "_scheduler_fault_target" not in tc.metadata:
            self._prepare_resource_plans([tc])
        if not tc.metadata.get("_scheduler_inventory_known"):
            raise RuntimeError("Cannot safely resolve fault resource without VirtualService inventory")
        target = tc.metadata["_scheduler_fault_target"]
        params = tc.fault_params or {}
        path_prefix = tc.path or ""
        vs_name = target["name"]
        route_host = target["route_host"]
        use_ingress_vs = target["match_ingress"]
        key = f"{vs_name}_{route_host}_{path_prefix or ''}"

        if key not in self._fault_injectors:
            self._fault_injectors[key] = FaultInjector(
                self._ssh, vs_name=vs_name, route_host=route_host, namespace=self._namespace,
            )
        injector = self._fault_injectors[key]

        if trigger == "simulate_503_error":
            injector.inject_http_fault(error_code=503)
        elif trigger == "simulate_config_fault":
            ft = params.get("fault_type", "abort")
            if ft == "abort":
                injector.inject_config_fault(
                    fault_type="abort",
                    status_code=params.get("fault_status", 503),
                    percentage=params.get("fault_percentage", 100),
                    match_path=(path_prefix or None) if use_ingress_vs else None,
                )
            elif ft == "delay":
                injector.inject_config_fault(
                    fault_type="delay",
                    delay=params.get("fault_delay", "1s"),
                    percentage=params.get("fault_percentage", 100),
                    match_path=(path_prefix or None) if use_ingress_vs else None,
                )
        elif trigger == "simulate_high_load_with_errors":
            injector.inject_upstream_error_scenario(
                error_percentage=80,
                match_path=(path_prefix or None) if use_ingress_vs else None,
            )
        elif trigger == "simulate_config_fault_with_timeout":
            injector.inject_fault_with_timeout(
                status_code=params.get("fault_status", 503),
                percentage=params.get("fault_percentage", 100),
                timeout=params.get("timeout_limit", "2s"),
                match_path=(path_prefix or None) if use_ingress_vs else None,
            )
        elif trigger == "__meshscope_delay_for_timeout__":
            injector.inject_config_fault(
                fault_type="delay",
                delay=params.get("response_delay", params.get("fault_delay", "3s")),
                percentage=100,
                match_path=(path_prefix or None) if use_ingress_vs else None,
            )

        return injector

    def _clear_all_faults(self):
        """确保所有故障注入器已恢复，避免遗留故障配置。"""
        for key, injector in self._fault_injectors.items():
            if injector._injected or injector._created:
                print(f"  [CLEANUP] 清理遗留故障: {key}")
                injector.clear_faults()

    @staticmethod
    def _print_summary(results: List[PipelineResult]):
        total = len(results)
        passed = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.PASSED)
        failed = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.FAILED)
        warning = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.WARNING)
        inconclusive = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.INCONCLUSIVE)
        skipped = sum(1 for r in results if (not r.validation) or (r.validation.overall_status == ValidationStatus.SKIPPED))
        denom = passed + failed  # 用“可判定用例”的通过率，避免 SKIPPED/WARNING 拉低
        rate = passed / denom * 100 if denom else 0.0
        print(f"  通过: {passed}  失败: {failed}  未判定: {inconclusive}  警告: {warning}  跳过: {skipped}  通过率(通过/(通过+失败)): {rate:.1f}%")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Istio 动态验证流水线")
    parser.add_argument("-i", "--input", help="Istio 配置文件路径")
    parser.add_argument("--matrix", help="旧版测试矩阵文件路径 (output_matrix.json)")
    parser.add_argument("--ingress-url", default="", help="集群入口 URL")
    parser.add_argument("--service-deps", help="服务依赖 JSON 路径")
    parser.add_argument("--namespace", default=None, help="K8s 命名空间")
    parser.add_argument(
        "--control-plane-config",
        default=None,
        help="控制面配置目录，动态验证前会从此目录同步最新 VS/DR 到 istio_config",
    )
    parser.add_argument(
        "--from-control-plane",
        action="store_true",
        help="直接从 --control-plane-config 目录生成用例（验证当前集群配置），不依赖 -i/--input 文件。",
    )
    parser.add_argument("--prometheus-url", default="", help="Prometheus URL（流量分割验证用，如 http://192.0.2.10:31012）")
    parser.add_argument("--jaeger-url", default="", help="Jaeger URL（响应体无版本信号时回退）")
    parser.add_argument("--ssh-host", help="SSH 主机")
    parser.add_argument("--ssh-user", help="SSH 用户名")
    parser.add_argument("--ssh-password", help="SSH 密码")
    parser.add_argument("--ssh-port", type=int, default=None, help="SSH 端口")
    parser.add_argument("--single-case", help="只运行指定用例 (如 case_005)")
    parser.add_argument(
        "--load-test",
        dest="allow_load_test",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否做高压测试（限流高压、连接池打满）。关闭时这些用例将跳过。",
    )
    parser.add_argument(
        "--fault-injection",
        dest="allow_fault_injection",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否改 VirtualService 注入 abort/delay。关闭时熔断、超时、重试无法动态验证。",
    )
    parser.add_argument(
        "--rollout",
        dest="allow_rollout",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否 patch Deployment 打开 Envoy access log。etcd 不稳时请关闭。",
    )
    args = parser.parse_args()
    try:
        from consistency_checker.config import fill_args_from_config, get_config
        fill_args_from_config(args, {
            "ingress_url": "ingress_url",
            "prometheus_url": "prometheus_url",
            "jaeger_url": "jaeger_url",
            "ssh_host": "ssh_host",
            "ssh_user": "ssh_user",
            "ssh_password": "ssh_password",
            "ssh_port": "ssh_port",
            "namespace": "namespace",
            "control_plane_config": "control_plane_config_dir",
            "service_deps": "service_dependencies_file",
            "allow_load_test": "allow_load_test",
            "allow_fault_injection": "allow_fault_injection",
            "allow_rollout": "allow_rollout",
        })
        if not args.ingress_url:
            args.ingress_url = get_config().get_ingress_url() or ""
        from istio_Dynamic_Test.internal.traffic.entry import resolve_ingress_base
        args.ingress_url = resolve_ingress_base(args.ingress_url)
        if not args.input and not args.matrix and not args.from_control_plane:
            args.input = get_config().istio_config_file
    except Exception:
        pass
    if not args.namespace:
        args.namespace = "default"
    if not args.control_plane_config:
        args.control_plane_config = "istio_config_parser/istio_monitor/istio_control_config"
    if args.ssh_port is None:
        args.ssh_port = 22

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
        from istio_Dynamic_Test.internal.testcase.generators.config_generator import ConfigGenerator
        generator = ConfigGenerator(
            args.input,
            service_deps_path=args.service_deps,
            ingress_url=args.ingress_url,
            namespace=args.namespace,
            control_plane_config_path=args.control_plane_config,
        )
    elif args.from_control_plane:
        from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator
        generator = SemanticGenerator(
            ingress_url=args.ingress_url,
            namespace=args.namespace,
        )

    ingress_url = (suite.ingress_url if suite else "") or args.ingress_url
    jaeger_url = getattr(args, "jaeger_url", "") or ""
    zipkin_url = ""
    try:
        cfg = get_config()
        if not jaeger_url:
            jaeger_url = cfg.jaeger_url or ""
        zipkin_url = cfg.zipkin_url or ""
    except Exception:
        pass
    tester = DynamicTester(
        generator=generator,
        ssh_config=ssh_config,
        namespace=args.namespace,
        prometheus_url=args.prometheus_url or None,
        ingress_url=ingress_url or None,
        jaeger_url=jaeger_url or None,
        zipkin_url=zipkin_url or None,
        safety=options_from_config({
            "allow_load_test": getattr(args, "allow_load_test", None),
            "allow_fault_injection": getattr(args, "allow_fault_injection", None),
            "allow_rollout": getattr(args, "allow_rollout", None),
        }),
    )
    # 进程退出时（含 Ctrl+C）确保故障恢复
    atexit.register(tester._clear_all_faults)

    # 单例模式：需先有 suite（-i 时从 generator 生成）
    if args.single_case:
        s = suite or (generator.generate_suite() if generator else None)
        if s:
            tc = next((c for c in s.cases if c.case_id == args.single_case), None)
            if tc:
                tester.run_single(tc)
            else:
                print(f"[ERROR] 未找到用例: {args.single_case}")
        else:
            print("[ERROR] 无测试用例可执行")
    else:
        tester.run(suite)


if __name__ == "__main__":
    main()
