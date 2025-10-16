"""
动态分析器

负责整合动态测试结果，包括测试矩阵、验证结果和运行时数据
"""

import os
import sys
import json
import logging
from typing import Dict, List, Optional, Any
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
                "failed_tests": sum(1 for b in self.dynamic_behaviors if not b.is_verified and b.verification_details),
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
    
    def _load_verification_results(self):
        """加载验证结果"""
        if not os.path.exists(self.verification_dir):
            logger.warning(f"验证结果目录不存在: {self.verification_dir}")
            return
        
        try:
            # 查找综合报告文件
            report_files = [
                f for f in os.listdir(self.verification_dir)
                if f.startswith('comprehensive_report_') and f.endswith('.json')
            ]
            
            if not report_files:
                logger.warning("未找到综合验证报告")
                return
            
            # 使用最新的报告
            latest_report = max(
                report_files,
                key=lambda f: os.path.getmtime(os.path.join(self.verification_dir, f))
            )
            
            report_path = os.path.join(self.verification_dir, latest_report)
            with open(report_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # 提取各用例的验证结果
                for case_id, result in data.get('verification_results', {}).items():
                    self.verification_results[case_id] = result
                    
            logger.info(f"从 {latest_report} 加载验证结果")
            
        except Exception as e:
            logger.error(f"加载验证结果失败: {e}")
    
    def _load_http_results(self):
        """加载HTTP测试结果"""
        if not os.path.exists(self.http_results_dir):
            logger.warning(f"HTTP结果目录不存在: {self.http_results_dir}")
            return
        
        try:
            for filename in os.listdir(self.http_results_dir):
                if filename.endswith('_http_result.json') or filename.endswith('_http_result_*.json'):
                    # 提取case_id
                    parts = filename.replace('_http_result', '').replace('.json', '').split('_')
                    if len(parts) >= 2:
                        case_id = f"{parts[0]}_{parts[1]}"
                        
                        file_path = os.path.join(self.http_results_dir, filename)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            self.http_results[case_id] = data.get('http_result', data)
        except Exception as e:
            logger.error(f"加载HTTP结果失败: {e}")
    
    def _extract_dynamic_behaviors(self):
        """从测试矩阵和验证结果提取动态行为"""
        if not self.test_matrix:
            logger.warning("测试矩阵为空，无法提取动态行为")
            return
        
        for test_case in self.test_matrix:
            case_id = test_case.get('case_id', 'unknown')
            
            # 确定策略类型
            policy_type = self._determine_policy_type(test_case)
            
            # 提取服务信息
            target_service = test_case.get('target_service', test_case.get('service', 'unknown'))
            source_service = test_case.get('source_service', 'client')
            
            # 提取期望行为
            expected_behavior = test_case.get('expected_behavior', {})
            
            # 提取实际行为（从验证结果）
            verification_result = self.verification_results.get(case_id, {})
            actual_behavior = verification_result.get('actual_behavior', {})
            
            # 提取HTTP结果
            http_result = self.http_results.get(case_id, {})
            
            # 判断是否验证通过
            is_verified = verification_result.get('overall_result', {}).get('passed', False)
            
            behavior = DynamicBehavior(
                test_case_id=case_id,
                policy_type=policy_type,
                source_service=source_service,
                target_service=target_service,
                test_params=test_case.get('test_params', {}),
                expected_behavior=expected_behavior,
                actual_behavior=actual_behavior,
                http_results=http_result,
                is_verified=is_verified,
                verification_details=verification_result,
                executed_at=datetime.now()
            )
            
            self.dynamic_behaviors.append(behavior)
    
    def _determine_policy_type(self, test_case: Dict[str, Any]) -> PolicyType:
        """根据测试用例确定策略类型"""
        case_type = test_case.get('case_type', '').lower()
        test_type = test_case.get('test_type', '').lower()
        
        if 'route' in case_type or 'match' in case_type:
            return PolicyType.ROUTING
        elif 'split' in case_type or 'weight' in case_type or 'canary' in case_type:
            return PolicyType.TRAFFIC_SPLIT
        elif 'retry' in case_type or test_type == 'retry':
            return PolicyType.RETRY
        elif 'timeout' in case_type or test_type == 'timeout':
            return PolicyType.TIMEOUT
        elif 'circuit' in case_type or 'breaker' in case_type:
            return PolicyType.CIRCUIT_BREAKER
        elif 'fault' in case_type or 'abort' in case_type or 'delay' in case_type:
            return PolicyType.FAULT_INJECTION
        elif 'ratelimit' in case_type or 'rate_limit' in case_type:
            return PolicyType.RATE_LIMIT
        else:
            return PolicyType.ROUTING  # 默认
    
    def _calculate_statistics(self) -> Dict[str, Any]:
        """计算统计数据"""
        if not self.dynamic_behaviors:
            return {
                "total_tests": 0,
                "verified_tests": 0,
                "failed_tests": 0,
                "verification_rate": 0.0,
                "by_policy_type": {}
            }
        
        total = len(self.dynamic_behaviors)
        verified = sum(1 for b in self.dynamic_behaviors if b.is_verified)
        failed = sum(1 for b in self.dynamic_behaviors if not b.is_verified and b.verification_details)
        
        # 按策略类型分组统计
        by_policy_type = {}
        for behavior in self.dynamic_behaviors:
            policy_type = behavior.policy_type.value
            if policy_type not in by_policy_type:
                by_policy_type[policy_type] = {
                    "total": 0,
                    "verified": 0,
                    "failed": 0
                }
            
            by_policy_type[policy_type]["total"] += 1
            if behavior.is_verified:
                by_policy_type[policy_type]["verified"] += 1
            elif behavior.verification_details:
                by_policy_type[policy_type]["failed"] += 1
        
        return {
            "total_tests": total,
            "verified_tests": verified,
            "failed_tests": failed,
            "verification_rate": verified / total if total > 0 else 0.0,
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


