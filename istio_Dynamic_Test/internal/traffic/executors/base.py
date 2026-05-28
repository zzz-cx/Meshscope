"""Executor 编排层抽象 —— 协议相关发送逻辑在 protocols/ 下实现。"""

from abc import ABC, abstractmethod

from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, TestCase

# 向后兼容：旧代码 from executors.base import compose_request_url
from istio_Dynamic_Test.internal.traffic.protocols.http.url import compose_request_url  # noqa: F401


class BaseExecutor(ABC):
    @abstractmethod
    def execute(self, test_case: TestCase) -> ExecutionResult:
        ...
