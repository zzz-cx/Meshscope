"""CLI 兼容入口，请优先使用: python -m istio_Dynamic_Test.cmd"""

from istio_Dynamic_Test.internal.pipeline.cli import DynamicTester, main

__all__ = ["DynamicTester", "main"]

if __name__ == "__main__":
    main()
