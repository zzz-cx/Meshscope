"""Executor 层抽象基类。

Executor 负责根据 TestCase 发送请求并收集原始 HTTP 结果。
不同的执行策略（单次请求 / 负载测试 / 并发压测）实现不同的子类。
"""

from abc import ABC, abstractmethod

from istio_Dynamic_Test.models.test_case import ExecutionResult, TestCase


def compose_request_url(target_url: str, path: str) -> str:
    """合并 CLI 传入的 ingress 基础 URL 与用例中的 path。

    若用户在 ``--ingress-url`` 中已写出完整路径（如 ``http://ip/productpage``），
    而生成器又为 VS 匹配追加了 ``path=/productpage``，直接拼接会得到
    ``/productpage/productpage`` 导致 404。此时检测到 base 已以 path 结尾则不再重复拼接。
    """
    base = (target_url or "").rstrip("/")
    p = (path or "").strip()
    if not p or p == "/":
        return base if base else "/"
    if not p.startswith("/"):
        p = "/" + p
    if not base:
        return p
    if base.endswith(p):
        return base
    return f"{base}{p}"


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
