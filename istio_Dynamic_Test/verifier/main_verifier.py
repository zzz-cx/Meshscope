#!/usr/bin/env python3
"""
主验证程序

演示如何使用整个验证模块进行：
1. 日志解析
2. 行为模型生成
3. 结果对比
4. 报告生成
"""

import sys
import os
sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('..'))

import json
import argparse
from typing import Dict, List

from log_parser import EnvoyLogParser, parse_logs_from_files
from behavior_model import BehaviorModel, parse_test_matrix
from result_comparator import ResultComparator, compare_batch_results
from report_generator import ReportGenerator

def load_logs_from_directory(log_dir: str) -> Dict[str, Dict[str, List]]:
    """
    从目录中加载日志文件
    
    Args:
        log_dir: 日志目录路径
        
    Returns:
        {case_id: {pod_name: log_content}} 格式的日志数据
    """
    logs_by_case = {}
    parser = EnvoyLogParser()
    
    if not os.path.exists(log_dir):
        print(f"❌ 日志目录不存在: {log_dir}")
        return logs_by_case
    
    print(f"📁 扫描日志目录: {log_dir}")
    
    # 扫描日志文件
    log_files = []
    for filename in os.listdir(log_dir):
        if filename.endswith('.log'):
            log_files.append(os.path.join(log_dir, filename))
    
    print(f"📄 找到 {len(log_files)} 个日志文件")
    
    # 按用例 ID 分组日志文件
    for log_file in log_files:
        filename = os.path.basename(log_file)
        
        # 解析文件名：case_001_reviews_v2_pod-name.log
        parts = filename.replace('.log', '').split('_')
        if len(parts) >= 2:
            case_id = f"{parts[0]}_{parts[1]}"  # case_001
            
            if case_id not in logs_by_case:
                logs_by_case[case_id] = {}
            
            # 读取日志内容
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 从文件名提取 pod 名称
                pod_name = '_'.join(parts[2:])  # reviews_v2_pod-name
                logs_by_case[case_id][pod_name] = content
                
                print(f"  ✅ 加载 {case_id} - {pod_name}")
                
            except Exception as e:
                print(f"  ❌ 读取文件失败 {log_file}: {e}")
    
    # 解析日志内容
    parsed_logs_by_case = {}
    for case_id, logs_dict in logs_by_case.items():
        parsed_logs = parser.parse_logs_batch(logs_dict)
        parsed_logs_by_case[case_id] = parsed_logs
        
        total_entries = sum(len(entries) for entries in parsed_logs.values())
        print(f"📊 {case_id}: 解析到 {total_entries} 条日志条目")
    
    return parsed_logs_by_case

def run_verification(matrix_file: str, log_dir: str, output_dir: str = "results/verification"):
    """
    运行完整的验证流程
    
    Args:
        matrix_file: 测试矩阵文件路径
        log_dir: 日志目录路径  
        output_dir: 输出目录路径
    """
    print("🔍 开始 Istio 动态测试验证流程")
    print("=" * 60)
    
    # 1. 解析测试矩阵，生成期望行为
    print("\n📋 第一步：解析测试矩阵")
    expected_behaviors = parse_test_matrix(matrix_file)
    
    if not expected_behaviors:
        print("❌ 未能解析到任何期望行为，检查测试矩阵文件")
        return
    
    print(f"✅ 成功解析 {len(expected_behaviors)} 个期望行为")
    
    # 2. 加载和解析日志
    print("\n📄 第二步：加载和解析日志")
    parsed_logs_by_case = load_logs_from_directory(log_dir)
    
    if not parsed_logs_by_case:
        print("❌ 未能加载到任何日志数据，检查日志目录")
        return
    
    print(f"✅ 成功加载 {len(parsed_logs_by_case)} 个用例的日志")
    
    # 3. 执行对比验证
    print("\n🔍 第三步：执行对比验证")
    comparator = ResultComparator()
    verification_results = compare_batch_results(
        expected_behaviors, parsed_logs_by_case, comparator
    )
    
    print(f"✅ 完成 {len(verification_results)} 个用例的验证")
    
    # 4. 生成报告
    print("\n📊 第四步：生成验证报告")
    os.makedirs(output_dir, exist_ok=True)
    
    # 加载测试配置
    test_config = None
    try:
        with open(matrix_file, 'r', encoding='utf-8') as f:
            test_config = json.load(f)
    except Exception as e:
        print(f"⚠️ 无法加载测试配置: {e}")
    
    # 生成报告
    report_generator = ReportGenerator(output_dir)
    report_files = report_generator.generate_comprehensive_report(
        verification_results, test_config, "istio_verification"
    )
    
    # 5. 显示验证结果摘要
    print("\n📈 第五步：验证结果摘要")
    print("-" * 40)
    
    passed_count = sum(1 for r in verification_results if r.overall_status.value == 'passed')
    failed_count = sum(1 for r in verification_results if r.overall_status.value == 'failed')
    warning_count = sum(1 for r in verification_results if r.overall_status.value == 'warning')
    
    print(f"✅ 通过用例: {passed_count}")
    print(f"❌ 失败用例: {failed_count}")
    print(f"⚠️ 警告用例: {warning_count}")
    print(f"📊 总成功率: {passed_count / len(verification_results) * 100:.1f}%")
    
    # 显示详细结果
    print("\n📋 详细结果:")
    for result in verification_results:
        status_symbol = {
            'passed': '✅',
            'failed': '❌', 
            'warning': '⚠️',
            'skipped': '⏭️'
        }.get(result.overall_status.value, '❓')
        
        print(f"  {status_symbol} {result.case_id}: {result.summary}")
        
        # 显示失败的验证项
        failed_verifications = [v for v in result.individual_results 
                              if v.status.value == 'failed']
        if failed_verifications:
            for verification in failed_verifications:
                print(f"      ❌ {verification.test_name}: {verification.message}")
    
    print("\n🎉 验证流程完成！")
    print(f"📁 报告文件已生成到: {output_dir}")

