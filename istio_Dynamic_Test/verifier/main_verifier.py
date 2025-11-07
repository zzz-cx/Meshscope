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
from datetime import datetime
from typing import Dict, List

from .log_parser import EnvoyLogParser, parse_logs_from_files
from .behavior_model import BehaviorModel, parse_test_matrix
from .result_comparator import ResultComparator, compare_batch_results
from .report_generator import ReportGenerator

def extract_http_results_from_traffic_driver(case_id: str) -> Dict:
    """
    从traffic_driver的执行结果中提取HTTP测试结果
    
    Args:
        case_id: 测试用例ID
        
    Returns:
        HTTP测试结果字典，包含状态码、响应时间等信息
    """
    import os
    import json
    import glob
    
    # 查找HTTP结果文件
    http_results_dir = "../results/http_results"
    if not os.path.exists(http_results_dir):
        print(f"⚠️  HTTP结果目录不存在: {http_results_dir}")
        return None
    
    # 查找匹配的HTTP结果文件
    pattern = os.path.join(http_results_dir, f"{case_id}_http_result_*.json")
    files = glob.glob(pattern)
    
    if not files:
        print(f"⚠️  未找到用例 {case_id} 的HTTP结果文件")
        return None
    
    # 获取最新的文件
    latest_file = max(files, key=os.path.getctime)
    
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            http_result = data.get('http_result', {})
            print(f"📊 从 {latest_file} 加载HTTP结果")
            return http_result
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"❌ 读取HTTP结果文件失败: {e}")
        return None

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
        
        # 解析文件名，支持多种格式：
        # - case_001_reviews_v2_pod-name.log (sidecar)
        # - case_001_gateway_istio-ingressgateway-pod.log (gateway)
        # - case_001_test503_reviews_pod-name.log (test)
        parts = filename.replace('.log', '').split('_')
        if len(parts) >= 2:
            case_id = f"{parts[0]}_{parts[1]}"  # case_001
            
            if case_id not in logs_by_case:
                logs_by_case[case_id] = {}
            
            # 读取日志内容
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 根据不同文件类型提取标识符
                if len(parts) >= 3 and parts[2] == 'gateway':
                    # Gateway日志：case_001_gateway_istio-ingressgateway-pod.log
                    pod_name = f"gateway_{parts[3]}" if len(parts) > 3 else "gateway_unknown"
                    log_type = "gateway"
                elif len(parts) >= 3 and parts[2] == 'test503':
                    # Test日志：case_001_test503_reviews_pod-name.log
                    pod_name = f"test503_{'_'.join(parts[3:])}"
                    log_type = "test"
                else:
                    # 普通sidecar日志：case_001_reviews_v2_pod-name.log
                    pod_name = '_'.join(parts[2:])
                    log_type = "sidecar"
                
                logs_by_case[case_id][pod_name] = content
                
                print(f"  ✅ 加载 {case_id} - {pod_name} ({log_type})")
                
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

