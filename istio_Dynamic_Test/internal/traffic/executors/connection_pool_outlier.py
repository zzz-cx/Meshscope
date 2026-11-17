"""The old VS-abort outlier simulation is intentionally disabled.

Use the controlled pool profile for connection-pool overflow. Instance ejection
requires endpoint-level stimuli and ejection/recovery evidence, not HTTP totals.
"""
from .base import BaseExecutor


class ConnectionPoolOutlierExecutor(BaseExecutor):
    def __init__(self, ssh_client=None, namespace="default"):
        self._namespace = namespace

    def execute(self, test_case):
        raise RuntimeError("VS fault injection cannot validate outlier detection; use controlled profiles")

    def execute_phase1_clear(self, test_case):
        return self.execute(test_case)

    def execute_phase2_recovery(self, pending):
        raise RuntimeError("No endpoint ejection evidence adapter is configured")