def analyze_single_case(case_id: str, log_dir: str, matrix_file: str):
    """
    分析单个测试用例
    
    Args:
        case_id: 用例 ID
        log_dir: 日志目录
        matrix_file: 测试矩阵文件
    """
    print(f"🔍 分析单个用例: {case_id}")
    print("=" * 40)
    
    # 1. 加载期望行为
    expected_behaviors = parse_test_matrix(matrix_file)
    target_behavior = None
    
    for i, behavior in enumerate(expected_behaviors):
        # 根据索引生成 case_id
        generated_case_id = f"case_{i+1:03d}"
        if case_id == generated_case_id:
            target_behavior = behavior
            break
    
    if not target_behavior:
        print(f"❌ 未找到用例 {case_id} 的期望行为")
        return
    
    # 2. 加载日志
    parsed_logs_by_case = load_logs_from_directory(log_dir)
    
    if case_id not in parsed_logs_by_case:
        print(f"❌ 未找到用例 {case_id} 的日志数据")
        print(f"可用用例: {list(parsed_logs_by_case.keys())}")
        return
    
    parsed_logs = parsed_logs_by_case[case_id]
    
    # 3. 执行验证
    comparator = ResultComparator()
    result = comparator.compare_single_result(case_id, target_behavior, parsed_logs)
    
    # 4. 显示详细结果
    print(f"\n📊 用例 {case_id} 分析结果:")
    print(f"状态: {result.overall_status.value}")
    print(f"描述: {result.test_description}")
    print(f"摘要: {result.summary}")
    
    print(f"\n📈 指标数据:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")
    
    print(f"\n🔍 验证详情:")
    for verification in result.individual_results:
        status_symbol = {
            'passed': '✅',
            'failed': '❌',
            'warning': '⚠️',
            'skipped': '⏭️'
        }.get(verification.status.value, '❓')
        
        print(f"  {status_symbol} {verification.test_name}: {verification.message}")
        
        # 对于流量分布验证，显示更详细的信息
        if verification.test_name == "流量分布验证" and verification.details:
            version_results = verification.details.get('version_results', {})
            if version_results:
                print(f"      📊 详细分布:")
                for version, result in version_results.items():
                    count = result['request_count']
                    actual = result['actual_percentage']
                    expected = result['expected_weight']
                    deviation = result['deviation']
                    status_icon = "✅" if result['passed'] else "❌"
                    print(f"        {status_icon} {version}: {count}个请求 ({actual:.1%}) vs 期望({expected:.1%}) 偏差({deviation:.1%})")
        elif verification.details:
            # 其他验证类型显示原有详情
            for detail_key, detail_value in verification.details.items():
                if detail_key not in ['version_results', 'summary']:  # 避免重复显示
                    print(f"      {detail_key}: {detail_value}")

