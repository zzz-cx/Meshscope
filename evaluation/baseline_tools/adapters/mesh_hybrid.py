#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""H-Ours: static heuristics + dynamic oracle, confidence fusion."""
from __future__ import print_function

from .base import empty_result
from . import static_ours
from . import dynamic_adapters


def detect(config_file, mapping=None, cluster=False, **kwargs):
    result = empty_result("H-Ours", config_file)
    s = static_ours.detect(config_file, mapping)
    d = dynamic_adapters.detect_ours(
        config_file, mapping=mapping, cluster=cluster, **kwargs)

    # fusion: union by fault_type, take max confidence; boost if both agree
    by_type = {}
    for f in (s.get("detected_faults") or []):
        by_type[f["fault_type"]] = dict(f)
        by_type[f["fault_type"]]["details"] = dict(f.get("details") or {})
        by_type[f["fault_type"]]["details"]["sources"] = ["static"]

    for f in (d.get("detected_faults") or []):
        ft = f["fault_type"]
        if ft in by_type:
            by_type[ft]["confidence"] = min(
                0.99, max(by_type[ft].get("confidence", 0), f.get("confidence", 0)) + 0.05)
            src = by_type[ft]["details"].setdefault("sources", [])
            if "dynamic" not in src:
                src.append("dynamic")
            by_type[ft]["description"] = by_type[ft].get("description", "") + " | " + f.get("description", "")
        else:
            nf = dict(f)
            nf["details"] = dict(f.get("details") or {})
            nf["details"]["sources"] = ["dynamic"]
            by_type[ft] = nf

    result["detected_faults"] = list(by_type.values())
    result["raw"] = {
        "static": s.get("raw"),
        "dynamic": d.get("raw"),
        "static_faults": len(s.get("detected_faults") or []),
        "dynamic_faults": len(d.get("detected_faults") or []),
    }
    if s.get("error"):
        result["error"] = s.get("error")
    if d.get("error"):
        result["error"] = (result.get("error") or "") + ";" + str(d.get("error"))
    return result
