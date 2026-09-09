# -*- coding: utf-8 -*-
"""
Effect-level case model aligned with Dynamic_Test orthogonal dimensions:

  match (如果) / action (什么) / scope (哪里) / trigger (何时)

Exhaustive: one validation case per (service, effect).
Orthogonal: pack independently observable effects into shared executions
(mirrors orthogonal_fault_bundle + per-dimension representatives).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from .config_synth import CONFIG_LEVELS

# effect_id -> metadata
# dims: which orthogonal dimensions this effect exercises
# conflicts: cannot share an execution with these effect_ids (same service)
EFFECT_DEFS = [
    # match / predicate
    {
        "effect_id": "pred_uri_route",
        "strategy": "routing",
        "dims": ("match",),
        "policies": ("routing",),
        "conflicts": (),
    },
    {
        "effect_id": "pred_header_user",
        "strategy": "routing",
        "dims": ("match",),
        "policies": ("routing",),
        "conflicts": (),
    },
    {
        "effect_id": "pred_header_role",
        "strategy": "routing",
        "dims": ("match",),
        "policies": ("routing",),
        "conflicts": (),
    },
    # actions
    {
        "effect_id": "action_routing_default",
        "strategy": "routing",
        "dims": ("action",),
        "policies": ("routing",),
        "conflicts": (),
    },
    {
        "effect_id": "action_traffic_split",
        "strategy": "traffic_split",
        "dims": ("action",),
        "policies": ("traffic_split",),
        "conflicts": (),
    },
    {
        "effect_id": "action_retry",
        "strategy": "retry",
        "dims": ("action", "trigger"),
        "policies": ("retry",),
        "conflicts": ("action_fault_abort",),
    },
    {
        "effect_id": "action_timeout",
        "strategy": "timeout",
        "dims": ("action", "trigger"),
        "policies": ("timeout",),
        "conflicts": ("action_fault_delay",),
    },
    {
        "effect_id": "action_fault_abort",
        "strategy": "fault_injection",
        "dims": ("action",),
        "policies": ("fault_injection",),
        "conflicts": ("action_retry",),
    },
    {
        "effect_id": "action_fault_delay",
        "strategy": "fault_injection",
        "dims": ("action", "trigger"),
        "policies": ("fault_injection",),
        "conflicts": ("action_timeout",),
    },
    {
        "effect_id": "action_rate_limit_pass",
        "strategy": "rate_limit",
        "dims": ("action",),
        "policies": ("rate_limit",),
        "conflicts": (),
    },
    {
        "effect_id": "action_rate_limit_burst",
        "strategy": "rate_limit",
        "dims": ("action", "trigger"),
        "policies": ("rate_limit",),
        "conflicts": (),
    },
    # scope
    {
        "effect_id": "scope_vs_local",
        "strategy": "routing",
        "dims": ("scope",),
        "policies": ("routing",),
        "conflicts": (),
    },
    {
        "effect_id": "scope_dr_global",
        "strategy": "circuit_breaker",
        "dims": ("scope",),
        "policies": ("circuit_breaker",),
        "conflicts": (),
    },
    {
        "effect_id": "scope_envoyfilter",
        "strategy": "rate_limit",
        "dims": ("scope",),
        "policies": ("rate_limit",),
        "conflicts": (),
    },
    # trigger / constraint
    {
        "effect_id": "trigger_load_pool",
        "strategy": "connection_pool",
        "dims": ("trigger",),
        "policies": ("connection_pool",),
        "conflicts": (),
    },
    {
        "effect_id": "trigger_outlier_window",
        "strategy": "connection_pool_outlier",
        "dims": ("trigger", "scope"),
        "policies": ("circuit_breaker",),
        "conflicts": (),
    },
    {
        "effect_id": "trigger_cb_eject",
        "strategy": "circuit_breaker",
        "dims": ("trigger", "action"),
        "policies": ("circuit_breaker",),
        "conflicts": (),
    },
    # C5 extras
    {
        "effect_id": "action_mirroring",
        "strategy": "mirroring",
        "dims": ("action",),
        "policies": ("mirroring",),
        "conflicts": (),
    },
    {
        "effect_id": "action_authz_deny",
        "strategy": "authorization",
        "dims": ("action", "match"),
        "policies": ("authorization",),
        "conflicts": (),
    },
    {
        "effect_id": "pred_authz_header",
        "strategy": "authorization",
        "dims": ("match",),
        "policies": ("authorization",),
        "conflicts": (),
    },
]


def effects_for_level(config_level: str) -> List[Dict[str, Any]]:
    policies = set(CONFIG_LEVELS[config_level]["policies"])
    out = []
    for e in EFFECT_DEFS:
        if all(p in policies for p in e["policies"]):
            out.append(e)
    return out


def build_exhaustive_units(n_services: int, config_level: str) -> List[Dict[str, Any]]:
    """One validation unit per (service, effect) — non-orthogonal baseline."""
    effects = effects_for_level(config_level)
    units = []
    for svc in range(1, n_services + 1):
        for e in effects:
            units.append(
                {
                    "unit_id": "s{0}:{1}".format(svc, e["effect_id"]),
                    "service_index": svc,
                    "effect_id": e["effect_id"],
                    "strategy": e["strategy"],
                    "dims": list(e["dims"]),
                    "conflicts": list(e["conflicts"]),
                    "path": "/s{0}/{1}/".format(svc, e["effect_id"]),
                }
            )
    return units


def _independent(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Independently observable in one shared execution?"""
    if a["service_index"] != b["service_index"]:
        # Cross-service: same as orthogonal_fault_bundle (different path prefixes).
        return True
    # Same service: conflict table + prefer different primary dims
    if a["effect_id"] in b.get("conflicts", []) or b["effect_id"] in a.get(
        "conflicts", []
    ):
        return False
    if a["effect_id"] == b["effect_id"]:
        return False
    # DestinationRule overlays on the same host must not share one apply
    # (Istio merges/overrides multiple DRs for one host → flaky at scale).
    dr_effects = {
        "scope_dr_global",
        "trigger_load_pool",
        "trigger_outlier_window",
        "trigger_cb_eject",
    }
    if a["effect_id"] in dr_effects and b["effect_id"] in dr_effects:
        return False
    da, db = set(a.get("dims") or []), set(b.get("dims") or [])
    # Allow merge when dimension sets are complementary or disjoint-primary
    if da.isdisjoint(db):
        return True
    # Same dim family (e.g. two match predicates): still ok if different paths
    if da == db and "match" in da:
        return True
    # Overlapping action dims: conservative no
    if "action" in da and "action" in db:
        return False
    return True