def main():
    """主程序入口"""
    parser = argparse.ArgumentParser(description='Istio 动态测试验证工具')
    
    parser.add_argument('--matrix', '-m', 
                       default='output_matrix.json',
                       help='测试矩阵文件路径')
    
    parser.add_argument('--logs', '-l',
                       default='results/envoy_logs',
                       help='日志目录路径')
    
    parser.add_argument('--output', '-o',
                       default='results/verification',
                       help='报告输出目录')
    
    parser.add_argument('--case', '-c',
                       help='分析单个用例（用例ID）')
    
    parser.add_argument('--demo', action='store_true',
                       help='运行演示模式（使用示例数据）')
    
    args = parser.parse_args()
    
    if args.demo:
        print("🧪 演示模式：创建示例数据并运行验证")
        create_demo_data()
        run_verification('demo_matrix.json', 'demo_logs', 'demo_results')
    elif args.case:
        analyze_single_case(args.case, args.logs, args.matrix)
    else:
        run_verification(args.matrix, args.logs, args.output)

def create_demo_data():
    """创建演示数据"""
    print("📝 创建演示数据...")
    
    # 创建示例测试矩阵
    demo_matrix = {
        "global_settings": {
            "ingress_url": "http://192.168.92.131:30476/productpage"
        },
        "test_cases": [
            {
                "case_id": "case_001",
                "description": "路由测试 - 请求路由到 reviews-v2",
                "type": "single_request",
                "request_params": {
                    "host": "reviews",
                    "headers": {"user-agent": "jason"}
                },
                "expected_outcome": {
                    "destination": "v2",
                    "note": "验证路由到 v2 版本"
                }
            },
            {
                "case_id": "case_002", 
                "description": "流量分布测试 - 80% v1, 20% v3",
                "type": "load_test",
                "request_params": {
                    "host": "reviews"
                },
                "load_params": {
                    "num_requests": 50,
                    "concurrency": 1
                },
                "expected_outcome": {
                    "distribution": {
                        "v1": "0.80",
                        "v3": "0.20"
                    },
                    "margin_of_error": "0.05"
                }
            }
        ]
    }
    
    with open('demo_matrix.json', 'w', encoding='utf-8') as f:
        json.dump(demo_matrix, f, ensure_ascii=False, indent=2)
    
    # 创建示例日志目录和文件
    os.makedirs('demo_logs', exist_ok=True)
    
    # 创建 case_001 的日志（路由到 v2）
    demo_log_v2 = '''[2024-01-15T10:30:15.123Z] "GET /reviews/2 HTTP/1.1" 200 - 0 157 45 12 "192.168.1.100" "jason" "abc123" "reviews" "10.244.1.15:9080"
[2024-01-15T10:30:16.456Z] "GET /reviews/2 HTTP/1.1" 200 - 0 161 52 15 "192.168.1.100" "jason" "def456" "reviews" "10.244.1.15:9080"'''
    
    with open('demo_logs/case_001_reviews-v2-abc123.log', 'w', encoding='utf-8') as f:
        f.write(demo_log_v2)
    
    # 创建 case_002 的日志（流量分布：40 个请求到 v1, 10 个请求到 v3）
    demo_log_v1 = '\n'.join([
        f'[2024-01-15T10:35:{i:02d}.{i*100:03d}Z] "GET /reviews/1 HTTP/1.1" 200 - 0 {150+i} {40+i} {10+i//5} "192.168.1.100" "curl/7.68.0" "req{i:03d}" "reviews" "10.244.1.16:9080"'
        for i in range(40)
    ])
    
    demo_log_v3 = '\n'.join([
        f'[2024-01-15T10:35:{i:02d}.{i*100:03d}Z] "GET /reviews/3 HTTP/1.1" 200 - 0 {160+i} {45+i} {12+i//3} "192.168.1.100" "curl/7.68.0" "req{i+40:03d}" "reviews" "10.244.1.17:9080"'
        for i in range(10)
    ])
    
    with open('demo_logs/case_002_reviews-v1-def456.log', 'w', encoding='utf-8') as f:
        f.write(demo_log_v1)
        
    with open('demo_logs/case_002_reviews-v3-ghi789.log', 'w', encoding='utf-8') as f:
        f.write(demo_log_v3)
    
    print("✅ 演示数据创建完成")

if __name__ == "__main__":
    main() 