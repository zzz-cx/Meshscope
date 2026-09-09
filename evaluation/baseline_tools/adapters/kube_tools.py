#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S-Lint / S-Schema adapters (skip gracefully if binary missing)."""
from __future__ import print_function

import json
import os

from .base import empty_result, merge_yamls, now_iso, run_cmd, which


def detect_kube_linter(config_file, mapping):
    result = empty_result("S-Lint", config_file)
    path = which("kube-linter")
    if not path:
        result["available"] = False
        result["error"] = "kube-linter not installed"
        return result
    tmp = merge_yamls([config_file])
    try:
        rc, out, err = run_cmd([path, "lint", tmp, "--format", "json"], timeout=60)
        result["raw"] = {"returncode": rc, "stdout": out[:4000], "stderr": err[:1000]}
        violations = []
        try:
            data = json.loads(out) if out.strip() else {}
            violations = data.get("Reports") or data.get("violations") or []
            if isinstance(data, list):
                violations = data
        except Exception:
            if out.strip():
                violations = [{"message": out.strip()[:500]}]
        default_ft = (mapping.get("kube_linter") or {}).get("default", "generic_config_error")
        faults = []
        for v in violations:
            msg = ""
            if isinstance(v, dict):
                msg = v.get("message") or v.get("Diagnostic", {}).get("Message", "") or str(v)
            else:
                msg = str(v)
            ft = default_ft
            lower = msg.lower()
            for rule in (mapping.get("kube_linter") or {}).get("keywords") or []:
                if all(m in lower for m in (rule.get("match") or [])):
                    ft = rule.get("fault_type", ft)
                    break
            faults.append({
                "config_file": config_file,
                "fault_type": ft,
                "confidence": 0.8,
                "description": msg,
                "details": {"tool": "kube-linter"},
                "detection_time": now_iso(),
            })
        result["detected_faults"] = faults
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return result


def detect_kubeval(config_file, mapping):
    result = empty_result("S-Schema", config_file)
    path = which("kubeval") or which("kubeconform")
    tool = "kubeval" if which("kubeval") else ("kubeconform" if which("kubeconform") else None)
    if not path:
        result["available"] = False
        result["error"] = "kubeval/kubeconform not installed"
        return result
    tmp = merge_yamls([config_file])
    try:
        if tool == "kubeconform":
            cmd = [path, "-output", "json", tmp]
        else:
            cmd = [path, tmp, "--output", "json"]
        rc, out, err = run_cmd(cmd, timeout=60)
        result["raw"] = {"returncode": rc, "stdout": out[:4000], "stderr": err[:1000], "tool": tool}
        default_ft = (mapping.get("kubeval") or {}).get("default", "schema_validation_error")
        faults = []
        # Any non-zero or error text → schema fault
        if rc != 0 or "error" in (out + err).lower():
            faults.append({
                "config_file": config_file,
                "fault_type": default_ft,
                "confidence": 0.85,
                "description": (out or err)[:500],
                "details": {"tool": tool},
                "detection_time": now_iso(),
            })
        result["detected_faults"] = faults
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return result
