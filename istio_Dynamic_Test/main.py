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

import argparse
import atexit
import io
import json
import os
import sys
import time
from datetime import datetime
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
from istio_Dynamic_Test.models.test_case import ValidationStatus
from istio_Dynamic_Test.generators.base import BaseGenerator
from istio_Dynamic_Test.models.test_case import PolicyType
from istio_Dynamic_Test.executors.base import BaseExecutor
from istio_Dynamic_Test.executors.http_executor import HttpExecutor
from istio_Dynamic_Test.executors.load_executor import LoadExecutor
from istio_Dynamic_Test.executors.mesh_executor import MeshExecutor
from istio_Dynamic_Test.executors.connection_pool_outlier_executor import ConnectionPoolOutlierExecutor
from istio_Dynamic_Test.executors.fault_injector import FaultInjector
from istio_Dynamic_Test.executors.safe_parallel_scheduler import LockManager, tag_case_locks
from istio_Dynamic_Test.bundling.orthogonal_fault_bundle import (
    apply_orthogonal_fault_bundling,
    flatten_cases_for_warmup,
    orthogonal_fault_bundle_enabled,
    subcase_to_inject_item,
)
from istio_Dynamic_Test.collectors.base import BaseCollector
from istio_Dynamic_Test.validators.base import BaseValidator
from istio_Dynamic_Test.validators.composite_validator import CompositeValidator
from istio_Dynamic_Test.validators.report_generator import ReportGenerator
from istio_Dynamic_Test.utils.ssh_utils import SSHClient
from istio_Dynamic_Test.utils.ingress_shard import synth_ingress_vs_name_for_case


def _svc_from_ingress_path(path: str) -> str:
    """
    单入口模型（meshscope-synth-ingress）下，约定路径 /s{i}/... 对应服务 meshscope-svc-{i:04d}。
    返回空字符串表示无法推断。
    """
    import re
    p = (path or "").strip()
    m = re.match(r"^/s(\d+)(/|$)", p)
    if not m:
        return ""
    try:
        idx = int(m.group(1))
    except Exception:
        return ""
    return f"meshscope-svc-{idx:04d}"


def _svc_from_name(name: str) -> str:
    """从 host/FQDN 中提取 meshscope-svc-XXXX（短名）。"""
    import re
    n = (name or "").strip()
    if not n:
        return ""
    # 截断 FQDN / namespace
    if ".svc.cluster.local" in n:
        n = n.split(".svc.cluster.local", 1)[0]
    if "." in n:
        n = n.split(".", 1)[0]
    m = re.match(r"^(meshscope-svc-\d{4})$", n)
    return m.group(1) if m else ""


def _path_for_meshscope_svc(svc: str) -> str:
    """meshscope-svc-0000 -> /s0/"""
    import re
    m = re.match(r"^meshscope-svc-(\d{4})$", svc or "")
    if not m:
        return ""
    return f"/s{int(m.group(1))}/"


