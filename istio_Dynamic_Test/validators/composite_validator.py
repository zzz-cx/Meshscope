"""CompositeValidator —— 根据 TestCase 的策略类型自动选择并组合多个 Validator。

这是 Validator 层的入口点，DynamicTester 只需调用 CompositeValidator，
它会根据 test_case.policy_types 自动委托给对应的子 Validator。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from istio_Dynamic_Test.models.test_case import (
    CollectionResult,
    ExecutionResult,
    PolicyType,
    TestCase,
    ValidationResult,
    ValidationStatus,
)
from .base import BaseValidator
from .routing_validator import RoutingValidator
from .traffic_split_validator import TrafficSplitValidator
from .circuit_breaker_validator import CircuitBreakerValidator
from .retry_validator import RetryValidator
from .fault_injection_validator import FaultInjectionValidator


# 策略 → Validator 映射
_VALIDATOR_REGISTRY: Dict[PolicyType, Type[BaseValidator]] = {
    PolicyType.ROUTING: RoutingValidator,
    PolicyType.TRAFFIC_SPLIT: TrafficSplitValidator,
    PolicyType.CIRCUIT_BREAKER: CircuitBreakerValidator,
    PolicyType.RETRY: RetryValidator,
    PolicyType.FAULT_INJECTION: FaultInjectionValidator,
}


class CompositeValidator(BaseValidator):
    """组合验证器 —— 自动根据策略类型分发验证任务。

    支持一个 TestCase 同时验证多种策略（正交组合）。
    """

    def __init__(self, extra_validators: Optional[Dict[PolicyType, BaseValidator]] = None):
        self._instances: Dict[PolicyType, BaseValidator] = {}
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
        instance = cls()
        self._instances[policy] = instance
        return instance

    @staticmethod
    def _merge_status(results: List[ValidationResult]) -> ValidationStatus:
        if not results:
            return ValidationStatus.SKIPPED
        if any(r.overall_status == ValidationStatus.PASSED for r in results):
            return ValidationStatus.PASSED
        if any(r.overall_status == ValidationStatus.WARNING for r in results):
            return ValidationStatus.WARNING
        return ValidationStatus.FAILED
