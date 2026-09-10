"""
一致性检测器

对比静态策略和动态行为，识别不一致性并生成详细报告
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from consistency_checker.models.data_models import (
    StaticPolicy,
    DynamicBehavior,
    ConsistencyResult,
    InconsistencyAnnotation,
    ConsistencyStatus,
    SeverityLevel,
    PolicyType
)
from consistency_checker.core.finding_records import (
    LAYER_CATALOG,
    attach_tuples,
    checks_performed,
    collect_alignment_findings,
    collect_conflict_findings,
    index_pairs,
    lookup_pair,
    matching_behaviors,
    _dynamic_status,
)

logger = logging.getLogger(__name__)


class ConsistencyChecker:
    """一致性检测器"""
    
    def __init__(
        self,
        static_policies: List[StaticPolicy],
        dynamic_behaviors: List[DynamicBehavior],
        tolerance: float = 0.1,
        artifact: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化一致性检测器
        
        Args:
            static_policies: 静态策略列表
            dynamic_behaviors: 动态行为列表
            tolerance: 容差阈值（用于流量分配等数值比较）
            artifact: parser 对齐产物（pairs / conflicts），用于补全 Sdecl / Sdp / 资源定位
        """
        self.static_policies = static_policies
        self.dynamic_behaviors = dynamic_behaviors
        self.tolerance = tolerance
        self.artifact = artifact or {}
        
        self.inconsistencies: List[InconsistencyAnnotation] = []
        self.policy_behavior_mapping: Dict[str, List[str]] = {}  # policy_id -> [case_ids]
        self._pairs = index_pairs(self.artifact)
        
    def check(self) -> ConsistencyResult:
        """
        执行一致性检查
        
        Returns:
            一致性检查结果
        """
        logger.info("开始一致性检查")
        
        # 0. 第一层 / 第三层：消费对齐产物与跨资源冲突
        alignment_findings = collect_alignment_findings(self.artifact, self.dynamic_behaviors)
        conflict_findings = collect_conflict_findings(self.artifact)
        self.inconsistencies.extend(alignment_findings)
        self.inconsistencies.extend(conflict_findings)
        logger.info(f"✓ 平面对齐检查: {len(alignment_findings)} 条")
        logger.info(f"✓ 跨资源冲突检查: {len(conflict_findings)} 条")
        
        # 1. 建立策略和行为的映射关系
        self._build_policy_behavior_mapping()
        logger.info(f"✓ 建立映射: {len(self.policy_behavior_mapping)} 个策略")
        
        # 2. 检查策略有效性（是否有对应的测试验证）
        unverified_policies = self._check_policy_effectiveness()
        logger.info(f"✓ 策略有效性检查: {len(unverified_policies)} 个未验证策略")
        
        # 3. 检查作用范围一致性
        scope_issues = self._check_scope_consistency()
        logger.info(f"✓ 范围一致性检查: 发现 {len(scope_issues)} 个问题")
        
        # 4. 检查行为偏差
        behavior_deviations = self._check_behavior_deviation()
        logger.info(f"✓ 行为偏差检查: 发现 {len(behavior_deviations)} 个偏差")
        
        # 5. 检查策略冲突
        conflicts = self._check_policy_conflicts()
        logger.info(f"✓ 策略冲突检查: 发现 {len(conflicts)} 个冲突")

        self._apply_runtime_filters()
        
        # 6. 汇总结果
        result = self._generate_consistency_result(
            unverified_policies,
            scope_issues,
            behavior_deviations,
            conflicts
        )
        
        logger.info(f"✓ 一致性检查完成: 状态={result.overall_status.value}, "
                   f"一致性率={result.consistency_rate:.2%}")
        
        return result

    def _apply_runtime_filters(self) -> None:
        """按运行时配置过滤检验记录（层次、功能、严重级别、样本数）。"""
        try:
            from consistency_checker.config import get_config
            cfg = get_config()
        except Exception:
            return
        before = len(self.inconsistencies)
        self.inconsistencies = [item for item in self.inconsistencies if cfg.allows_finding(item)]
        dropped = before - len(self.inconsistencies)
        if dropped:
            logger.info("按运行时配置过滤掉 %s 条检验记录", dropped)
    
    def _build_policy_behavior_mapping(self):
        """建立策略和动态行为的映射关系"""
        for policy in self.static_policies:
            matching = []
            target = str(policy.target_service or "").split(".")[0]
            for behavior in self.dynamic_behaviors:
                if behavior.policy_type != policy.policy_type:
                    continue
                names = {
                    str(behavior.target_service or "").split(".")[0],
                    str(behavior.source_service or "").split(".")[0],
                    str((behavior.test_params or {}).get("host") or "").split(".")[0],
                }
                if target and target in names:
                    matching.append(behavior.test_case_id)
            if matching:
                self.policy_behavior_mapping[policy.policy_id] = matching
    
    def _check_policy_effectiveness(self) -> List[str]:
        """统计尚未动态验证的声明式策略；不再单独写成不一致记录。

        静态是否一致看 Sdecl↔Sdp；动态是否一致看对应功能的 Srt。
        未打流量只在对齐记录里显示「尚未打入对应流量」。
        """
        unverified_policies = []
        for policy in self.static_policies:
            if policy.policy_id in self.policy_behavior_mapping:
                continue
            alignment = (policy.rules or {}).get("alignment_status")
            if alignment == "matched":
                unverified_policies.append(policy.policy_id)
        return unverified_policies
    
    def _check_scope_consistency(self) -> List[Dict[str, Any]]:
        """检查策略作用范围的一致性"""
        scope_issues = []
        
        for policy in self.static_policies:
            if policy.policy_id not in self.policy_behavior_mapping:
                continue
            
            case_ids = self.policy_behavior_mapping[policy.policy_id]
            behaviors = [b for b in self.dynamic_behaviors if b.test_case_id in case_ids]
            
            # 流量分配用例用 distribution 覆盖全部 subset，不要求按 subset 拆用例
            if any(
                isinstance(b.expected_behavior, dict) and b.expected_behavior.get("distribution")
                for b in behaviors
            ):
                continue

            if policy.applies_to:
                tested_subsets = set()
                for behavior in behaviors:
                    subset = behavior.test_params.get('subset') or behavior.test_params.get('version')
                    if subset:
                        tested_subsets.add(subset)
                
                expected_subsets = set(policy.applies_to)
                missing_subsets = expected_subsets - tested_subsets
                
                if missing_subsets:
                    issue = {
                        "policy_id": policy.policy_id,
                        "policy_name": policy.config_name,
                        "expected_subsets": list(expected_subsets),
                        "tested_subsets": list(tested_subsets),
                        "missing_subsets": list(missing_subsets)
                    }
                    scope_issues.append(issue)
                    
                    # 创建不一致性标注
                    pair = lookup_pair(self._pairs, policy.target_service, policy_type=policy.policy_type)
                    inconsistency = InconsistencyAnnotation(
                        inconsistency_id=f"inc_scope_{policy.policy_id}",
                        inconsistency_type="scope_mismatch",
                        severity=SeverityLevel.MEDIUM,
                        description=f"策略 {policy.config_name} 的部分作用范围未被测试覆盖",
                        affected_policies=[policy.policy_id],
                        affected_services=[policy.target_service],
                        affected_subsets=list(missing_subsets),
                        layer="layer2",
                        static_expectation={"applies_to": list(expected_subsets)},
                        dynamic_observation={"tested": list(tested_subsets), "missing": list(missing_subsets)},
                        root_cause="测试覆盖不完整",
                        suggestions=[
                            f"添加针对子集 {missing_subsets} 的测试用例",
                            "确认这些子集是否真实存在"
                        ],
                        impact_scope=list(missing_subsets)
                    )
                    self.inconsistencies.append(attach_tuples(inconsistency, pair=pair, policy=policy))
        
        return scope_issues
    
    def _check_behavior_deviation(self) -> List[Dict[str, Any]]:
        """检查动态行为与静态策略的偏差。

        已对齐到声明式功能的用例会写在同一条 Sdecl/Sdp/Srt 记录里，这里只补
        没有对应 pair 的失败用例。
        """
        deviations = []
        for behavior in self.dynamic_behaviors:
            if getattr(behavior, "skipped", False) or behavior.is_verified:
                continue
            pair = lookup_pair(self._pairs, behavior.target_service, policy_type=behavior.policy_type)
            if pair is None:
                pair = lookup_pair(self._pairs, behavior.source_service, policy_type=behavior.policy_type)
            related_policies = [
                p for p in self.static_policies
                if p.policy_type == behavior.policy_type and p.target_service == behavior.target_service
            ]
            if pair is not None:
                continue
            if not related_policies:
                continue
            policy = related_policies[0] if related_policies else None
            itype = "traffic_split_drift" if behavior.policy_type == PolicyType.TRAFFIC_SPLIT else "behavior_deviation"
            inconsistency = InconsistencyAnnotation(
                inconsistency_id=f"inc_deviation_{behavior.test_case_id}",
                inconsistency_type=itype,
                severity=self._determine_deviation_severity(behavior, policy),
                description=(
                    f"测试 {behavior.test_case_id} 的实际行为与策略 {policy.config_name} 定义不一致"
                    if policy else
                    f"测试 {behavior.test_case_id} 的运行时行为与期望不一致"
                ),
                affected_policies=[policy.policy_id] if policy else [],
                affected_services=[behavior.target_service],
                layer="layer2",
                static_expectation=behavior.expected_behavior,
                dynamic_observation=behavior.actual_behavior,
                root_cause=self._analyze_deviation_root_cause(behavior),
                suggestions=(
                    self._generate_deviation_suggestions(behavior, policy)
                    if policy else
                    ["对照 Sdecl / Sdp 与本次 Srt 观测", f"查看用例 {behavior.test_case_id}"]
                ),
                impact_scope=[behavior.target_service],
            )
            self.inconsistencies.append(attach_tuples(
                inconsistency, pair=pair, policy=policy, behavior=behavior
            ))
            deviations.append({
                "test_case_id": behavior.test_case_id,
                "policy_id": policy.policy_id if policy else None,
                "policy_type": behavior.policy_type.value,
                "service": behavior.target_service,
                "expected": behavior.expected_behavior,
                "actual": behavior.actual_behavior,
            })
        return deviations
    
    def _check_policy_conflicts(self) -> List[Dict[str, Any]]:
        """检查策略冲突"""
        conflicts = []
        
        # 按目标服务分组策略
        service_policies: Dict[str, List[StaticPolicy]] = {}
        for policy in self.static_policies:
            service = policy.target_service
            if service not in service_policies:
                service_policies[service] = []
            service_policies[service].append(policy)
        
        # 检查同一服务上的策略是否冲突
        for service, policies in service_policies.items():
            # 检查流量分配冲突
            traffic_split_policies = [p for p in policies if p.policy_type == PolicyType.TRAFFIC_SPLIT]
            if len(traffic_split_policies) > 1:
                conflict = {
                    "type": "multiple_traffic_split",
                    "service": service,
                    "policies": [p.policy_id for p in traffic_split_policies],
                    "description": f"服务 {service} 存在多个流量分配策略"
                }
                conflicts.append(conflict)
                
                # 创建冲突标注
                pair = lookup_pair(self._pairs, service, policy_type=PolicyType.TRAFFIC_SPLIT)
                inconsistency = InconsistencyAnnotation(
                    inconsistency_id=f"inc_conflict_{service}_traffic_split",
                    inconsistency_type="policy_conflict",
                    severity=SeverityLevel.HIGH,
                    description=f"服务 {service} 配置了多个流量分配策略，可能导致行为不确定",
                    affected_policies=[p.policy_id for p in traffic_split_policies],
                    affected_services=[service],
                    layer="layer3",
                    resource_kind="DestinationRule",
                    function_type="traffic_shifting",
                    root_cause="重复的流量分配配置",
                    suggestions=[
                        "合并或删除冗余的流量分配策略",
                        "确保只有一个DestinationRule定义流量权重"
                    ],
                    impact_scope=[service]
                )
                self.inconsistencies.append(attach_tuples(
                    inconsistency, pair=pair, policy=traffic_split_policies[0]
                ))
        
        return conflicts
    
    def _determine_deviation_severity(self, behavior: DynamicBehavior, policy: Optional[StaticPolicy]) -> SeverityLevel:
        """确定偏差的严重程度"""
        # 根据策略类型和偏差细节判断严重程度
        if behavior.policy_type in [PolicyType.CIRCUIT_BREAKER, PolicyType.AUTHORIZATION]:
            return SeverityLevel.CRITICAL
        elif behavior.policy_type in [PolicyType.ROUTING, PolicyType.TRAFFIC_SPLIT]:
            return SeverityLevel.HIGH
        elif behavior.policy_type in [PolicyType.RETRY, PolicyType.TIMEOUT]:
            return SeverityLevel.MEDIUM
        else:
            return SeverityLevel.LOW
    
    def _analyze_deviation_root_cause(self, behavior: DynamicBehavior) -> str:
        """分析偏差的根本原因"""
        verification_details = behavior.verification_details
        
        if not verification_details:
            return "未知原因"
        
        # 检查各维度的验证结果
        checks = verification_details.get('dimension_checks', {})
        
        failed_checks = []
        for dimension, result in checks.items():
            if isinstance(result, dict) and not result.get('passed', True):
                failed_checks.append(dimension)
        
        if failed_checks:
            return f"以下维度验证失败: {', '.join(failed_checks)}"
        
        return "动态行为与静态配置不匹配"
    
    def _generate_deviation_suggestions(self, behavior: DynamicBehavior, policy: StaticPolicy) -> List[str]:
        """生成偏差修复建议"""
        suggestions = []
        
        if behavior.policy_type == PolicyType.ROUTING:
            suggestions.append("检查VirtualService的匹配条件是否正确")
            suggestions.append("确认目标服务和端口配置")
        elif behavior.policy_type == PolicyType.TRAFFIC_SPLIT:
            suggestions.append("检查DestinationRule中的subset定义")
            suggestions.append("验证流量权重配置是否正确")
            suggestions.append("确保有足够的请求量进行统计验证")
        elif behavior.policy_type == PolicyType.CIRCUIT_BREAKER:
            suggestions.append("检查连接池和异常检测配置")
            suggestions.append("确认触发条件是否达到")
        elif behavior.policy_type == PolicyType.RETRY:
            suggestions.append("检查重试策略配置")
            suggestions.append("确认上游服务的错误响应")
        
        suggestions.append(f"查看详细日志: {behavior.test_case_id}")
        
        return suggestions
    
    def _generate_consistency_result(
        self,
        unverified_policies: List[str],
        scope_issues: List[Dict[str, Any]],
        behavior_deviations: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]]
    ) -> ConsistencyResult:
        """生成一致性检查结果"""
        
        # 确定总体一致性状态
        total_issues = len(self.inconsistencies)
        critical_issues = sum(1 for inc in self.inconsistencies if inc.severity == SeverityLevel.CRITICAL)
        high_issues = sum(1 for inc in self.inconsistencies if inc.severity == SeverityLevel.HIGH)
        
        if critical_issues > 0:
            overall_status = ConsistencyStatus.INCONSISTENT
        elif high_issues > 0:
            overall_status = ConsistencyStatus.PARTIAL
        elif total_issues > 0:
            overall_status = ConsistencyStatus.PARTIAL
        else:
            overall_status = ConsistencyStatus.CONSISTENT
        
        declared_pairs = [
            p for p in (self.artifact.get("pairs") or [])
            if isinstance(p, dict) and p.get("control_tuples")
        ]
        static_matched = [p for p in declared_pairs if p.get("alignment_status") == "matched"]
        static_bad = [
            p for p in declared_pairs
            if p.get("alignment_status") in {"control_only", "mismatched", "partial_matched"}
        ]
        static_match_rate = (len(static_matched) / len(declared_pairs)) if declared_pairs else 1.0

        judged = [
            b for b in self.dynamic_behaviors
            if (not getattr(b, "skipped", False)) and b.verification_details
        ]
        passed_dyn = [b for b in judged if b.is_verified]
        failed_dyn = [b for b in judged if not b.is_verified]
        dynamic_verify_rate = (len(passed_dyn) / len(judged)) if judged else 0.0

        split_ok = 0
        split_judged = 0
        scores = []
        for pair in declared_pairs:
            svc = pair.get("service_name") or ""
            ftype = pair.get("function_type") or ""
            runtime = matching_behaviors(self.dynamic_behaviors, svc, function_type=ftype)
            dyn = _dynamic_status(runtime)
            static_ok = pair.get("alignment_status") == "matched"
            if ftype in {"traffic_shifting", "traffic_split"} and dyn in {"passed", "failed"}:
                split_judged += 1
                if static_ok and dyn == "passed":
                    split_ok += 1
            if not static_ok:
                scores.append(0.0)
            elif dyn == "failed":
                scores.append(0.0)
            else:
                scores.append(1.0)
        consistency_rate = (sum(scores) / len(scores)) if scores else 1.0
        split_rate = (split_ok / split_judged) if split_judged else None

        issue_findings = [
            inc for inc in self.inconsistencies
            if inc.inconsistency_type not in {"matched", "dynamic_skipped", "dynamic_passed"}
            and inc.severity in {SeverityLevel.CRITICAL, SeverityLevel.HIGH, SeverityLevel.MEDIUM}
        ]
        if any(inc.severity == SeverityLevel.CRITICAL for inc in issue_findings):
            overall_status = ConsistencyStatus.INCONSISTENT
        elif static_bad or failed_dyn:
            overall_status = ConsistencyStatus.PARTIAL if static_matched else ConsistencyStatus.INCONSISTENT
        elif issue_findings:
            overall_status = ConsistencyStatus.PARTIAL
        else:
            overall_status = ConsistencyStatus.CONSISTENT

        verified_policies = []
        inconsistent_policies = []
        for policy in self.static_policies:
            alignment = (policy.rules or {}).get("alignment_status")
            has_fail = any(
                inc.inconsistency_type in {"behavior_deviation", "traffic_split_drift"}
                and policy.policy_id in (inc.affected_policies or [])
                for inc in self.inconsistencies
            )
            if alignment == "matched" and not has_fail:
                verified_policies.append(policy.policy_id)
            elif alignment and alignment != "matched":
                inconsistent_policies.append(policy.policy_id)

        total_policies = len(declared_pairs) or len(self.static_policies)
        verified_count = len(static_matched)

        result = ConsistencyResult(
            result_id=f"consistency_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            overall_status=overall_status,
            timestamp=datetime.now(),
            static_policies=self.static_policies,
            dynamic_behaviors=self.dynamic_behaviors,
            consistent_policies=verified_policies,
            inconsistent_policies=inconsistent_policies,
            unverified_policies=unverified_policies,
            inconsistencies=self.inconsistencies,
            total_policies=total_policies,
            verified_policies=verified_count,
            consistency_rate=consistency_rate,
            summary={
                "total_inconsistencies": len(issue_findings),
                "critical_issues": critical_issues,
                "high_issues": high_issues,
                "scope_issues": len(scope_issues),
                "behavior_deviations": len(behavior_deviations),
                "policy_conflicts": len(conflicts),
                "unverified_policies": len(unverified_policies),
                "static_match_rate": static_match_rate,
                "dynamic_verify_rate": dynamic_verify_rate,
                "split_consistency_rate": split_rate,
                "declared_functions": len(declared_pairs),
                "matched_functions": len(static_matched),
                "dynamic_passed": len(passed_dyn),
                "dynamic_failed": len(failed_dyn),
                "dynamic_skipped": sum(1 for b in self.dynamic_behaviors if getattr(b, "skipped", False)),
                "dynamic_total": len(self.dynamic_behaviors),
                "by_layer": {
                    layer: sum(1 for inc in self.inconsistencies if inc.layer == layer)
                    for layer in ("layer1", "layer2", "layer3")
                },
                "by_type": {
                    itype: sum(1 for inc in self.inconsistencies if inc.inconsistency_type == itype)
                    for itype in sorted({inc.inconsistency_type for inc in self.inconsistencies})
                },
                "layers": LAYER_CATALOG,
                "checks_performed": checks_performed(),
            }
        )
        
        return result


