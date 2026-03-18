"""Executor 层抽象基类。

Executor 负责根据 TestCase 发送请求并收集原始 HTTP 结果。
不同的执行策略（单次请求 / 负载测试 / 并发压测）实现不同的子类。
"""

from abc import ABC, abstractmethod

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase


class BaseExecutor(ABC):
    """测试执行器基类。"""

    @abstractmethod
    def execute(self, test_case: TestCase) -> ExecutionResult:
        """执行一个测试用例并返回执行结果。

        Args:
            test_case: 待执行的测试用例。

        Returns:
            ExecutionResult 对象。
        """
        ...