def _post_http_collect_sleep_seconds(
    tc: TestCase, *, has_pre_prometheus: bool, prom_url: Optional[str]
) -> float:
    """采集前等待秒数：默认保持旧行为；可用环境变量与 DYNAMIC_TEST_SLEEP_SCALE 缩放。"""
    try:
        scale = float(os.getenv("DYNAMIC_TEST_SLEEP_SCALE", "1") or "1")
    except ValueError:
        scale = 1.0
    if PolicyType.TRAFFIC_SPLIT in (tc.policy_types or []):
        if has_pre_prometheus:
            key = "DYNAMIC_TEST_SLEEP_TRAFFIC_SPLIT_PROM_S"
            default = "12"
        else:
            key = "DYNAMIC_TEST_SLEEP_TRAFFIC_SPLIT_NO_PROM_S"
            default = "2"
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
    ):
        self._generator = generator
        self._custom_executor = executor
        self._collector = collector
        self._prometheus_url = prometheus_url
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

        # 按 TestType / PolicyType 的默认执行器
        self._http_executor = HttpExecutor(self._ssh)
        self._load_executor = LoadExecutor(self._ssh)
        self._mesh_executor = MeshExecutor(self._ssh, namespace=namespace)
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
        print(f"{'=' * 60}\n")

        # 预热 Collector（启用 access log）
        if self._collector and hasattr(self._collector, "warmup_for_suite"):
            self._collector.warmup_for_suite(flatten_cases_for_warmup(suite.cases))

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
        lock_mgr = LockManager()
        pool = None
        futures = []  # type: List[any]
        if max_workers > 1:
            from concurrent.futures import ThreadPoolExecutor  # lazy import
            pool = ThreadPoolExecutor(max_workers=max_workers)
            print(f"  [SCHED] safe-parallel enabled: max_workers={max_workers}")

        pending_cp_outlier: list[tuple[int, ConnectionPoolOutlierExecutor.PendingWait]] = []
        externalized_wait_s_total = 0.0

        def _drain_pending(now: float) -> None:
            # 仅在到点后恢复；恢复阶段不写 meshscope-synth-ingress
            ready = [p for p in pending_cp_outlier if now >= p[1].resume_at]
            for idx, pending in ready:
                pending_cp_outlier.remove((idx, pending))
                tc = pending.test_case
                print(f"\n[RESUME {tc.case_id}] connection_pool_outlier phase2 recovery")
                resume_start = time.time()
                execution = self._cp_outlier_executor.execute_phase2_recovery(pending)
                self._save_http_result(tc.case_id, execution)
                # Phase 3/4: 采集与验证（对齐 _run_single）
                collection = None
                validation = None
                if self._collector:
                    time.sleep(1)
                    collection = self._collector.collect(tc, pre_snapshot={})
                validation = self._validator.validate(tc, execution, collection)
                phase2_elapsed = time.time() - resume_start
                case_duration = round(float(getattr(pending, "phase1_elapsed_s", 0.0)) + phase2_elapsed, 2)
                pr = PipelineResult(
                    test_case=tc,
                    execution=execution,
                    collection=collection,
                    validation=validation,
                    case_duration_seconds=case_duration,
                )
                results.append(pr)
                if pr.validation:
                    status = pr.validation.overall_status.value.upper()
                    print(f"  => {status}: {pr.validation.summary}")

        for i, tc in enumerate(suite.cases, 1):
            # 若有到点的 pending，先补跑恢复阶段
            _drain_pending(time.time())

            print(f"\n[{i}/{total}] {tc.case_id}: {tc.description}")
            print(f"  策略: {[p.value for p in tc.policy_types]}")

            # 特殊：connection_pool_outlier_validation 把等待阶段外提，允许等待期间继续跑其它用例
            if tc.metadata.get("is_orthogonal_fault_bundle"):
                subs = tc.metadata.get("bundle_subcases") or []
                print(f"  [BUNDLE] 子用例数={len(subs)}: {[s.case_id for s in subs]}")
                if pool is None:
                    for pr in self._run_orthogonal_fault_bundle(subs):
                        results.append(pr)
                        if pr.validation:
                            status = pr.validation.overall_status.value.upper()
                            print(f"  => {status}: {pr.validation.summary}")
                else:
                    locks = tag_case_locks(tc)
                    print(f"  [SCHED] submit locks={locks}")

                    def _job(case: TestCase, case_locks: List[str]) -> List[PipelineResult]:
                        with lock_mgr.acquire_all(case_locks):
                            return self._run_case_results(case)

                    futures.append(pool.submit(_job, tc, locks))
                continue

            if tc.trigger_condition == "connection_pool_outlier_validation":
                try:
                    pending = self._cp_outlier_executor.execute_phase1_clear(tc)
                    externalized_wait_s_total += float(pending.wait_seconds or 0)
                    print(f"  [SCHED] phase1 done in {getattr(pending, 'phase1_elapsed_s', 0.0):.1f}s, wait={pending.wait_seconds}s (externalized)")
                    pending_cp_outlier.append((i, pending))
                    # 该用例的 phase2 恢复稍后补跑；先继续下一个用例
                    continue
                except Exception as e:
                    print(f"  [ERROR] {tc.case_id}: {e}")
                    # 出错则回退串行执行，保证完整性
                    result = self._run_single(tc)
                    results.append(result)
                    if result.validation:
                        status = result.validation.overall_status.value.upper()
                        print(f"  => {status}: {result.validation.summary}")
                    continue

            if pool is None:
                for result in self._run_case_results(tc):
                    results.append(result)
                    if result.validation:
                        status = result.validation.overall_status.value.upper()
                        print(f"  => {status}: {result.validation.summary}")
            else:
                locks = tag_case_locks(tc)
                print(f"  [SCHED] submit locks={locks}")

                def _job(case: TestCase, case_locks: List[str]) -> List[PipelineResult]:
                    with lock_mgr.acquire_all(case_locks):
                        return self._run_case_results(case)

                futures.append(pool.submit(_job, tc, locks))

        # 跑完所有用例后，补齐 pending 的恢复阶段
        while pending_cp_outlier:
            _drain_pending(time.time())
            if pending_cp_outlier:
                # 若还没到点，短睡眠并继续
                time.sleep(1)

        # 等待并行提交的用例完成
        if pool is not None:
            from concurrent.futures import as_completed
            for fut in as_completed(futures):
                try:
                    for pr in fut.result():
                        results.append(pr)
                except Exception as e:
                    print(f"  [ERROR] parallel case failed: {e}")
            try:
                pool.shutdown(wait=True)
            except Exception:
                pass

        elapsed = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"  流水线完成  耗时: {elapsed:.1f}s")
        if externalized_wait_s_total > 0:
            print(f"  [SCHED] externalized_wait_s_total: {externalized_wait_s_total:.1f}s")
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

    def _run_case_results(self, tc: TestCase) -> List[PipelineResult]:
        """单调度行对应的流水线结果（bundle 会展开为多份子用例结果）。"""
        if tc.metadata.get("is_orthogonal_fault_bundle"):
            subs = tc.metadata.get("bundle_subcases") or []
            return self._run_orthogonal_fault_bundle(subs)
        return [self._run_single(tc)]

    def _run_orthogonal_fault_bundle(self, subcases: List[TestCase]) -> List[PipelineResult]:
        """同一入口 VS 一次 patch 多条 match；对每个子用例分别请求、采集与校验。"""
        bundle_start = time.time()
        injector = None  # type: Optional[FaultInjector]
        results: List[PipelineResult] = []
        try:
            first = subcases[0]
            svc = first.host or first.source_service
            path_prefix = first.path or ""
            inferred = _svc_from_ingress_path(path_prefix) or _svc_from_name(svc)
            ingress_vs = synth_ingress_vs_name_for_case(path_prefix, inferred or (svc or ""))
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
                self._save_http_result(sc.case_id, ex)
                executions[sc.case_id] = ex

            wait_max = 0.0
            for sc in subcases:
                wait_max = max(
                    wait_max,
                    _post_http_collect_sleep_seconds(
                        sc,
                        has_pre_prometheus=False,
                        prom_url=self._prometheus_url,
                    ),
                )
            if wait_max > 0:
                time.sleep(wait_max)

            dur = round(time.time() - bundle_start, 2)
            for sc in subcases:
                execution = executions.get(sc.case_id)
                collection = None
                validation = None
                if self._collector:
                    pre = pre_log_lines.get(sc.case_id, {})
                    collection = self._collector.collect(sc, pre_snapshot=pre)
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
        injector = None
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
            execution = executor.execute(tc)
            self._save_http_result(tc.case_id, execution)

            # Phase 3: 数据采集（traffic_split 用 Prometheus 时等待，时长可由环境变量配置）
            if self._collector:
                wait = _post_http_collect_sleep_seconds(
                    tc,
                    has_pre_prometheus=pre_prometheus is not None,
                    prom_url=self._prometheus_url,
                )
                if wait > 0:
                    time.sleep(wait)
                collect_kw = {"pre_snapshot": pre_log_lines}
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
        if self._custom_executor:
            return self._custom_executor
        # 连接池与熔断参数专项验证：多阶段执行器（自管故障注入与恢复）
        if (tc.trigger_condition == "connection_pool_outlier_validation"
                or PolicyType.CONNECTION_POOL_OUTLIER in (tc.policy_types or [])):
            return self._cp_outlier_executor
        # traffic_split：MeshExecutor 发固定 N 次请求，Collector 取 Prometheus 增量校验
        if PolicyType.TRAFFIC_SPLIT in tc.policy_types:
            return self._mesh_executor
        if tc.test_type == TestType.LOAD_TEST:
            return self._load_executor
        return self._http_executor

    def _inject_fault(self, tc: TestCase) -> Optional[FaultInjector]:
        trigger = tc.trigger_condition
        # 单入口模型对齐：timeout 测试矩阵里常用 simulate_slow_response/response_delay 表达“需要变慢”，
        # 但实际 workload（http-echo）不会主动 sleep。这里用入口 VS 的 delay fault 做确定性触发，
        # 使 TimeoutValidator 能稳定观测到 504/UT。
        params = tc.fault_params or {}
        if not trigger:
            if params.get("simulate_slow_response") and (params.get("response_delay") or params.get("fault_delay")):
                trigger = "__meshscope_delay_for_timeout__"
            else:
                return None
        # connection_pool_outlier_validation 由 ConnectionPoolOutlierExecutor 自管故障注入
        if trigger == "connection_pool_outlier_validation":
            return None

        # 单入口模型对齐：如果存在 meshscope 合成入口 VS，则优先把故障注入打到对应分片 VS，
        # 并用 path 前缀限定命中范围，避免“注入了但流量没走到注入点”。
        svc = tc.host or tc.source_service
        path_prefix = tc.path or ""
        inferred = _svc_from_ingress_path(path_prefix) or _svc_from_name(svc)
        ingress_vs = synth_ingress_vs_name_for_case(path_prefix, inferred or (svc or ""))
        use_ingress_vs = False
        try:
            out, err = self._ssh.run_command(f"kubectl get virtualservice {ingress_vs} -n {self._namespace} 2>&1")
            combined = (out or "") + (err or "")
            if "NotFound" not in combined and "Error" not in combined:
                use_ingress_vs = True
        except Exception:
            pass

        if use_ingress_vs and inferred:
            vs_name = ingress_vs
            route_host = inferred
            key = f"{vs_name}_{route_host}_{path_prefix or ''}"
        else:
            vs_name = svc
            route_host = svc
            key = f"{vs_name}_{route_host}"

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
        total = len(results)
        passed = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.PASSED)
        failed = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.FAILED)
        warning = sum(1 for r in results if r.validation and r.validation.overall_status == ValidationStatus.WARNING)
        skipped = sum(1 for r in results if (not r.validation) or (r.validation.overall_status == ValidationStatus.SKIPPED))
        denom = passed + failed  # 用“可判定用例”的通过率，避免 SKIPPED/WARNING 拉低
        rate = passed / denom * 100 if denom else 0.0
        print(f"  通过: {passed}  失败: {failed}  警告: {warning}  跳过: {skipped}  通过率(通过/(通过+失败)): {rate:.1f}%")


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
    parser.add_argument(
        "--from-control-plane",
        action="store_true",
        help="直接从 --control-plane-config 目录生成用例（验证当前集群配置），不依赖 -i/--input 文件。",
    )
    parser.add_argument("--prometheus-url", default="", help="Prometheus URL（流量分割验证用，如 http://192.168.92.131:31012）")
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
    elif args.from_control_plane:
        # 直接从控制面快照目录生成用例：写入一个临时 json 作为 ConfigGenerator 的承载文件
        from istio_Dynamic_Test.generators.config_generator import ConfigGenerator
        temp_dir = os.path.join(_PROJECT_ROOT, "evaluation", "e2e", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_cfg = os.path.join(temp_dir, f"istio_config_synced_{args.namespace}.json")
        # 先写一个最小骨架，sync 时会保留 enabled_policies/其他元数据
        if not os.path.exists(temp_cfg):
            with open(temp_cfg, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "description": "自动从 control plane 同步生成（用于动态验证当前集群配置）",
                        "enabled_policies": {
                            "routing": True,
                            "retry": True,
                            "timeout": True,
                            "fault_injection": True,
                            "traffic_split": True,
                            "circuit_breaker": True,
                            "connection_pool": True,
                            "connection_pool_outlier": True,
                            "rate_limit": True,
                            "orthogonal_minimize": True,
                        },
                        "envoyFilters": [],
                        "virtualServices": [],
                        "destinationRules": [],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        generator = ConfigGenerator(
            temp_cfg,
            service_deps_path=args.service_deps,
            ingress_url=args.ingress_url,
            namespace=args.namespace,
            control_plane_config_path=args.control_plane_config,
        )

    ssh = SSHClient(**(ssh_config or {}))

    from istio_Dynamic_Test.collectors.envoy_log_collector import EnvoyCollector
    from istio_Dynamic_Test.collectors.composite_collector import CompositeCollector
    if args.prometheus_url:
        collector = CompositeCollector(
            prometheus_url=args.prometheus_url,
            namespace=args.namespace,
            ssh_client=ssh,
        )
    else:
        collector = EnvoyCollector(ssh_client=ssh, namespace=args.namespace)

    ingress_url = (suite.ingress_url if suite else "") or args.ingress_url
    tester = DynamicTester(
        generator=generator,
        collector=collector,
        ssh_config=ssh_config,
        namespace=args.namespace,
        prometheus_url=args.prometheus_url or None,
        ingress_url=ingress_url or None,
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
