# -*- coding: utf-8 -*-
"""Load Dynamic_Test TestCaseGenerator without importing package __init__ (avoids paramiko)."""

from __future__ import print_function

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

# lib/ -> orthogonal_efficiency -> efficiency -> evaluation -> istio_check
_ISTIO_CHECK_ROOT = Path(__file__).resolve().parents[4]
_GENERATOR_PATH = (
    _ISTIO_CHECK_ROOT
    / "istio_Dynamic_Test"
    / "internal"
    / "testcase"
    / "generators"
    / "test_case_generator.py"
)


def load_test_case_generator_class():
    path = str(_GENERATOR_PATH)
    if not os.path.isfile(path):
        alt = (
            _ISTIO_CHECK_ROOT
            / "istio_check"
            / "istio_Dynamic_Test"
            / "internal"
            / "testcase"
            / "generators"
            / "test_case_generator.py"
        )
        path = str(alt)
    spec = importlib.util.spec_from_file_location("meshscope_tcg_bridge", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.TestCaseGenerator


def generate_with_dynamic_test(
    istio_config: Dict[str, Any], orthogonal_minimize: bool
) -> List[Dict[str, Any]]:
    """Run Dynamic_Test generator on an in-memory istio_config dict."""
    TCG = load_test_case_generator_class()
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(istio_config, f)
        gen = TCG(tmp)
        ep = dict(istio_config.get("enabled_policies") or {})
        if orthogonal_minimize:
            ep["orthogonal_minimize"] = True
        else:
            ep.pop("orthogonal_minimize", None)
        gen.config["enabled_policies"] = ep
        return list(gen.generate() or [])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def dynamic_test_case_counts(istio_config: Dict[str, Any]) -> Tuple[int, int]:
    exh = len(generate_with_dynamic_test(istio_config, orthogonal_minimize=False))
    ortho = len(generate_with_dynamic_test(istio_config, orthogonal_minimize=True))
    return exh, ortho
