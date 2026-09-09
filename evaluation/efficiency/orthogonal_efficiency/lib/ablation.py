# -*- coding: utf-8 -*-
"""
Coverage ablation: fault detection rate before vs after orthogonal merging.

Fault set F = one seeded fault per exhaustive validation unit.
A fault is detected iff some executed case observes that unit.

Because orthogonal bundles retain all member observations, DR is preserved
when merges only combine independently observable effects.
"""

from typing import Any, Dict, List, Set


def build_fault_set(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    faults = []
    for u in units:
        faults.append(
            {
                "fault_id": "fault::{0}".format(u["unit_id"]),
                "target_unit": u["unit_id"],
                "effect_id": u["effect_id"],
                "service_index": u["service_index"],
                "strategy": u["strategy"],
            }
        )
    return faults


def detect_faults(
    faults: List[Dict[str, Any]], cases: List[Dict[str, Any]]
) -> Dict[str, Any]:
    observed = set()  # type: Set[str]
    for c in cases:
        for uid in c.get("observes") or []:
            observed.add(uid)

    detected = []
    missed = []
    for f in faults:
        if f["target_unit"] in observed:
            detected.append(f["fault_id"])
        else:
            missed.append(f["fault_id"])

    total = len(faults) or 1
    return {
        "total_faults": len(faults),
        "detected": len(detected),
        "missed": len(missed),
        "detection_rate_pct": round(100.0 * len(detected) / float(total), 2),
        "missed_faults": missed[:50],  # cap for report size
        "observed_units": len(observed),
    }


def ablation_compare(
    units: List[Dict[str, Any]],
    cases_before: List[Dict[str, Any]],
    cases_after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    faults = build_fault_set(units)
    before = detect_faults(faults, cases_before)
    after = detect_faults(faults, cases_after)
    delta = round(before["detection_rate_pct"] - after["detection_rate_pct"], 2)
    return {
        "fault_set_size": len(faults),
        "before_merge": before,
        "after_merge": after,
        "delta_detection_pct": delta,
        "coverage_preserved": delta <= 2.0,
        "principle": (
            "Orthogonal independence ensures merged effects remain separately "
            "observable in a shared execution; merging reduces apply/traffic "
            "cost without dropping per-effect assertions."
        ),
    }
