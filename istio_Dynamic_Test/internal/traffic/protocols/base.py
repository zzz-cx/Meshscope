"""协议层抽象 —— 各协议实现发送与结果落盘。"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from istio_Dynamic_Test.internal.models.testcase import ExecutionResult, TestCase
    from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient


class ProtocolTrafficClient(ABC):
    """在远程/本地执行协议流量的客户端。"""

    @abstractmethod
    def execute(self, test_case: "TestCase") -> "ExecutionResult":
        ...
