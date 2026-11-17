"""Retired heuristic oracle; controlled obligations use behavior_profiles instead."""
from .controlled import ControlledProbeRequiredValidator


class ConnectionPoolOutlierValidator(ControlledProbeRequiredValidator):
    """Do not infer policy correctness from 503 totals or aggregate log counts."""
