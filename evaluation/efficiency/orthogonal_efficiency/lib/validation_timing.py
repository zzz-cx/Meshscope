# -*- coding: utf-8 -*-
"""
Complete validation-time model (Dynamic_Test pipeline style):

  apply fault/config → send traffic → collect telemetry → assert → clear

Exhaustive: pay apply+clear per case.
Orthogonal bundle: one apply/clear for the bundle; traffic+assert per member
(same accounting as orthogonal_fault_bundle).
"""

from __future__ import print_function

import random
from typing import Any, Dict, List, Optional

# Baseline seconds calibrated to typical Dynamic_Test stage costs on a local cluster.
APPLY_S = 0.85
CLEAR_S = 0.55
TELEMETRY_S = 0.12
ASSERT_S = 0.05
REQUEST_S = 0.035

# Extra requests / overhead by strategy (complete effect validation, not a single curl).
STRATEGY_TRAFFIC = {
    "routing": {"requests": 3, "extra_s": 0.05},
    "traffic_split": {"requests": 40, "extra_s": 0.25},
    "retry": {"requests": 8, "extra_s": 0.40},
    "timeout": {"requests": 4, "extra_s": 0.35},
    "fault_injection": {"requests": 6, "extra_s": 0.20},
    "rate_limit": {"requests": 30, "extra_s": 0.45},
    "circuit_breaker": {"requests": 25, "extra_s": 0.60},
    "connection_pool": {"requests": 20, "extra_s": 0.35},
    "connection_pool_outlier": {"requests": 25, "extra_s": 0.55},
    "mirroring": {"requests": 10, "extra_s": 0.20},
    "authorization": {"requests": 4, "extra_s": 0.10},
}


def _jitter(rng, base, sigma_frac=0.08):
    # type: (random.Random, float, float) -> float
    if base <= 0:
        return 0.0
    return max(0.0, rng.gauss(base, base * sigma_frac))


def unit_traffic_cost(unit, rng):
    # type: (Dict[str, Any], random.Random) -> float
    strat = unit.get("strategy") or "routing"
    spec = STRATEGY_TRAFFIC.get(strat, {"requests": 5, "extra_s": 0.1})
    req_t = spec["requests"] * _jitter(rng, REQUEST_S)
    extra = _jitter(rng, spec["extra_s"])
    telem = _jitter(rng, TELEMETRY_S)
    assert_t = _jitter(rng, ASSERT_S)
    return req_t + extra + telem + assert_t


def case_validation_time(case, rng):
    # type: (Dict[str, Any], random.Random) -> float
    """Wall-clock seconds for one complete validation execution unit."""
    members = case.get("members") or []
    apply_t = _jitter(rng, APPLY_S)
    clear_t = _jitter(rng, CLEAR_S)
    traffic = 0.0
    for m in members:
        traffic += unit_traffic_cost(m, rng)
    # Bundled multi-match inject has a small coordination overhead
    bundle_n = max(int(case.get("bundle_size") or len(members) or 1), 1)
    coord = _jitter(rng, 0.04 * max(bundle_n - 1, 0))
    return apply_t + traffic + clear_t + coord


def suite_validation_time(cases, seed):
    # type: (List[Dict[str, Any]], int) -> Dict[str, Any]
    """
    Full suite validation time = sum of per-case complete pipeline times
    (sequential Dynamic_Test style; no cross-case parallelism).
    """
    rng = random.Random(seed)
    per_case = []
    total = 0.0
    for c in cases:
        t = case_validation_time(c, rng)
        per_case.append({"case_id": c.get("case_id"), "validation_s": round(t, 4)})
        total += t
    return {
        "total_validation_s": round(total, 3),
        "num_cases": len(cases),
        "mean_case_s": round(total / float(max(len(cases), 1)), 4),
        "per_case": per_case,
    }


def mean_std(values):
    # type: (List[float]) -> Dict[str, float]
    n = len(values) or 1
    mu = sum(values) / float(n)
    if len(values) <= 1:
        return {"mean": round(mu, 3), "std": 0.0, "min": round(mu, 3), "max": round(mu, 3)}
    var = sum((x - mu) ** 2 for x in values) / float(len(values) - 1)
    std = var ** 0.5
    return {
        "mean": round(mu, 3),
        "std": round(std, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }
