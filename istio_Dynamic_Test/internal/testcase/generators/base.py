"""Generator 层抽象基类。

所有测试用例生成器都应继承 BaseGenerator 并实现 generate() 方法。
扩展新功能（如限流、mTLS 等）时，只需新增一个 Generator 子类。
"""

from abc import ABC, abstractmethod
from typing import List

from istio_Dynamic_Test.internal.models.testcase import TestCase, TestSuite


class BaseGenerator(ABC):
    """测试用例生成器基类。"""

    @abstractmethod
    def generate(self) -> List[TestCase]:
        """生成测试用例列表。

        Returns:
            TestCase 对象的列表。
        """
        ...

    def generate_suite(self, ingress_url: str = "") -> TestSuite:
        """生成完整的测试套件（含全局配置）。"""
        cases = self.generate()
        return TestSuite(
            cases=cases,
            global_settings={"ingress_url": ingress_url},
        )
