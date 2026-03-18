"""
istio_Dynamic_Test —— Istio 动态验证框架
=========================================

四层流水线架构::

    Generator → Executor → Collector → Validator

快速开始::

    from istio_Dynamic_Test.main import DynamicTester
    from istio_Dynamic_Test.generators import ConfigGenerator
    from istio_Dynamic_Test.executors import HttpExecutor, LoadExecutor
    from istio_Dynamic_Test.collectors import EnvoyCollector
    from istio_Dynamic_Test.validators import CompositeValidator

    tester = DynamicTester(
        generator=ConfigGenerator("istio_config.json", ingress_url="http://..."),
        collector=EnvoyCollector(namespace="default"),
        validator=CompositeValidator(),
    )
    results = tester.run()

或通过 CLI::

    python -m istio_Dynamic_Test.main -i istio_config.json --ingress-url http://...
"""

__version__ = "2.0.0"
