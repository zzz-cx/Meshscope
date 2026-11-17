"""
动态分析器

负责整合动态测试结果，包括测试矩阵、验证结果和运行时数据
"""

import os
import sys
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from consistency_checker.models.data_models import (
    DynamicBehavior,
    PolicyType
)
from consistency_checker.config import get_config

logger = logging.getLogger(__name__)


class DynamicAnalyzer:
    """动态测试结果分析器"""
    
    def __init__(
        self,
        test_matrix_file: Optional[str] = None,
        verification_dir: Optional[str] = None,
        http_results_dir: Optional[str] = None
    ):
        """
        初始化动态分析器
        
        Args:
            test_matrix_file: 测试矩阵文件路径
            verification_dir: 验证结果目录
            http_results_dir: HTTP测试结果目录
        """
        self.config = get_config()
        self.test_matrix_file = test_matrix_file or self.config.test_matrix_file
        self.verification_dir = verification_dir or self.config.verification_dir
        self.http_results_dir = http_results_dir or self.config.http_results_dir
        
        self.test_matrix = None
        self.verification_results = {}
        self.http_results = {}
        self.dynamic_behaviors: List[DynamicBehavior] = []
        
    def analyze(self) -> Dict[str, Any]:
        """
        执行动态分析
        
        Returns:
            包含动态行为和测试结果的分析数据
        """
        logger.info("开始动态分析")
        
        # 1. 加载测试矩阵
        self._load_test_matrix()
        logger.info(f"✓ 加载测试矩阵: {len(self.test_matrix) if self.test_matrix else 0} 个测试用例")
        
        # 2. 加载验证结果
        self._load_verification_results()
        logger.info(f"✓ 加载验证结果: {len(self.verification_results)} 个用例")
        
        # 3. 加载HTTP测试结果
        self._load_http_results()
        logger.info(f"✓ 加载HTTP结果: {len(self.http_results)} 个用例")
        
        # 4. 提取动态行为
        self._extract_dynamic_behaviors()
        logger.info(f"✓ 提取动态行为: {len(self.dynamic_behaviors)} 个")
        
        # 5. 统计分析
        statistics = self._calculate_statistics()
        logger.info(f"✓ 统计分析完成")
        
        return {
            "test_matrix": self.test_matrix,
            "verification_results": self.verification_results,
            "http_results": self.http_results,
            "dynamic_behaviors": self.dynamic_behaviors,
            "statistics": statistics,
            "summary": {
                "total_tests": len(self.dynamic_behaviors),
                "verified_tests": sum(1 for b in self.dynamic_behaviors if b.is_verified),
                "failed_tests": sum(
                    1 for b in self.dynamic_behaviors
                    if (not b.is_verified) and (not getattr(b, "skipped", False)) and b.verification_details
                ),
                "skipped_tests": sum(1 for b in self.dynamic_behaviors if getattr(b, "skipped", False)),
                "verification_rate": statistics.get('verification_rate', 0.0)
            }
        }
    
    def _load_test_matrix(self):
        """加载测试矩阵"""
        if not os.path.exists(self.test_matrix_file):
            logger.warning(f"测试矩阵文件不存在: {self.test_matrix_file}")
            self.test_matrix = []
            return
        
        try:
            with open(self.test_matrix_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.test_matrix = data.get('test_cases', []) if isinstance(data, dict) else data
        except Exception as e:
            logger.error(f"加载测试矩阵失败: {e}")
            self.test_matrix = []
    
    def _candidate_dirs(self, primary: Optional[str], extras: List[str]) -> List[str]:
        seen = set()
        out = []
        for path in [primary, *extras]:
            if not path:
                continue
            abs_path = path if os.path.isabs(path) else os.path.join(self.config.project_root, path)
            if abs_path in seen or not os.path.isdir(abs_path):
                continue
            seen.add(abs_path)
            out.append(abs_path)
        return out

    def _load_verification_results(self):
        """加载验证结果（兼容旧 verification 目录与 DynamicTester 的 dynamic_test_*.json）。"""
        dirs = self._candidate_dirs(self.verification_dir, [
            "results/reports",
            "istio_Dynamic_Test/results/verification",
            "results/verification",
        ])
        if not dirs:
            logger.warning("未找到动态验证结果目录")
            return
        try:
            report_candidates = []
            for folder in dirs:
                for name in os.listdir(folder):
                    if not name.endswith(".json") or name.endswith("_summary.json"):
                        continue
                    if (
                        name.startswith("dynamic_test_")
                        or name.startswith("comprehensive_report_")
                        or name.startswith("istio_verification_")
                    ):
                        report_candidates.append(os.path.join(folder, name))
            if not report_candidates:
                logger.warning("未找到综合验证报告")
                return
            report_path = max(report_candidates, key=os.path.getmtime)
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._ingest_verification_payload(data)
            logger.info("从 %s 加载验证结果: %s 个用例", report_path, len(self.verification_results))
        except Exception as e:
            logger.error(f"加载验证结果失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _ingest_verification_payload(self, data: Dict[str, Any]) -> None:
        verification_results = data.get("verification_results") or {}
        if not verification_results:
            for step in data.get("execution_steps") or []:
                if step.get("step") == 3 and "verification_summary" in step:
                    for result in step.get("verification_summary") or []:
                        case_id = result.get("case_id")
                        if case_id:
                            verification_results[case_id] = {
                                "overall_result": {
                                    "passed": result.get("overall_status") == "passed",
                                    "status": result.get("overall_status"),
                                },
                                "actual_behavior": result.get("metrics") or {},
                                "dimension_results": result.get("dimension_results") or {},
                            }
                    break
        if not verification_results and isinstance(data.get("results"), dict):
            verification_results = data["results"]
        if not verification_results and isinstance(data.get("cases"), list):
            for case in data["cases"]:
                if not isinstance(case, dict):
                    continue
                case_id = case.get("case_id")
                if not case_id:
                    continue
                validation = case.get("validation") or {}
                details = validation.get("details") or []
                status = str(validation.get("overall_status") or "")
                messages = " ".join(str(d.get("message") or "") for d in details if isinstance(d, dict))
                skipped = bool(details) and all(
                    isinstance(d, dict) and d.get("status") == "skipped" for d in details
                )
                if status == "skipped":
                    skipped = True
                if "无增量" in messages or "无数据" in str(validation.get("summary") or ""):
                    skipped = True
                if any(
                    token in str(validation.get("summary") or "") or token in messages
                    for token in ("未开启", "未允许", "安全开关")
                ):
                    skipped = True
                exec_data = case.get("execution") or {}
                exec_meta = exec_data.get("metadata") or {}
                actual = {
                    "status_codes": exec_data.get("status_codes"),
                    "total_requests": exec_data.get("total_requests"),
                    "success_rate": exec_data.get("success_rate"),
                    "validation_status": "skipped" if skipped else status,
                    "message": validation.get("summary"),
                }
                weights = {}
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    obs = detail.get("actual")
                    if isinstance(obs, dict) and obs and all(isinstance(v, (int, float)) for v in obs.values()):
                        weights = dict(obs)
                    inner = detail.get("details") or {}
                    if isinstance(inner, dict) and inner.get("weights"):
                        weights = dict(inner["weights"])
                    elif isinstance(obs, dict) and obs.get("weights"):
                        weights = dict(obs["weights"])
                if not weights and exec_meta.get("version_percentages"):
                    weights = dict(exec_meta["version_percentages"])
                if weights:
                    actual["weights"] = weights
                    actual["distribution"] = weights
                if exec_meta.get("landed_services"):
                    actual["landed_services"] = exec_meta["landed_services"]
                if exec_meta.get("version_counts"):
                    actual["version_counts"] = exec_meta["version_counts"]
                verification_results[case_id] = {
                    "overall_result": {
                        "passed": status == "passed" and not skipped,
                        "status": "skipped" if skipped else status,
                        "skipped": skipped,
                    },
                    "actual_behavior": actual,
                    "case": {
                        "description": case.get("description"),
                        "policy_types": case.get("policy_types") or [],
                    },
                }
        for case_id, result in verification_results.items():
            self.verification_results[case_id] = result

    def _load_http_results(self):
        """加载HTTP测试结果"""
        dirs = self._candidate_dirs(self.http_results_dir, [
            "results/http_results",
            "istio_Dynamic_Test/results/http_results",
        ])
        if not dirs:
            logger.warning("未找到 HTTP 结果目录")
            return
        try:
            import re
            newest: Dict[str, Tuple[str, float]] = {}
            for folder in dirs:
                for filename in os.listdir(folder):
                    if not re.match(r'case_\d+_http_result(_\d{8}_\d{6})?\.json$', filename):
                        continue
                    match = re.match(r'(case_\d+)_http_result.*\.json$', filename)
                    if not match:
                        continue
                    case_id = match.group(1)
                    file_path = os.path.join(folder, filename)
                    mtime = os.path.getmtime(file_path)
                    prev = newest.get(case_id)
                    if prev is None or mtime > prev[1]:
                        newest[case_id] = (file_path, mtime)
            for case_id, (file_path, _) in newest.items():
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.http_results[case_id] = data.get("http_result", data)
        except Exception as e:
            logger.error(f"加载HTTP结果失败: {e}")
    
    def _extract_dynamic_behaviors(self):
        """从测试矩阵和验证结果提取动态行为"""
        matrix = list(self.test_matrix or [])
        seen = {str(item.get("case_id")) for item in matrix if isinstance(item, dict) and item.get("case_id")}
        for case_id, result in self.verification_results.items():
            if case_id in seen:
                continue
            meta = (result or {}).get("case") or {}
            matrix.append({
                "case_id": case_id,
                "description": meta.get("description") or case_id,
                "policy_types": meta.get("policy_types") or [],
                "test_strategies": meta.get("policy_types") or [],
            })
        if not matrix:
            logger.warning("测试矩阵为空，无法提取动态行为")
            return
        self.test_matrix = matrix

        for test_case in matrix:
            case_id = test_case.get("case_id", "unknown")
            policy_type = self._determine_policy_type(test_case)
            params = test_case.get("request_params") or test_case.get("test_params") or {}
            host = str(params.get("host") or "").split(".")[0]
            source_service = test_case.get("source_service") or host or "client"
            target_service = (
                test_case.get("target_service")
                or test_case.get("service")
                or host
                or source_service
                or "unknown"
            )
            expected_behavior = (
                test_case.get("expected_behavior")
                or test_case.get("expected_outcome")
                or {}
            )
            verification_result = self.verification_results.get(case_id, {})
            actual_behavior = dict(verification_result.get("actual_behavior") or {})
            http_result = self.http_results.get(case_id, {}) or {}
            if not verification_result:
                continue
            if not actual_behavior.get("weights"):
                percents = http_result.get("version_percentages") or (http_result.get("metadata") or {}).get("version_percentages")
                if percents:
                    actual_behavior["weights"] = percents
                    actual_behavior["distribution"] = percents
            if http_result.get("landed_services") and not actual_behavior.get("landed_services"):
                actual_behavior["landed_services"] = http_result["landed_services"]
            overall = verification_result.get("overall_result") or {}
            skipped = bool(overall.get("skipped"))
            is_verified = bool(overall.get("passed")) and not skipped

            self.dynamic_behaviors.append(DynamicBehavior(
                test_case_id=case_id,
                policy_type=policy_type,
                source_service=source_service,
                target_service=target_service,
                test_params=params,
                expected_behavior=expected_behavior,
                actual_behavior=actual_behavior,
                http_results=http_result,
                is_verified=is_verified,
                skipped=skipped,
                verification_details=verification_result,
                executed_at=datetime.now()
            ))
    
    def _determine_policy_type(self, test_case: Dict[str, Any]) -> PolicyType:
        """根据测试用例确定策略类型"""
        strategies = " ".join(str(s) for s in (test_case.get("test_strategies") or [])).lower()
        policy_types = " ".join(str(s) for s in (test_case.get("policy_types") or [])).lower()
        case_type = str(test_case.get("case_type") or test_case.get("type") or "").lower()
        test_type = str(test_case.get("test_type") or "").lower()
        description = str(test_case.get("description") or "").lower()
        blob = " ".join([strategies, policy_types, case_type, test_type, description])

        if "split" in blob or "weight" in blob or "canary" in blob or "分流" in blob or "流量分配" in blob:
            return PolicyType.TRAFFIC_SPLIT
        if "circuit" in blob or "breaker" in blob or "熔断" in blob:
            return PolicyType.CIRCUIT_BREAKER
        if "retry" in blob or "重试" in blob:
            return PolicyType.RETRY
        if "timeout" in blob or "超时" in blob:
            return PolicyType.TIMEOUT
        if "fault" in blob or "abort" in blob or "delay" in blob:
            return PolicyType.FAULT_INJECTION
        if "ratelimit" in blob or "rate_limit" in blob or "限流" in blob:
            return PolicyType.RATE_LIMIT
        if "route" in blob or "match" in blob:
            return PolicyType.ROUTING
        return PolicyType.ROUTING
    
    def _calculate_statistics(self) -> Dict[str, Any]:
        """计算统计数据"""
        if not self.dynamic_behaviors:
            return {
                "total_tests": 0,
                "verified_tests": 0,
                "failed_tests": 0,
                "skipped_tests": 0,
                "verification_rate": 0.0,
                "by_policy_type": {}
            }
        
        total = len(self.dynamic_behaviors)
        verified = sum(1 for b in self.dynamic_behaviors if b.is_verified)
        skipped = sum(1 for b in self.dynamic_behaviors if getattr(b, "skipped", False))
        failed = sum(
            1 for b in self.dynamic_behaviors
            if (not b.is_verified) and (not getattr(b, "skipped", False)) and b.verification_details
        )
        judged = verified + failed
        
        by_policy_type = {}
        for behavior in self.dynamic_behaviors:
            policy_type = behavior.policy_type.value
            if policy_type not in by_policy_type:
                by_policy_type[policy_type] = {
                    "total": 0,
                    "verified": 0,
                    "failed": 0,
                    "skipped": 0,
                }
            by_policy_type[policy_type]["total"] += 1
            if behavior.is_verified:
                by_policy_type[policy_type]["verified"] += 1
            elif getattr(behavior, "skipped", False):
                by_policy_type[policy_type]["skipped"] += 1
            elif behavior.verification_details:
                by_policy_type[policy_type]["failed"] += 1
        
        return {
            "total_tests": total,
            "verified_tests": verified,
            "failed_tests": failed,
            "skipped_tests": skipped,
            "verification_rate": verified / judged if judged > 0 else 0.0,
            "by_policy_type": by_policy_type
        }
    
    def get_behavior_by_case_id(self, case_id: str) -> Optional[DynamicBehavior]:
        """根据用例ID获取动态行为"""
        for behavior in self.dynamic_behaviors:
            if behavior.test_case_id == case_id:
                return behavior
        return None
    
    def get_behaviors_by_service(self, service_name: str) -> List[DynamicBehavior]:
        """获取服务相关的所有动态行为"""
        return [
            b for b in self.dynamic_behaviors
            if b.target_service == service_name or b.source_service == service_name
        ]
    
    def get_behaviors_by_policy_type(self, policy_type: PolicyType) -> List[DynamicBehavior]:
        """获取特定策略类型的所有动态行为"""
        return [b for b in self.dynamic_behaviors if b.policy_type == policy_type]