def orthogonal_merge_units(
    units: List[Dict[str, Any]], max_bundle_size: int = 4
) -> List[Dict[str, Any]]:
    """
    Pack exhaustive units into orthogonal shared executions.
    Each bundle remains able to observe every member effect (coverage-preserving merge).
    """
    max_b = max(2, int(max_bundle_size))
    bundles = []  # type: List[List[Dict[str, Any]]]

    # Stable order: by service then effect
    ordered = sorted(
        units, key=lambda u: (u["service_index"], u["effect_id"])
    )
    for u in ordered:
        placed = False
        for b in bundles:
            if len(b) >= max_b:
                continue
            if all(_independent(u, x) for x in b):
                b.append(u)
                placed = True
                break
        if not placed:
            bundles.append([u])

    merged = []
    for i, b in enumerate(bundles):
        merged.append(
            {
                "case_id": "ortho_bundle_{0:04d}".format(i + 1),
                "method": "orthogonal",
                "bundle_size": len(b),
                "unit_ids": [x["unit_id"] for x in b],
                "effects": [x["effect_id"] for x in b],
                "services": sorted({x["service_index"] for x in b}),
                "observes": [x["unit_id"] for x in b],
                "members": b,
            }
        )
    return merged


def exhaustive_cases(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cases = []
    for u in units:
        cases.append(
            {
                "case_id": "exh_{0}".format(u["unit_id"]),
                "method": "exhaustive",
                "bundle_size": 1,
                "unit_ids": [u["unit_id"]],
                "effects": [u["effect_id"]],
                "services": [u["service_index"]],
                "observes": [u["unit_id"]],
                "members": [u],
            }
        )
    return cases


def reduction_stats(exh_n: int, ortho_n: int) -> Dict[str, Any]:
    red = 0.0
    if exh_n > 0:
        red = 100.0 * (1.0 - float(ortho_n) / float(exh_n))
    return {
        "exhaustive_cases": exh_n,
        "orthogonal_cases": ortho_n,
        "reduction_pct": round(red, 2),
        "reduction_ratio": round(1.0 - float(ortho_n) / float(max(exh_n, 1)), 4),
    }
