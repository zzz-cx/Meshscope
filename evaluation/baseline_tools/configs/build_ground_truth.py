#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build extended ground_truth for baseline experiment."""
from __future__ import print_function

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ACC_GT = os.path.join(
    HERE, "..", "..", "accuracy", "experiments", "configs", "ground_truth.json"
)
OUT = os.path.join(HERE, "ground_truth.json")


def detectability_from_expected(sample):
    if not sample.get("has_fault"):
        return "none"
    ed = sample.get("expected_detection") or {}
    s = bool(ed.get("static_detection"))
    d = bool(ed.get("dynamic_detection"))
    if s and d:
        return "both"
    if s and not d:
        return "static_only"
    if d and not s:
        return "dynamic_only"
    return "both"


def main():
    with open(ACC_GT, "r") as f:
        gt = json.load(f)

    samples = gt.get("samples") or {}
    for k, v in samples.items():
        v["detectability"] = detectability_from_expected(v)

    # Reclassify timeout_mut as both (static can see short timeout)
    # Add L-Dynamic samples
    extra = {
        "dynamic_only/aggressive_outlier.yaml": {
            "has_fault": True,
            "fault_type": "circuit_breaker_error",
            "severity": "high",
            "description": "OutlierDetection consecutive5xx=1 ejects healthy pods under transient errors",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.85,
            },
            "fault_details": {"consecutive5xxErrors": 1, "maxConnections": 1},
        },
        "dynamic_only/retry_storm.yaml": {
            "has_fault": True,
            "fault_type": "retry_policy_error",
            "severity": "medium",
            "description": "Excessive retries with short perTryTimeout amplify load",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.8,
            },
            "fault_details": {"attempts": 10, "perTryTimeout": "100ms"},
        },
        "dynamic_only/tiny_timeout.yaml": {
            "has_fault": True,
            "fault_type": "timeout_error",
            "severity": "high",
            "description": "1ms timeout causes runtime request failures",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.9,
            },
            "fault_details": {"timeout": "1ms"},
        },
        "dynamic_only/always_abort.yaml": {
            "has_fault": True,
            "fault_type": "fault_injection_error",
            "severity": "high",
            "description": "100% abort fault — schema-valid but always fails at runtime",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.95,
            },
            "fault_details": {"abort_percent": 100},
        },
        "dynamic_only/skewed_split.yaml": {
            "has_fault": True,
            "fault_type": "weight_error",
            "severity": "medium",
            "description": "Valid 99/1 weights contradict declared 50/50 canary intent",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.85,
            },
            "fault_details": {"weights": [99, 1], "intent": "50/50"},
        },
        "dynamic_only/tiny_pool.yaml": {
            "has_fault": True,
            "fault_type": "circuit_breaker_error",
            "severity": "medium",
            "description": "maxConnections=1 exhausts under concurrent load",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.8,
            },
            "fault_details": {"maxConnections": 1},
        },
        "dynamic_only/tiny_ratelimit.yaml": {
            "has_fault": True,
            "fault_type": "rate_limit_error",
            "severity": "high",
            "description": "Local rate limit token bucket size 1 starves normal traffic",
            "detectability": "dynamic_only",
            "expected_detection": {
                "static_detection": False,
                "dynamic_detection": True,
                "detection_confidence": 0.85,
            },
            "fault_details": {"max_tokens": 1, "fill_interval": "60s"},
        },
    }
    samples.update(extra)

    # Note: S-Ours may still catch some L-Dynamic via heuristics; GT marks expected static=false
    # for istioctl-native expectation. Scoring still uses type match.

    stats = {
        "total_samples": len(samples),
        "detectability": {},
        "fault_types": {},
    }
    for v in samples.values():
        det = v.get("detectability", "unknown")
        stats["detectability"][det] = stats["detectability"].get(det, 0) + 1
        ft = v.get("fault_type", "")
        stats["fault_types"][ft] = stats["fault_types"].get(ft, 0) + 1

    out = {
        "metadata": {
            "version": "baseline-1.0",
            "description": "Baseline GT with detectability stratification + L-Dynamic samples",
            "source": "accuracy/experiments/configs/ground_truth.json + dynamic_only/*",
        },
        "samples": samples,
        "statistics": stats,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)
        f.write("\n")
    print("Wrote {0} samples -> {1}".format(len(samples), OUT))
    print("detectability:", stats["detectability"])


if __name__ == "__main__":
    main()
