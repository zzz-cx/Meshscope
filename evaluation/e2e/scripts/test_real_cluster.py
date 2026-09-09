#!/usr/bin/env python3
"""
E2E Test with Real Cluster脚本
"""

import sys
import json
from pathlib import Path

# 添加items目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from evaluation.e2e.scripts.e2e_evaluator import E2EEvaluator

def main():
    print("=" * 80)
    print("E2E Test with Real Cluster")
    print("=" * 80)
    
    # 创建评估器
    evaluator = E2EEvaluator()
    
    # 从JSON文件读取测试用例
    test_cases_file = project_root / "evaluation" / "e2e" / "test_cases" / "e2e_test_cases_cluster.json"
    with open(test_cases_file, 'r', encoding='utf-8') as f:
        test_suite = json.load(f)
    
    # 使用第一测试用例
    test_case = test_suite['test_cases'][0]
    
    print(f"\nTest Configuration:")
    if test_case.get('use_fetched_configs'):
        print(f"  - Using fetched configs: {test_case.get('fetched_configs_dir', 'N/A')}")
    elif test_case.get('fetch_from_cluster'):
        print(f"  - Cluster host: {test_case['cluster_config']['vm_host']}")
        print(f"  - Namespace: {test_case['cluster_config']['namespace']}")
        print(f"  - Fetch from cluster enabled: True")
    if test_case.get('enable_traffic_test'):
        print(f"  - Traffic test: {test_case.get('traffic_config', {}).get('target_url', 'N/A')}")
    print()
    
    # 运行测试
    print("Starting E2E test execution...\n")
    result = evaluator.run_e2e_test(test_case)
    
    # 打印结果
    print("\n" + "=" * 80)
    print("Test Results")
    print("=" * 80)
    print(f"Test ID: {result['test_id']}")
    print(f"Test Name: {result['name']}")
    print(f"Overall Result: {'SUCCESS' if result['overall_success'] else 'FAILED'}")
    print(f"Execution Time: {result['execution_time']:.2f}s")
    
    print(f"\nStage Execution Status:")
    for stage_name, stage_result in result['stages'].items():
        if isinstance(stage_result, dict):
            success = stage_result.get('success', stage_result.get('skipped', False))
            status = "[OK]" if success else ("[SKIP]" if stage_result.get('skipped') else "[FAIL]")
            print(f"  {stage_name}: {status}")
            
            # 显示关键信息
            if stage_name == "0_fetch" and stage_result.get('success'):
                print(f"    - Config changes: {stage_result.get('changes_count', 0)} items")
                print(f"    - Control plane: {stage_result.get('control_plane_dir', 'N/A')}")
            elif stage_name == "1_parsing" and stage_result.get('success'):
                print(f"    - Config source: {stage_result.get('config_source', 'N/A')}")
                print(f"    - Config dir: {stage_result.get('config_dir', 'N/A')}")
            elif stage_name == "2_static_analysis" and stage_result.get('success'):
                summary = stage_result.get('summary', {})
                print(f"    - Services: {summary.get('total_services', 0)}")
                print(f"    - Policies: {summary.get('total_policies', 0)}")
                print(f"    - Edges: {summary.get('total_edges', 0)}")
                print(f"    - Issues: {stage_result.get('inconsistencies_count', 0)}")
            elif stage_name == "3_traffic_test" and stage_result.get('success'):
                print(f"    - Total requests: {stage_result.get('request_count', 0)}")
                print(f"    - Successful: {stage_result.get('success_count', 0)}")
                print(f"    - Failed: {stage_result.get('failure_count', 0)}")
                print(f"    - Success rate: {stage_result.get('success_rate', 0):.1%}")
                print(f"    - Avg response time: {stage_result.get('avg_response_time', 0):.0f}ms")
            elif stage_name == "4_dynamic_analysis" and stage_result.get('success'):
                print(f"    - Anomalies found: {stage_result.get('anomalies_count', 0)} ")
                for anomaly in stage_result.get('anomalies', [])[:3]:  # Show first 3
                    print(f"      * {anomaly.get('type')}: {anomaly.get('description')}")
    
    if result.get('errors'):
        print(f"\nError Messages:")
        for error in result['errors']:
            print(f"  - {error}")
    
    # 保存详细结果（清理不可序列化的对象）
    def clean_for_json(obj):
        """递归清理不可序列化的对象"""
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_for_json(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return clean_for_json(obj.__dict__)
        else:
            try:
                json.dumps(obj)
                return obj
            except:
                return str(obj)
    
    output_file = project_root / "evaluation" / "e2e" / "results" / "test_real_cluster_result.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(clean_for_json(result), f, ensure_ascii=False, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")
    
    return 0 if result['overall_success'] else 1

if __name__ == "__main__":
    sys.exit(main())

