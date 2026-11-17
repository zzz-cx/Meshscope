"""CompositeValidator —— 根据 TestCase 的策略类型自动选择并组合多个 Validator。

这是 Validator 层的入口点，DynamicTester 只需调用 CompositeValidator，
它会根据 test_case.policy_types 自动委托给对应的子 Validator。
"""

from typing import Dict, List, Optional, Type

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    PolicyType,
    TestCase,
    ValidationResult,
    ValidationStatus,
)
from istio_Dynamic_Test.internal.validation.policies.base import BaseValidator
from istio_Dynamic_Test.internal.validation.policies.routing import RoutingValidator
from istio_Dynamic_Test.internal.validation.policies.traffic_split import TrafficSplitValidator
from istio_Dynamic_Test.internal.validation.policies.circuit_breaker import CircuitBreakerValidator
from istio_Dynamic_Test.internal.validation.policies.connection_pool import ConnectionPoolValidator
from istio_Dynamic_Test.internal.validation.policies.connection_pool_outlier import (
    ConnectionPoolOutlierValidator,
)
from istio_Dynamic_Test.internal.validation.policies.retry import RetryValidator
from istio_Dynamic_Test.internal.validation.policies.fault_injection import FaultInjectionValidator
from istio_Dynamic_Test.internal.validation.policies.rate_limit import RateLimitValidator
from istio_Dynamic_Test.internal.validation.policies.timeout import TimeoutValidator


# 策略 → Validator 映射
_VALIDATOR_REGISTRY: Dict[PolicyType, Type[BaseValidator]] = {
    PolicyType.ROUTING: RoutingValidator,
    PolicyType.TRAFFIC_SPLIT: TrafficSplitValidator,
    PolicyType.CIRCUIT_BREAKER: CircuitBreakerValidator,
    PolicyType.CONNECTION_POOL: ConnectionPoolValidator,
    PolicyType.CONNECTION_POOL_OUTLIER: ConnectionPoolOutlierValidator,
    PolicyType.RETRY: RetryValidator,
    PolicyType.FAULT_INJECTION: FaultInjectionValidator,
    PolicyType.RATE_LIMIT: RateLimitValidator,
    PolicyType.TIMEOUT: TimeoutValidator,
}


class CompositeValidator(BaseValidator):
    """组合验证器 —— 自动根据策略类型分发验证任务。

    支持一个 TestCase 同时验证多种策略（正交组合）。
    """

    def __init__(
        self,
        extra_validators: Optional[Dict[PolicyType, BaseValidator]] = None,
        prometheus_url: Optional[str] = None,
        ingress_url: Optional[str] = None,
        namespace: str = "default",
    ):
        self._instances: Dict[PolicyType, BaseValidator] = {}
        self._prometheus_url = prometheus_url
        self._ingress_url = ingress_url
        self._namespace = namespace
        if extra_validators:
            self._instances.update(extra_validators)

    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        policies = test_case.policy_types
        if not policies:
            policies = [PolicyType.ROUTING]

        all_details = []
        sub_results: List[ValidationResult] = []

        for policy in policies:
            validator = self._get_validator(policy)
            if validator is None:
                continue
            result = validator.validate(test_case, execution, collection)
            sub_results.append(result)
            for d in result.details:
                d.dimension = f"[{policy.value}] {d.dimension}"
                all_details.append(d)

        overall = self._merge_status(sub_results)
        summaries = [r.summary for r in sub_results if r.summary]

        return ValidationResult(
            case_id=test_case.case_id,
            overall_status=overall,
            details=all_details,
            summary=" | ".join(summaries) if summaries else "无验证结果",
        )

    def _get_validator(self, policy: PolicyType) -> Optional[BaseValidator]:
        if policy in self._instances:
            return self._instances[policy]
        cls = _VALIDATOR_REGISTRY.get(policy)
        if cls is None:
            return None
        # TrafficSplitValidator 需要 prometheus_url/ingress_url
        if policy == PolicyType.TRAFFIC_SPLIT and cls is TrafficSplitValidator:
            instance = cls(
                prometheus_url=self._prometheus_url,
                ingress_url=self._ingress_url,
                namespace=self._namespace,
            )
        # CircuitBreakerValidator 可选 Prometheus 交叉验证
        elif policy == PolicyType.CIRCUIT_BREAKER and cls is CircuitBreakerValidator:
            instance = cls(
                prometheus_url=self._prometheus_url,
                namespace=self._namespace,
            )
        elif policy == PolicyType.CONNECTION_POOL_OUTLIER and cls is ConnectionPoolOutlierValidator:
            instance = cls()
        elif policy == PolicyType.RATE_LIMIT and cls is RateLimitValidator:
            instance = cls(
                prometheus_url=self._prometheus_url,
                namespace=self._namespace,
            )
        elif policy == PolicyType.TIMEOUT and cls is TimeoutValidator:
            instance = cls(
                prometheus_url=self._prometheus_url,
                namespace=self._namespace,
            )
        else:
            instance = cls()
        self._instances[policy] = instance
        return instance

    @staticmethod
    def _merge_status(results: List[ValidationResult]) -> ValidationStatus:
        """严格模式：所有子验证器都通过才算通过，任一 FAILED 则整体 FAILED。"""
        if not results:
            return ValidationStatus.SKIPPED
        if any(r.overall_status == ValidationStatus.FAILED for r in results):
            return ValidationStatus.FAILED
        if any(r.overall_status in (ValidationStatus.INCONCLUSIVE, ValidationStatus.SKIPPED) for r in results):
            return ValidationStatus.INCONCLUSIVE
        if any(r.overall_status == ValidationStatus.WARNING for r in results):
            return ValidationStatus.WARNING
        return ValidationStatus.PASSED
