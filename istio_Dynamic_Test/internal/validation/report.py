"""ReportGenerator —— 生成验证报告。

复用原有 verifier/report_generator.py 的逻辑，并新增从
ValidationResult 列表直接生成摘要的能力。
"""

import json
import os
from datetime import datetime
from typing import Dict, List

from istio_Dynamic_Test.internal.models.testcase import PipelineResult, ValidationStatus


class ReportGenerator:
    """报告生成器。

    Args:
        output_dir: 报告输出目录。
    """

    def __init__(self, output_dir: str = "results/reports"):
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, results: List[PipelineResult], title: str = "dynamic_test") -> Dict[str, str]:
        """从 PipelineResult 列表生成 JSON + 文本摘要报告。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON 报告
        json_path = os.path.join(self._output_dir, f"{title}_{timestamp}.json")
        report_data = self._build_json(results)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # 文本摘要
        txt_path = os.path.join(self._output_dir, f"{title}_{timestamp}.txt")
        summary = self._build_text(results)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(summary)

        print(f"  [REPORT] JSON -> {json_path}")
        print(f"  [REPORT] TXT  -> {txt_path}")
        return {"json": json_path, "txt": txt_path}

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_json(results: List[PipelineResult]) -> dict:
        cases = []
        for r in results:
            entry: dict = {
                "case_id": r.test_case.case_id,
                "description": r.test_case.description,
                "policy_types": [p.value for p in r.test_case.policy_types],
            }
            if r.case_duration_seconds is not None:
                entry["case_duration_seconds"] = r.case_duration_seconds
            if r.execution:
                entry["execution"] = {
                    "status_codes": r.execution.status_codes,
                    "total_requests": r.execution.total_requests,
                    "success_rate": r.execution.success_rate,
                    "avg_response_time": r.execution.avg_response_time,
                    "metadata": r.execution.metadata or {},
                }
            if r.validation:
                entry["validation"] = {
                    "overall_status": r.validation.overall_status.value,
                    "summary": r.validation.summary,
                    "details": [
                        {
                            "dimension": d.dimension,
                            "status": d.status.value,
                            "message": d.message,
                            "expected": d.expected,
                            "actual": d.actual,
                            "details": d.details,
                        }
                        for d in r.validation.details
                    ],
                }
            cases.append(entry)

        passed = sum(
            1 for r in results
            if r.validation and r.validation.overall_status == ValidationStatus.PASSED
        )
        total = len(results)
        return {
            "generated_at": datetime.now().isoformat(),
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed / total * 100:.1f}%" if total else "N/A",
            "cases": cases,
        }

    @staticmethod
    def _build_text(results: List[PipelineResult]) -> str:
        lines = ["=" * 60, "Istio 动态验证报告", "=" * 60, ""]
        passed = failed = warning = 0
        for r in results:
            status = r.validation.overall_status.value if r.validation else "skipped"
            icon = {"passed": "PASS", "failed": "FAIL", "warning": "WARN"}.get(status, "SKIP")
            dur = f" ({r.case_duration_seconds:.1f}s)" if r.case_duration_seconds is not None else ""
            lines.append(f"[{icon}] {r.test_case.case_id}: {r.test_case.description}{dur}")
            if r.validation:
                for d in r.validation.details:
                    lines.append(f"      [{d.status.value.upper()}] {d.dimension}: {d.message}")
                if status == "passed":
                    passed += 1
                elif status == "failed":
                    failed += 1
                else:
                    warning += 1
            lines.append("")

        lines.append("-" * 60)
        lines.append(f"总计: {len(results)}  通过: {passed}  失败: {failed}  警告: {warning}")
        rate = passed / len(results) * 100 if results else 0
        lines.append(f"通过率: {rate:.1f}%")
        return "\n".join(lines)
