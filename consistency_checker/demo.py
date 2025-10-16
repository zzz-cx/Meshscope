#!/usr/bin/env python3
"""
一致性验证系统演示脚本

快速演示如何使用Python API
"""

import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def demo_config():
    """演示配置管理"""
    print("=" * 80)
    print("演示1: 全局配置管理")
    print("=" * 80)
    
    from consistency_checker.config import get_config, GlobalConfig
    
    # 获取默认配置
    config = get_config()
    print(f"✓ 项目根目录: {config.project_root}")
    print(f"✓ 命名空间: {config.namespace}")
    print(f"✓ 流量分配容差: {config.traffic_split_tolerance}")
    print(f"✓ 一致性输出目录: {config.consistency_output_dir}")
    print()


def demo_data_models():
    """演示数据模型"""
    print("=" * 80)
    print("演示2: 统一数据模型")
    print("=" * 80)
    
    from consistency_checker.models.data_models import (
        StaticPolicy,
        DynamicBehavior,
        PolicyType,
        ConsistencyStatus,
        SeverityLevel
    )
    from datetime import datetime
    
    # 创建静态策略示例
    policy = StaticPolicy(
        policy_id="policy_001",
        policy_type=PolicyType.ROUTING,
        source_service="client",
        target_service="productpage",
        namespace="default",
        config_name="productpage-vs",
        config_type="VirtualService",
        rules={"match": {"uri": {"prefix": "/"}}},
        created_at=datetime.now()
    )
    
    print(f"✓ 策略ID: {policy.policy_id}")
    print(f"✓ 策略类型: {policy.policy_type.value}")
    print(f"✓ 目标服务: {policy.target_service}")
    print()
    
    # 创建动态行为示例
    behavior = DynamicBehavior(
        test_case_id="case_001",
        policy_type=PolicyType.ROUTING,
        source_service="client",
        target_service="productpage",
        expected_behavior={"status_code": 200},
        actual_behavior={"status_code": 200},
        is_verified=True
    )
    
    print(f"✓ 测试用例: {behavior.test_case_id}")
    print(f"✓ 验证状态: {'通过' if behavior.is_verified else '失败'}")
    print()


def demo_static_analyzer():
    """演示静态分析器"""
    print("=" * 80)
    print("演示3: 静态分析器")
    print("=" * 80)
    
    from consistency_checker.core.static_analyzer import StaticAnalyzer
    
    try:
        analyzer = StaticAnalyzer(namespace="default")
        print(f"✓ 静态分析器已初始化")
        print(f"✓ 配置目录: {analyzer.config_dir}")
        print(f"✓ 命名空间: {analyzer.namespace}")
        print()
        
        print("提示: 运行 analyzer.analyze() 可执行完整静态分析")
        print("      需要确保配置文件存在于 istio_config_parser/istio_control_config/")
        print()
        
    except Exception as e:
        print(f"⚠️  静态分析器初始化失败: {e}")
        print()


def demo_dynamic_analyzer():
    """演示动态分析器"""
    print("=" * 80)
    print("演示4: 动态分析器")
    print("=" * 80)
    
    from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
    
    try:
        analyzer = DynamicAnalyzer()
        print(f"✓ 动态分析器已初始化")
        print(f"✓ 测试矩阵文件: {analyzer.test_matrix_file}")
        print(f"✓ 验证结果目录: {analyzer.verification_dir}")
        print()
        
        print("提示: 运行 analyzer.analyze() 可执行完整动态分析")
        print("      需要确保测试结果存在于 istio_Dynamic_Test/results/")
        print()
        
    except Exception as e:
        print(f"⚠️  动态分析器初始化失败: {e}")
        print()


def demo_consistency_checker():
    """演示一致性检测器"""
    print("=" * 80)
    print("演示5: 一致性检测器")
    print("=" * 80)
    
    from consistency_checker.core.consistency_checker import ConsistencyChecker
    from consistency_checker.models.data_models import (
        StaticPolicy,
        DynamicBehavior,
        PolicyType
    )
    from datetime import datetime
    
    # 创建示例数据
    static_policies = [
        StaticPolicy(
            policy_id="policy_001",
            policy_type=PolicyType.ROUTING,
            source_service="*",
            target_service="productpage",
            namespace="default",
            config_name="productpage-vs",
            config_type="VirtualService",
            rules={},
            created_at=datetime.now()
        )
    ]
    
    dynamic_behaviors = [
        DynamicBehavior(
            test_case_id="case_001",
            policy_type=PolicyType.ROUTING,
            source_service="client",
            target_service="productpage",
            is_verified=True
        )
    ]
    
    checker = ConsistencyChecker(
        static_policies=static_policies,
        dynamic_behaviors=dynamic_behaviors,
        tolerance=0.1
    )
    
    print(f"✓ 一致性检测器已初始化")
    print(f"✓ 静态策略数: {len(static_policies)}")
    print(f"✓ 动态行为数: {len(dynamic_behaviors)}")
    print(f"✓ 容差阈值: {checker.tolerance}")
    print()
    
    # 执行检查
    result = checker.check()
    print(f"✓ 一致性检查完成")
    print(f"  - 总体状态: {result.overall_status.value}")
    print(f"  - 总策略数: {result.total_policies}")
    print(f"  - 已验证策略: {result.verified_policies}")
    print(f"  - 一致性率: {result.consistency_rate:.2%}")
    print(f"  - 不一致性: {len(result.inconsistencies)}")
    print()


def demo_pipeline():
    """演示流程编排器"""
    print("=" * 80)
    print("演示6: 流程编排器")
    print("=" * 80)
    
    from consistency_checker.core.orchestrator import Pipeline
    
    pipeline = Pipeline(namespace="default")
    print(f"✓ 流水线已初始化")
    print(f"✓ 命名空间: {pipeline.namespace}")
    print()
    
    print("提示: 使用以下方法执行流水线:")
    print("  - pipeline.run_full_pipeline()      # 完整流水线")
    print("  - pipeline.run_static_only()        # 仅静态分析")
    print("  - pipeline.run_consistency_check_only()  # 仅一致性检查")
    print()


def main():
    """主函数"""
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "Istio一致性验证系统 - 演示" + " " * 32 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    
    try:
        demo_config()
        demo_data_models()
        demo_static_analyzer()
        demo_dynamic_analyzer()
        demo_consistency_checker()
        demo_pipeline()
        
        print("=" * 80)
        print("✅ 所有演示完成！")
        print("=" * 80)
        print()
        print("下一步:")
        print("  1. 查看完整文档: consistency_checker/README.md")
        print("  2. 运行完整流水线: python -m consistency_checker.main --mode full")
        print("  3. 启动Web界面: python -m consistency_checker.main --mode web")
        print()
        
    except Exception as e:
        print(f"\n[ERROR] 演示过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

