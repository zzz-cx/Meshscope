"""Validator 层抽象基类。

每种 Istio 策略（路由 / 分流 / 熔断 / 重试 / 故障注入等）都有独立的
Validator 子类，负责将 Executor + Collector 的输出与 TestCase 中的期望进行对比。

新增功能时只需实现一个新的 Validator 子类。
"""

from abc import ABC, abstractmethod
from typing import Optional

from istio_Dynamic_Test.models.test_case import (
    CollectionResult,
    ExecutionResult,
    TestCase,
    ValidationResult,
)


class BaseValidator(ABC):
    """验证器基类。"""

    @abstractmethod
    def validate(
        self,
        test_case: TestCase,
        execution: Optional[ExecutionResult] = None,
        collection: Optional[CollectionResult] = None,
    ) -> ValidationResult:
        """验证测试用例的执行结果是否符合期望。

        Args:
            test_case: 测试用例（包含期望行为）。
            execution: Executor 层输出。
            collection: Collector 层输出。

        Returns:
            ValidationResult 对象。
        """
        ...
