"""Collector 层抽象基类。

Collector 负责在 Executor 执行完毕后，收集各类观测数据
（Envoy access log / Prometheus metric / Jaeger trace 等）。
"""

from abc import ABC, abstractmethod

from istio_Dynamic_Test.models.test_case import CollectionResult, TestCase


class BaseCollector(ABC):
    """数据采集器基类。"""

    @abstractmethod
    def collect(self, test_case: TestCase) -> CollectionResult:
        """为指定测试用例采集数据。

        Args:
            test_case: 对应的测试用例。

        Returns:
            CollectionResult 对象。
        """
        ...
