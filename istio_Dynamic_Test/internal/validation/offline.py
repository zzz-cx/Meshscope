"""离线验证：基于已采集 Envoy 日志与执行结果，不重复发流量。"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from istio_Dynamic_Test.internal.models.testcase import (
    CollectionResult,
    ExecutionResult,
    PipelineResult,
    TestSuite,
)
from istio_Dynamic_Test.internal.validation.composite import CompositeValidator
from istio_Dynamic_Test.internal.validation.report import ReportGenerator


def _load_execution_result(case_id: str, results_dir: str) -> Optional[ExecutionResult]:
    if not results_dir or not os.path.isdir(results_dir):
        return None
    patterns = [
        os.path.join(results_dir, f"{case_id}_*_result_*.json"),
        os.path.join(results_dir, f"{case_id}_http_result*.json"),
    ]
    files: List[str] = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    files = sorted(files, key=os.path.getmtime, reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as f:
        data = json.load(f)
    hr = data.get("http_result") or {}
    if not hr and "status_codes" in data:
        hr = data
    return ExecutionResult(
        case_id=case_id,
        status_codes=hr.get("status_codes", {}),
        total_requests=hr.get("total_requests", 0),
        success_rate=hr.get("success_rate", 0.0),
        avg_response_time=hr.get("avg_response_time", 0.0),
        error_count=hr.get("error_count", 0),
    )


def _load_envoy_logs_for_case(case_id: str, log_dir: str) -> Dict[str, str]:
    logs: Dict[str, str] = {}
    if not log_dir or not os.path.isdir(log_dir):
        return logs
    for path in glob.glob(os.path.join(log_dir, f"{case_id}_*.log")):
        pod = os.path.basename(path).replace(f"{case_id}_", "", 1).replace(".log", "")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                logs[pod] = f.read()
        except OSError:
            continue
    return logs


def run_verification(
    matrix_file: str,
    log_dir: str,
    output_dir: Optional[str] = None,
    istio_config_file: Optional[str] = None,
    http_results_dir: Optional[str] = None,
) -> Dict[str, Any]:
    _ = istio_config_file
    suite = TestSuite.from_matrix_file(matrix_file)
    out_dir = output_dir or os.path.join("results", "verification")
    os.makedirs(out_dir, exist_ok=True)
    http_dir = http_results_dir or os.path.join("results", "http_results")

    validator = CompositeValidator()
    pipeline_results: List[PipelineResult] = []

    for tc in suite.cases:
        execution = _load_execution_result(tc.case_id, http_dir)
        collection = CollectionResult(
            case_id=tc.case_id,
            envoy_logs=_load_envoy_logs_for_case(tc.case_id, log_dir),
        )
        validation = validator.validate(tc, execution, collection)
        pipeline_results.append(
            PipelineResult(
                test_case=tc,
                execution=execution,
                collection=collection,
                validation=validation,
            )
        )

    paths = ReportGenerator(out_dir).generate(
        pipeline_results, title="istio_verification"
    )
    return {
        "output_dir": out_dir,
        "report_paths": paths,
        "case_count": len(pipeline_results),
        "timestamp": datetime.now().isoformat(),
    }


def analyze_single_case(
    case_id: str,
    matrix_file: str,
    log_dir: str,
    http_results_dir: Optional[str] = None,
) -> Dict[str, Any]:
    suite = TestSuite.from_matrix_file(matrix_file)
    tc = next((c for c in suite.cases if c.case_id == case_id), None)
    if not tc:
        raise ValueError(f"未找到用例: {case_id}")
    http_dir = http_results_dir or os.path.join("results", "http_results")
    execution = _load_execution_result(case_id, http_dir)
    collection = CollectionResult(
        case_id=case_id,
        envoy_logs=_load_envoy_logs_for_case(case_id, log_dir),
    )
    validation = CompositeValidator().validate(tc, execution, collection)
    return {
        "case_id": case_id,
        "validation": validation,
        "execution": execution,
        "collection": collection,
    }
