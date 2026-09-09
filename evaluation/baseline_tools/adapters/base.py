#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared helpers for baseline adapters (Python 3.6 compatible)."""
from __future__ import print_function

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None


def now_iso():
    return datetime.now().isoformat()


def load_yaml_mapping(path):
    if yaml is None:
        raise RuntimeError("PyYAML required")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def merge_yamls(paths):
    """Write concatenated YAML docs to a temp file; return path."""
    fd, tmp = tempfile.mkstemp(suffix=".yaml", prefix="baseline_")
    os.close(fd)
    with open(tmp, "w") as out:
        for p in paths:
            with open(p, "r") as inp:
                out.write(inp.read())
            if not out.tell() or True:
                out.write("\n---\n")
    return tmp


def run_cmd(cmd, timeout=90):
    """subprocess.run compatible with Python 3.6."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except OSError as e:
        return -2, "", str(e)


def which(name, fallbacks=None):
    fallbacks = fallbacks or []
    rc, out, _ = run_cmd(["bash", "-lc", "command -v {0}".format(name)])
    if rc == 0 and out.strip():
        return out.strip()
    for p in fallbacks:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def map_istioctl_message(text, code, mapping):
    """Prefer keyword rules; fall back to message codes (IST0101 is overloaded)."""
    cfg = mapping.get("istioctl", {})
    lower = (text or "").lower()
    for rule in cfg.get("keywords") or []:
        matches = rule.get("match") or []
        if matches and all(m.lower() in lower for m in matches):
            return rule.get("fault_type")
    codes = cfg.get("codes") or {}
    if code and code in codes:
        return codes[code]
    return cfg.get("default", "generic_config_error")


def empty_result(method, config_file):
    return {
        "method": method,
        "config_file": config_file,
        "detected_faults": [],
        "raw": {},
        "t_detect_sec": 0.0,
        "error": None,
        "available": True,
    }


def timed_detect(fn, *args, **kwargs):
    t0 = time.time()
    result = fn(*args, **kwargs)
    result["t_detect_sec"] = round(time.time() - t0, 4)
    return result
