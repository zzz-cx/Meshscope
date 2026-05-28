"""
istio_Dynamic_Test —— Istio 动态验证流水线

公开 API::

    from istio_Dynamic_Test import DynamicTester
    from istio_Dynamic_Test.internal.validation import run_verification
"""

__version__ = "2.1.0"

from istio_Dynamic_Test.internal.pipeline import DynamicTester

__all__ = ["DynamicTester", "__version__"]
