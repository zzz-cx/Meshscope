"""
一致性检测器

对比静态策略和动态行为，识别不一致性并生成详细报告
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
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

logger = logging.getLogger(__name__)


class ConsistencyChecker:
    """一致性检测器"""
    
    def __init__(
        self,
        static_policies: List[StaticPolicy],
        dynamic_behaviors: List[DynamicBehavior],
        tolerance: float = 0.1
    ):
        """
        初始化一致性检测器
        
        Args:
            static_policies: 静态策略列表
            dynamic_behaviors: 动态行为列表
            tolerance: 容差阈值（用于流量分配等数值比较）
        """
        self.static_policies = static_policies
        self.dynamic_behaviors = dynamic_behaviors
        self.tolerance = tolerance
        
        self.inconsistencies: List[InconsistencyAnnotation] = []
        self.policy_behavior_mapping: Dict[str, List[str]] = {}  # policy_id -> [case_ids]
        
    def check(self) -> ConsistencyResult:
        """
        执行一致性检查
        
        Returns:
            一致性检查结果
        """
        logger.info("开始一致性检查")
        
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
    
    def _build_policy_behavior_mapping(self):
        """建立策略和动态行为的映射关系"""
        for policy in self.static_policies:
            matching_behaviors = []
            
            for behavior in self.dynamic_behaviors:
                # 匹配策略类型和目标服务
                if (behavior.policy_type == policy.policy_type and
                    behavior.target_service == policy.target_service):
                    matching_behaviors.append(behavior.test_case_id)
            
            if matching_behaviors:
                self.policy_behavior_mapping[policy.policy_id] = matching_behaviors
    
    def _check_policy_effectiveness(self) -> List[str]:
        """检查策略是否有效（是否有对应的动态测试验证）"""
        unverified_policies = []
        
        for policy in self.static_policies:
            if policy.policy_id not in self.policy_behavior_mapping:
                unverified_policies.append(policy.policy_id)
                
                # 创建不一致性标注
                inconsistency = InconsistencyAnnotation(
                    inconsistency_id=f"inc_policy_unverified_{policy.policy_id}",
                    inconsistency_type="policy_not_verified",
                    severity=SeverityLevel.MEDIUM,
                    description=f"策略 {policy.config_name} 未被动态测试验证",
                    affected_policies=[policy.policy_id],
                    affected_services=[policy.target_service],
                    static_expectation={"policy": policy.config_name, "type": policy.policy_type.value},
                    dynamic_observation={"tests": 0, "status": "no_test_coverage"},
                    root_cause="缺少对应的测试用例",
                    suggestions=[
                        f"为 {policy.config_name} 添加动态测试用例",
                        "确认策略是否真正生效"
                    ]
                )
                self.inconsistencies.append(inconsistency)
        
        return unverified_policies
    
    def _check_scope_consistency(self) -> List[Dict[str, Any]]:
        """检查策略作用范围的一致性"""
        scope_issues = []
        
        for policy in self.static_policies:
            if policy.policy_id not in self.policy_behavior_mapping:
                continue
            
            case_ids = self.policy_behavior_mapping[policy.policy_id]
            behaviors = [b for b in self.dynamic_behaviors if b.test_case_id in case_ids]
            
            # 检查是否所有相关子集都被测试覆盖
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
                    inconsistency = InconsistencyAnnotation(
                        inconsistency_id=f"inc_scope_{policy.policy_id}",
                        inconsistency_type="scope_mismatch",
                        severity=SeverityLevel.MEDIUM,
                        description=f"策略 {policy.config_name} 的部分作用范围未被测试覆盖",
                        affected_policies=[policy.policy_id],
                        affected_services=[policy.target_service],
                        static_expectation={"applies_to": list(expected_subsets)},
                        dynamic_observation={"tested": list(tested_subsets), "missing": list(missing_subsets)},
                        root_cause="测试覆盖不完整",
                        suggestions=[
                            f"添加针对子集 {missing_subsets} 的测试用例",
                            "确认这些子集是否真实存在"
                        ],
                        impact_scope=list(missing_subsets)
                    )
                    self.inconsistencies.append(inconsistency)
        
        return scope_issues
    
    def _check_behavior_deviation(self) -> List[Dict[str, Any]]:
        """检查动态行为与静态策略的偏差"""
        deviations = []
        
        for behavior in self.dynamic_behaviors:
            if not behavior.is_verified:
                # 找到相关的静态策略
                related_policies = [
                    p for p in self.static_policies
                    if p.policy_type == behavior.policy_type and
                       p.target_service == behavior.target_service
                ]
                
                if related_policies:
                    policy = related_policies[0]
                    
                    deviation = {
                        "test_case_id": behavior.test_case_id,
                        "policy_id": policy.policy_id,
                        "policy_type": policy.policy_type.value,
                        "service": behavior.target_service,
                        "expected": behavior.expected_behavior,
                        "actual": behavior.actual_behavior,
                        "verification_details": behavior.verification_details
                    }
                    deviations.append(deviation)
                    
                    # 确定严重程度
                    severity = self._determine_deviation_severity(behavior, policy)
                    
                    # 创建不一致性标注
                    inconsistency = InconsistencyAnnotation(
                        inconsistency_id=f"inc_deviation_{behavior.test_case_id}",
                        inconsistency_type="behavior_deviation",
                        severity=severity,
                        description=f"测试 {behavior.test_case_id} 的实际行为与策略 {policy.config_name} 定义不一致",
                        affected_policies=[policy.policy_id],
                        affected_services=[behavior.target_service],
                        static_expectation=behavior.expected_behavior,
                        dynamic_observation=behavior.actual_behavior,
                        root_cause=self._analyze_deviation_root_cause(behavior),
                        suggestions=self._generate_deviation_suggestions(behavior, policy),
                        impact_scope=[behavior.target_service]
                    )
                    self.inconsistencies.append(inconsistency)
        
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
                inconsistency = InconsistencyAnnotation(
                    inconsistency_id=f"inc_conflict_{service}_traffic_split",
                    inconsistency_type="policy_conflict",
                    severity=SeverityLevel.HIGH,
                    description=f"服务 {service} 配置了多个流量分配策略，可能导致行为不确定",
                    affected_policies=[p.policy_id for p in traffic_split_policies],
                    affected_services=[service],
                    root_cause="重复的流量分配配置",
                    suggestions=[
                        "合并或删除冗余的流量分配策略",
                        "确保只有一个DestinationRule定义流量权重"
                    ],
                    impact_scope=[service]
                )
                self.inconsistencies.append(inconsistency)
        
        return conflicts
    
    def _determine_deviation_severity(self, behavior: DynamicBehavior, policy: StaticPolicy) -> SeverityLevel:
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
        
        # 分类策略
        verified_policies = []
        inconsistent_policies = []
        
        for policy in self.static_policies:
            if policy.policy_id in unverified_policies:
                continue
            
            # 检查该策略是否有相关的偏差
            has_deviation = any(
                inc.inconsistency_type == "behavior_deviation" and policy.policy_id in inc.affected_policies
                for inc in self.inconsistencies
            )
            
            if has_deviation:
                inconsistent_policies.append(policy.policy_id)
            else:
                verified_policies.append(policy.policy_id)
        
        # 计算一致性率
        total_policies = len(self.static_policies)
        verified_count = len(verified_policies)
        consistency_rate = verified_count / total_policies if total_policies > 0 else 0.0
        
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
                "total_inconsistencies": total_issues,
                "critical_issues": critical_issues,
                "high_issues": high_issues,
                "scope_issues": len(scope_issues),
                "behavior_deviations": len(behavior_deviations),
                "policy_conflicts": len(conflicts),
                "unverified_policies": len(unverified_policies)
            }
        )
        
        return result


