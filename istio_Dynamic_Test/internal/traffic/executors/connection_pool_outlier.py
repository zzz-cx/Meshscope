"""ConnectionPoolOutlierExecutor —— 多阶段执行器，验证连接池与熔断参数。

阶段 1: 注入 503 故障 -> 高并发负载 -> 统计 503 数量（验证 consecutiveErrors 触发）
阶段 2: 清除故障 -> 等待 baseEjectionTime -> 发送请求（验证熔断恢复）
"""

import re
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, TestCase
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient
from istio_Dynamic_Test.internal.traffic.protocols.http.curl import build_status_curl_cmd
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor
from istio_Dynamic_Test.internal.traffic.fault.injector import FaultInjector


def _parse_duration_seconds(s: str) -> int:
    """解析 Istio 时长字符串为秒数。如 60s->60, 1m->60, 3m->180。"""
    if not s or not isinstance(s, str):
        return 60
    s = str(s).strip().lower()
    m = re.match(r"^(\d+)(s|m|h)?$", s)
    if not m:
        return 60
    val = int(m.group(1))
    unit = m.group(2) or "s"
    if unit == "s":
        return val
    if unit == "m":
        return val * 60
    if unit == "h":
        return val * 3600
    return val


class ConnectionPoolOutlierExecutor(BaseExecutor):
    """连接池与熔断参数验证执行器。

    从 test_case.metadata 读取 expected_outcome 中的 dr_params：
    - consecutive_errors: 连续错误次数触发熔断
    - base_ejection_time: 熔断驱逐时长（如 60s）
    - max_connections, http1_max_pending_requests: 连接池参数（用于报告）
    """

    def __init__(
        self,
        ssh_client: Optional[SSHClient] = None,
        namespace: str = "default",
    ):
        self._ssh = ssh_client or SSHClient()
        self._namespace = namespace

    def execute(self, test_case: TestCase) -> ExecutionResult:
        """
        兼容旧行为：完整同步执行（包含 baseEjectionTime 等待）。

        在 DynamicTester 并行调度模式下，会优先调用 execute_phase1_clear()/execute_phase2_recovery()
        以便把等待阶段外提并穿插执行其它用例。
        """
        pending = self.execute_phase1_clear(test_case)
        time.sleep(max(0, int(pending.wait_seconds)))
        return self.execute_phase2_recovery(pending)

    @dataclass
    class PendingWait:
        test_case: TestCase
        injector: FaultInjector
        curl_cmd: str
        wait_seconds: int
        resume_at: float
        phase1_elapsed_s: float
        phase1_total: int
        phase1_503_count: int
        phase1_status_codes: dict
        conn_limits: dict
        consecutive_errors: int
        base_ejection: str

    def execute_phase1_clear(self, test_case: TestCase) -> "ConnectionPoolOutlierExecutor.PendingWait":
        phase1_start = time.time()
        outcome = (test_case.metadata or {}).get("expected_outcome", {})
        conn_limits = outcome.get("connection_limits", {})
        consecutive_errors = outcome.get("circuit_breaker_threshold") or conn_limits.get("consecutive_errors", 5)
        base_ejection = outcome.get("base_ejection_time") or conn_limits.get("base_ejection_time") or "60s"
        wait_seconds = _parse_duration_seconds(base_ejection)

        # host='*'（单入口模型）时要用 source_service 作为真实服务名，否则会生成非法 VS 名
        host = test_case.source_service or test_case.host
        # 单入口模型对齐：优先把 upstream error 注入打到入口 VS 的对应 /s{i}/ 路由上
        vs_name = host
        route_host = host
        match_path = test_case.path or None
        try:
            # host 可能是 FQDN，先归一化
            h = (host or "").split(".svc.cluster.local", 1)[0]
            h = h.split(".", 1)[0]
            if h.startswith("meshscope-svc-"):
                vs_name = "meshscope-synth-ingress"
                route_host = h
                # 若本用例没有显式 path（很多用例是 http://ingress/ + Host 头），则不要强加 /s{i}/，
                # 否则注入规则可能匹配不到实际流量。
                if not match_path:
                    match_path = None
        except Exception:
            pass

        injector = FaultInjector(
            self._ssh,
            vs_name=vs_name,
            route_host=route_host,
            namespace=self._namespace,
        )

        curl_cmd, _url = build_status_curl_cmd(
            test_case, extra_headers={"Connection": "close"}
        )

        # 阶段 1: 注入故障，高并发负载，统计 503
        print(f"  [CP_OUTLIER] 阶段1: 注入 80% 上游错误，触发熔断（期望 consecutiveErrors={consecutive_errors}）")
        injector.inject_upstream_error_scenario(error_percentage=80, match_path=match_path)

        n = max(test_case.request_count, consecutive_errors * 10)
        conc = min(test_case.concurrency, n, 20)
        if conc < 8:
            conc = 8

        codes_phase1: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(self._run_curl, curl_cmd) for _ in range(n)]
            for fut in as_completed(futures):
                try:
                    code = fut.result(timeout=30)
                    codes_phase1[code] = codes_phase1.get(code, 0) + 1
                except Exception:
                    codes_phase1["error"] = codes_phase1.get("error", 0) + 1

        total1 = sum(codes_phase1.values())
        cnt_503 = codes_phase1.get("503", 0)
        print(f"  [CP_OUTLIER] 阶段1 结果: 总请求={total1}, 503={cnt_503}, 分布={dict(sorted(codes_phase1.items()))}")

        # 阶段 2: 清除故障，等待 baseEjectionTime（等待外提给调度器）
        print(f"  [CP_OUTLIER] 阶段2: 清除故障，等待 baseEjectionTime={base_ejection} ({wait_seconds}s)")
        injector.clear_faults()
        phase1_elapsed = time.time() - phase1_start
        return ConnectionPoolOutlierExecutor.PendingWait(
            test_case=test_case,
            injector=injector,
            curl_cmd=curl_cmd,
            wait_seconds=wait_seconds,
            resume_at=time.time() + wait_seconds,
            phase1_elapsed_s=phase1_elapsed,
            phase1_total=total1,
            phase1_503_count=cnt_503,
            phase1_status_codes=codes_phase1,
            conn_limits=conn_limits,
            consecutive_errors=int(consecutive_errors),
            base_ejection=str(base_ejection),
        )

    def execute_phase2_recovery(self, pending: "ConnectionPoolOutlierExecutor.PendingWait") -> ExecutionResult:
        test_case = pending.test_case
        # 阶段 3: 发送恢复验证请求
        n_recovery = 20
        codes_phase2: dict[str, int] = {}
        for _ in range(n_recovery):
            code = self._run_curl(pending.curl_cmd)
            codes_phase2[code] = codes_phase2.get(code, 0) + 1

        total2 = sum(codes_phase2.values())
        cnt_200 = codes_phase2.get("200", 0)
        print(f"  [CP_OUTLIER] 阶段2 恢复验证: 总请求={total2}, 200={cnt_200}, 分布={dict(sorted(codes_phase2.items()))}")

        all_codes = {}
        for k, v in pending.phase1_status_codes.items():
            all_codes[k] = all_codes.get(k, 0) + v
        for k, v in codes_phase2.items():
            all_codes[k] = all_codes.get(k, 0) + v
        total = pending.phase1_total + total2
        success = sum(c for k, c in all_codes.items() if str(k).startswith("2"))
        rate = (success / total * 100) if total > 0 else 0.0

        metadata = {
            "phase1_total": pending.phase1_total,
            "phase1_503_count": pending.phase1_503_count,
            "phase1_status_codes": pending.phase1_status_codes,
            "phase2_total": total2,
            "phase2_200_count": cnt_200,
            "phase2_status_codes": codes_phase2,
            "expected_consecutive_errors": pending.consecutive_errors,
            "expected_base_ejection_time": pending.base_ejection,
            "expected_base_ejection_seconds": pending.wait_seconds,
            "connection_limits": pending.conn_limits,
            "scheduler": {"wait_externalized": True},
        }

        return ExecutionResult(
            case_id=test_case.case_id,
            status_codes=all_codes,
            total_requests=total,
            success_rate=rate,
            avg_response_time=0.0,
            error_count=total - success,
            metadata=metadata,
        )

    def _run_curl(self, cmd: str) -> str:
        out, _ = self._ssh.run_command(cmd)
        return (out or "").strip() or "error"