def run_verification(matrix_file: str, log_dir: str, output_dir: str = "results/verification", istio_config_file: str = None):
    """
    运行完整的验证流程
    
    Args:
        matrix_file: 测试矩阵文件路径
        log_dir: 日志目录路径  
        output_dir: 输出目录路径
        istio_config_file: Istio配置文件路径（可选）
    """
    # 设置输出编码（Windows 兼容）
    import sys
    import io
    if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except:
            pass
    
    print("[INFO] 开始 Istio 动态测试验证流程")
    print("=" * 60)
    
    # 收集验证过程信息
    verification_process = {
        "start_time": datetime.now().isoformat(),
        "matrix_file": matrix_file,
        "log_dir": log_dir,
        "istio_config_file": istio_config_file,
        "steps": []
    }
    
    # 1. 解析测试矩阵，生成期望行为
    print("\n📋 第一步：解析测试矩阵")
    if istio_config_file:
        print(f"🔧 使用Istio配置文件: {istio_config_file}")
    
    step1_start = datetime.now()
    expected_behaviors = parse_test_matrix(matrix_file, istio_config_file)
    step1_end = datetime.now()
    
    # 记录第一步详情
    step1_info = {
        "step": 1,
        "name": "解析测试矩阵",
        "start_time": step1_start.isoformat(),
        "end_time": step1_end.isoformat(),
        "duration_ms": (step1_end - step1_start).total_seconds() * 1000,
        "matrix_file": matrix_file,
        "istio_config_file": istio_config_file,
        "parsed_behaviors_count": len(expected_behaviors),
        "behaviors_summary": []
    }
    
    if not expected_behaviors:
        print("❌ 未能解析到任何期望行为，检查测试矩阵文件")
        step1_info["error"] = "未能解析到任何期望行为"
        verification_process["steps"].append(step1_info)
        return
    
    print(f"✅ 成功解析 {len(expected_behaviors)} 个期望行为")
    
    # 记录期望行为详情
    for i, behavior in enumerate(expected_behaviors):
        behavior_summary = {
            "case_id": f"case_{i+1:03d}",
            "test_type": behavior.test_type.value,
            "policy_type": behavior.policy_type.value,
            "description": behavior.description,
            "expected_destination": behavior.expected_destination,
            "expected_distribution": behavior.expected_distribution,
            "expected_retry_attempts": behavior.expected_retry_attempts,
            "expected_per_try_timeout": behavior.expected_per_try_timeout,
            "expected_trip_threshold": behavior.expected_trip_threshold,
            "expected_trip_timeout": behavior.expected_trip_timeout,
            "expected_recovery_time": behavior.expected_recovery_time
        }
        step1_info["behaviors_summary"].append(behavior_summary)
        
        # 打印详细信息
        print(f"   📝 Case {i+1:03d}: {behavior.policy_type.value} - {behavior.description}")
        if behavior.expected_retry_attempts:
            print(f"      🔄 重试: {behavior.expected_retry_attempts}次, 单次超时: {behavior.expected_per_try_timeout}s")
        if behavior.expected_trip_threshold:
            print(f"      ⚡ 熔断: 阈值{behavior.expected_trip_threshold}, 恢复时间: {behavior.expected_recovery_time}s")
    
    verification_process["steps"].append(step1_info)
    
    # 2. 加载和解析日志
    print("\n📄 第二步：加载和解析日志")
    step2_start = datetime.now()
    parsed_logs_by_case = load_logs_from_directory(log_dir)
    step2_end = datetime.now()
    
    # 记录第二步详情
    step2_info = {
        "step": 2,
        "name": "加载和解析日志",
        "start_time": step2_start.isoformat(),
        "end_time": step2_end.isoformat(),
        "duration_ms": (step2_end - step2_start).total_seconds() * 1000,
        "log_dir": log_dir,
        "cases_with_logs_count": len(parsed_logs_by_case),
        "log_summary": []
    }
    
    if not parsed_logs_by_case:
        print("❌ 未能加载到任何日志数据，检查日志目录")
        step2_info["error"] = "未能加载到任何日志数据"
        verification_process["steps"].append(step2_info)
        return
    
    print(f"✅ 成功加载 {len(parsed_logs_by_case)} 个用例的日志")
    
    # 记录日志解析详情
    total_log_entries = 0
    for case_id, parsed_logs in parsed_logs_by_case.items():
        case_log_entries = sum(len(entries) for entries in parsed_logs.values())
        total_log_entries += case_log_entries
        
        pod_count = len(parsed_logs)
        success_entries = sum(len([e for e in entries if e.is_success]) for entries in parsed_logs.values())
        error_entries = sum(len([e for e in entries if e.is_error]) for entries in parsed_logs.values())
        
        log_case_summary = {
            "case_id": case_id,
            "total_entries": case_log_entries,
            "pod_count": pod_count,
            "success_entries": success_entries,
            "error_entries": error_entries,
            "success_rate": success_entries / case_log_entries if case_log_entries > 0 else 0,
            "pods": list(parsed_logs.keys())
        }
        step2_info["log_summary"].append(log_case_summary)
        
        success_rate = success_entries / case_log_entries if case_log_entries > 0 else 0
        print(f"   📊 {case_id}: {case_log_entries}条日志, {pod_count}个Pod, 成功率{success_rate:.1%}")
    
    step2_info["total_log_entries"] = total_log_entries
    verification_process["steps"].append(step2_info)
    
    # 3. 执行对比验证
    print("\n[STEP 3] 第三步：执行对比验证")
    step3_start = datetime.now()
    comparator = ResultComparator()
    # 传入 http_results 目录，启用多维度验证（HTTP + 日志）
    verification_results = compare_batch_results(
        expected_behaviors,
        parsed_logs_by_case,
        comparator,
        http_results_dir=os.path.join(os.path.dirname(log_dir), 'http_results')
    )
    
    step3_end = datetime.now()
    
    # 记录第三步详情
    step3_info = {
        "step": 3,
        "name": "执行对比验证",
        "start_time": step3_start.isoformat(),
        "end_time": step3_end.isoformat(),
        "duration_ms": (step3_end - step3_start).total_seconds() * 1000,
        "verification_results_count": len(verification_results) if verification_results else 0,
        "verification_summary": []
    }
    
    if not verification_results:
        print("❌ 验证过程中出现错误")
        step3_info["error"] = "验证过程中出现错误"
        verification_process["steps"].append(step3_info)
        return
    
    print(f"✅ 完成 {len(verification_results)} 个用例的验证")
    
    # 记录验证结果详情
    passed_count = 0
    failed_count = 0
    warning_count = 0
    
    for result in verification_results:
        if result.overall_status.value == "passed":
            passed_count += 1
        elif result.overall_status.value == "failed":
            failed_count += 1
        elif result.overall_status.value == "warning":
            warning_count += 1
        
        # 收集各维度验证结果
        dimension_results = {}
        for verification in result.individual_results:
            dimension_results[verification.test_name] = {
                "status": verification.status.value,
                "message": verification.message,
                "expected_value": verification.expected_value,
                "actual_value": verification.actual_value,
                "deviation": verification.deviation,
                "details": verification.details
            }
        
        verification_case_summary = {
            "case_id": result.case_id,
            "test_description": result.test_description,
            "overall_status": result.overall_status.value,
            "dimension_results": dimension_results,
            "summary": result.summary,
            "metrics": result.metrics
        }
        step3_info["verification_summary"].append(verification_case_summary)
        
        # 打印验证详情
        status_icon = {"passed": "✅", "failed": "❌", "warning": "⚠️"}.get(result.overall_status.value, "❓")
        print(f"   {status_icon} {result.case_id}: {result.overall_status.value.upper()}")
        
        # 打印各维度结果
        for verification in result.individual_results:
            dim_icon = {"passed": "✅", "failed": "❌", "warning": "⚠️", "skipped": "⏭️"}.get(verification.status.value, "❓")
            print(f"      {dim_icon} {verification.test_name}: {verification.message}")
    
    step3_info["passed_count"] = passed_count
    step3_info["failed_count"] = failed_count
    step3_info["warning_count"] = warning_count
    step3_info["total_count"] = len(verification_results)
    verification_process["steps"].append(step3_info)
    
    # 4. 生成报告
    print("\n📊 第四步：生成验证报告")
    step4_start = datetime.now()
    os.makedirs(output_dir, exist_ok=True)
    
    # 加载测试配置
    test_config = None
    try:
        with open(matrix_file, 'r', encoding='utf-8') as f:
            test_config = json.load(f)
    except Exception as e:
        print(f"⚠️ 无法加载测试配置: {e}")
    
    # 完成验证过程记录
    verification_process["end_time"] = datetime.now().isoformat()
    verification_process["total_duration_ms"] = (datetime.now() - datetime.fromisoformat(verification_process["start_time"])).total_seconds() * 1000
    
    # 将验证过程信息添加到测试配置中
    if test_config is None:
        test_config = {}
    test_config["verification_process"] = verification_process
    
    # 生成报告
    report_generator = ReportGenerator(output_dir)
    report_files = report_generator.generate_comprehensive_report(
        verification_results, test_config, "istio_verification"
    )
    step4_end = datetime.now()
    
    # 记录第四步详情
    step4_info = {
        "step": 4,
        "name": "生成验证报告",
        "start_time": step4_start.isoformat(),
        "end_time": step4_end.isoformat(),
        "duration_ms": (step4_end - step4_start).total_seconds() * 1000,
        "output_dir": output_dir,
        "generated_files": list(report_files.values()) if report_files else []
    }
    verification_process["steps"].append(step4_info)
    
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

