"""
统一数据模型 —— 贯穿 Generator → Executor → Collector → Validator 四层流水线。

所有层之间的数据交换都通过这些数据类完成，确保接口清晰、类型安全。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .protocol import Protocol


# ─── 枚举定义 ────────────────────────────────────────────────────────────────

class TestType(Enum):
    SINGLE_REQUEST = "single_request"
    LOAD_TEST = "load_test"


class PolicyType(Enum):
    ROUTING = "routing"
    TRAFFIC_SPLIT = "traffic_split"
    FAULT_INJECTION = "fault_injection"
    CIRCUIT_BREAKER = "circuit_breaker"
    RETRY = "retry"
    RATE_LIMIT = "rate_limit"
    CONNECTION_POOL = "connection_pool"
    CONNECTION_POOL_OUTLIER = "connection_pool_outlier"  # 连接池与熔断参数专项验证
    TIMEOUT = "timeout"
    ORTHOGONAL_MATCHING = "orthogonal_matching"
    COMPOSITE = "composite"


class ValidationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


# ─── 核心数据类 ──────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    """
    统一测试用例对象。
    由 Generator 生成，依次流经 Executor → Collector → Validator。
    """
    case_id: str
    name: str
    description: str = ""
    test_type: TestType = TestType.SINGLE_REQUEST
    policy_types: List[PolicyType] = field(default_factory=list)

    # 请求参数
    protocol: Protocol = Protocol.HTTP
    target_url: str = ""
    host: str = ""
    path: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    # gRPC 专用（protocol=grpc 时生效）
    grpc_method: str = ""
    grpc_payload: str = "{}"
    grpc_port: Optional[int] = None
    grpc_plaintext: bool = True

    # 负载参数
    request_count: int = 1
    concurrency: int = 1

    # 故障注入触发条件
    trigger_condition: Optional[str] = None
    fault_params: Dict[str, Any] = field(default_factory=dict)

    # 期望结果
    expected_destination: Optional[str] = None
    expected_distribution: Optional[Dict[str, float]] = None
    expected_success_rate: Optional[float] = None
    expected_fault_rate: Optional[float] = None
    expected_fault_code: Optional[int] = None
    expected_retry_attempts: Optional[int] = None
    expected_circuit_breaker_threshold: Optional[int] = None
    margin_of_error: float = 0.1

    # 测试策略标签（用于正交组合）
    test_strategies: List[str] = field(default_factory=list)
    source_service: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 限流动态验证：来自 expected_outcome.rate_limit，由 RateLimitValidator 消费
    rate_limit_expect: Optional[Dict[str, Any]] = None

    # ── 兼容旧版矩阵 JSON 的工厂方法 ─────────────────────────────────────
    @classmethod
    def from_matrix_dict(cls, d: Dict[str, Any], ingress_url: str = "") -> "TestCase":
        """从旧版 output_matrix.json 中的单个 test_case 字典创建 TestCase。"""
        params = d.get("request_params", {})
        load = d.get("load_params", {})
        outcome = d.get("expected_outcome", {})

        distribution = None
        raw_dist = outcome.get("distribution")
        if raw_dist:
            distribution = {}
            for ver, w in raw_dist.items():
                if isinstance(w, str) and "approx" in w:
                    distribution[ver] = float(w.replace("approx", "").strip())
                else:
                    distribution[ver] = float(w)

        strategies = list(d.get("test_strategies", []))
        rl_expect = outcome.get("rate_limit")
        rl_expect = rl_expect if isinstance(rl_expect, dict) else None
        if rl_expect and "rate_limit" not in strategies:
            strategies.append("rate_limit")
        policy_types = [_strategy_to_policy(s) for s in strategies]

        if not policy_types:
            if distribution:
                policy_types = [PolicyType.TRAFFIC_SPLIT]
            elif outcome.get("destination"):
                policy_types = [PolicyType.ROUTING]

        expected_fault_code = None  # type: Optional[int]
        ofc = outcome.get("fault_code") if outcome.get("fault_code") is not None else outcome.get("expected_fault_code")
        if ofc is not None:
            try:
                expected_fault_code = int(ofc)
            except (TypeError, ValueError):
                expected_fault_code = None
        if expected_fault_code is None and (params.get("fault_type") or "").strip() == "abort":
            fs = params.get("fault_status")
            if fs is not None:
                try:
                    expected_fault_code = int(fs)
                except (TypeError, ValueError):
                    pass

        proto_raw = params.get("protocol") or (d.get("global_settings") or {}).get("default_protocol")
        grpc_method = (
            params.get("grpc_method")
            or params.get("method")
            or params.get("grpc_service_method")
            or ""
        )
        path_val = params.get("path", "")
        if not grpc_method and path_val:
            p = str(path_val).strip().lstrip("/")
            if p and "/" in p and "." in p.split("/", 1)[0]:
                grpc_method = p

        grpc_payload = params.get("grpc_data") or params.get("grpc_payload") or "{}"
        grpc_port = None
        if params.get("grpc_port") is not None:
            try:
                grpc_port = int(params["grpc_port"])
            except (TypeError, ValueError):
                grpc_port = None
        gp = params.get("grpc_plaintext", True)
        if isinstance(gp, str):
            grpc_plaintext = gp.strip().lower() not in ("0", "false", "no")
        else:
            grpc_plaintext = bool(gp)

        return cls(
            case_id=d.get("case_id", ""),
            name=d.get("case_id", ""),
            description=d.get("description", ""),
            test_type=TestType(d.get("type", "single_request")),
            policy_types=policy_types,
            protocol=Protocol.from_value(str(proto_raw or "")),
            target_url=ingress_url,
            host=params.get("host", ""),
            path=params.get("path", ""),
            headers=params.get("headers", {}),
            grpc_method=str(grpc_method or ""),
            grpc_payload=str(grpc_payload),
            grpc_port=grpc_port,
            grpc_plaintext=grpc_plaintext,
            request_count=load.get("num_requests", 1),
            concurrency=load.get("concurrency", 1),
            trigger_condition=params.get("trigger_condition"),
            fault_params={
                k: v for k, v in params.items()
                if k.startswith("fault_") or k in (
                    "inject_fault_to", "connection_pool_test",
                    "simulate_slow_response", "response_delay",
                )
            },
            expected_destination=outcome.get("destination"),
            expected_distribution=distribution,
            expected_success_rate=None,
            expected_fault_rate=None,
            expected_fault_code=expected_fault_code,
            expected_retry_attempts=None,
            expected_circuit_breaker_threshold=outcome.get("circuit_breaker_threshold"),
            margin_of_error=float(outcome.get("margin_of_error", 0.1)),
            test_strategies=strategies,
            source_service=d.get("source_service", ""),
            metadata=d,
            rate_limit_expect=rl_expect,
        )


@dataclass
class TestSuite:
    """测试套件 —— 一组 TestCase 加上全局配置。"""
    cases: List[TestCase] = field(default_factory=list)
    global_settings: Dict[str, Any] = field(default_factory=dict)

    @property
    def ingress_url(self) -> str:
        return self.global_settings.get("ingress_url", "")

    @classmethod
    def from_matrix_file(cls, path: str) -> "TestSuite":
        """从旧版 output_matrix.json 加载。"""
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        gs = data.get("global_settings", {})
        ingress = gs.get("ingress_url", "")
        cases = [
            TestCase.from_matrix_dict(tc, ingress)
            for tc in data.get("test_cases", [])
        ]
        return cls(cases=cases, global_settings=gs)


# ─── 各层的输出数据 ─────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Executor 层的输出。"""
    case_id: str
    status_codes: Dict[str, int] = field(default_factory=dict)
    total_requests: int = 0
    success_rate: float = 0.0
    avg_response_time: float = 0.0
    error_count: int = 0
    raw_output: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionResult:
    """Collector 层的输出。"""
    case_id: str
    envoy_logs: Dict[str, str] = field(default_factory=dict)
    prometheus_metrics: Dict[str, Any] = field(default_factory=dict)
    gateway_logs: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationDetail:
    """单项验证结果。"""
    dimension: str
    status: ValidationStatus
    message: str = ""
    expected: Any = None
    actual: Any = None
    deviation: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Validator 层的输出。"""
    case_id: str
    overall_status: ValidationStatus = ValidationStatus.SKIPPED
    details: List[ValidationDetail] = field(default_factory=list)
    summary: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.overall_status == ValidationStatus.PASSED


@dataclass
class PipelineResult:
    """单个用例的完整流水线结果。"""
    test_case: TestCase
    execution: Optional[ExecutionResult] = None
    collection: Optional[CollectionResult] = None
    validation: Optional[ValidationResult] = None
    # 单用例完整耗时（秒）：从错误注入开始到故障恢复结束
    case_duration_seconds: Optional[float] = None


# ─── 内部辅助 ────────────────────────────────────────────────────────────────

_STRATEGY_POLICY_MAP = {
    "routing": PolicyType.ROUTING,
    "traffic_split": PolicyType.TRAFFIC_SPLIT,
    "fault_injection": PolicyType.FAULT_INJECTION,
    "circuit_breaker": PolicyType.CIRCUIT_BREAKER,
    "retry": PolicyType.RETRY,
    "rate_limit": PolicyType.RATE_LIMIT,
    "connection_pool": PolicyType.CONNECTION_POOL,
    "connection_pool_outlier": PolicyType.CONNECTION_POOL_OUTLIER,
    "timeout": PolicyType.TIMEOUT,
    "orthogonal_matching": PolicyType.ORTHOGONAL_MATCHING,
    "delay_injection": PolicyType.FAULT_INJECTION,
}


def _strategy_to_policy(strategy: str) -> PolicyType:
    return _STRATEGY_POLICY_MAP.get(strategy, PolicyType.COMPOSITE)
