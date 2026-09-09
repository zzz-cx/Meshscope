#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S-Istio: istioctl analyze (offline / cluster-aware)."""
from __future__ import print_function

import json
import os
import re

from .base import (
    empty_result,
    map_istioctl_message,
    merge_yamls,
    now_iso,
    run_cmd,
    which,
)

ISTIOCTL_FALLBACKS = [
    "/root/configPilot/cluster/istio-1.24.6/bin/istioctl",
    "/usr/local/bin/istioctl",
]


def _parse_messages(stdout, stderr):
    messages = []
    text = stdout or ""
    # JSON array
    try:
        data = json.loads(text) if text.strip().startswith("[") or text.strip().startswith("{") else None
        if isinstance(data, list):
            for m in data:
                messages.append({
                    "level": m.get("level") or m.get("severity") or "",
                    "code": m.get("code") or m.get("type", {}).get("code") if isinstance(m.get("type"), dict) else m.get("code", ""),
                    "message": m.get("message") or m.get("detail") or str(m),
                    "origin": m,
                })
            return messages
        if isinstance(data, dict):
            for m in data.get("messages") or data.get("analyzerErrors") or []:
                messages.append({
                    "level": m.get("level", ""),
                    "code": m.get("code", ""),
                    "message": m.get("message", ""),
                    "origin": m,
                })
            return messages
    except Exception:
        pass

    # Text lines: Error [IST0101] (...)
    for line in (text + "\n" + (stderr or "")).splitlines():
        line = line.strip()
        if not line:
            continue
        if "No validation issues found" in line:
            continue
        m = re.search(r"\[(IST\d+)\]", line)
        code = m.group(1) if m else ""
        level = "Error" if line.lower().startswith("error") else (
            "Warning" if line.lower().startswith("warning") else "Info"
        )
        if code or "error" in line.lower() or "warning" in line.lower():
            messages.append({
                "level": level,
                "code": code,
                "message": line,
                "origin": line,
            })
    return messages


def detect(config_file, mapping, mode="offline", istioctl_path=None):
    """
    mode: offline (--use-kube=false) | cluster (default analyze against kube)
    """
    method = "S-Istio-offline" if mode == "offline" else "S-Istio-cluster"
    result = empty_result(method, config_file)
    path = istioctl_path or which("istioctl", ISTIOCTL_FALLBACKS)
    if not path:
        result["available"] = False
        result["error"] = "istioctl not found"
        return result

    tmp = merge_yamls([config_file])
    try:
        cmd = [path, "analyze", tmp, "-o", "json"]
        if mode == "offline":
            cmd.append("--use-kube=false")
        rc, out, err = run_cmd(cmd, timeout=90)
        result["raw"] = {
            "returncode": rc,
            "stdout": out[:8000],
            "stderr": err[:2000],
            "mode": mode,
            "istioctl": path,
        }
        messages = _parse_messages(out, err)
        # Some versions print human text even with -o json when empty
        if not messages and rc != 0:
            messages = _parse_messages(err, "")

        faults = []
        for msg in messages:
            ft = map_istioctl_message(msg.get("message", ""), msg.get("code", ""), mapping)
            conf = 0.9 if str(msg.get("level", "")).lower().startswith("error") else 0.75
            faults.append({
                "config_file": config_file,
                "fault_type": ft,
                "confidence": conf,
                "description": msg.get("message", ""),
                "details": {
                    "tool": "istioctl",
                    "code": msg.get("code", ""),
                    "level": msg.get("level", ""),
                    "mode": mode,
                },
                "detection_time": now_iso(),
            })
        result["detected_faults"] = faults
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    return result