def analyze_single_case(case_id: str, log_dir: str, matrix_file: str, istio_config_file: str = None):
    """
    分析单个测试用例
    
    Args:
        case_id: 用例 ID
        log_dir: 日志目录
        matrix_file: 测试矩阵文件
    """
    print(f"[ANALYZE] 分析单个用例: {case_id}")
    print("=" * 40)
    
    # 1. 加载期望行为
    expected_behaviors = parse_test_matrix(matrix_file, istio_config_file)
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
    
    # 3. 执行验证 (多维度验证)
    comparator = ResultComparator()
    
    # 尝试从traffic_driver结果中获取HTTP结果
    http_results = extract_http_results_from_traffic_driver(case_id)
    
    result = comparator.compare_single_result(case_id, target_behavior, parsed_logs, http_results)
    
    # 4. 显示详细结果
    print(f"\n📊 用例 {case_id} 分析结果:")
    print(f"状态: {result.overall_status.value}")
    print(f"描述: {result.test_description}")
    print(f"摘要: {result.summary}")
    
    print(f"\n📈 指标数据:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")
    
    print(f"\n[DETAIL] 验证详情:")
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
    
    parser.add_argument('--config', '-cfg',
                       help='Istio配置文件路径（可选，用于提取重试、熔断等时间参数）')
    
    args = parser.parse_args()
    
    if args.demo:
        print("🧪 演示模式：创建示例数据并运行验证")
        create_demo_data()
        run_verification('demo_matrix.json', 'demo_logs', 'demo_results')
    elif args.case:
        analyze_single_case(args.case, args.logs, args.matrix, args.config)
    else:
        run_verification(args.matrix, args.logs, args.output, args.config)

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