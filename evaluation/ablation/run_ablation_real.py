#!/usr/bin/env python3
"""
消融实验 — 真实集群版

完整流程：
  1. 将测试配置 YAML 注入到集群
  2. 导出控制面/数据面配置（export_control_plane_config / export_data_plane_config）
  3. 用 istio_config_parser (main_parser) 做静态分析，检查 VS-DR subset 等不一致
  4. 用 istio_Dynamic_Test (generator → traffic_driver → verifier) 做动态测试
  5. 对比两种方法的检测结果

Usage:
    python run_ablation_real.py --case missing_subset_v2 --ssh-host 192.168.92.131 --ssh-password xxx
    python run_ablation_real.py --case missing_subset_v2 --method static   # 只跑静态
    python run_ablation_real.py --case missing_subset_v2 --method dynamic  # 只跑动态
    python run_ablation_real.py --list                                      # 列出所有用例
"""

import os
import sys
import json
import yaml
import time
import argparse
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

CONTROL_PLANE_DIR = os.path.join(PROJECT_ROOT, "istio_config_parser", "istio_monitor", "istio_control_config")
DATA_PLANE_DIR = os.path.join(PROJECT_ROOT, "istio_config_parser", "istio_monitor", "istio_sidecar_config")

GROUND_TRUTH = {
    "missing_subset_v2": {
        "has_fault": True,
        "fault_types": ["missing_subset"],
        "description": "VS -> subset v2, DR only defines v1",
        "namespace": "default",
    },
    "weight_not_100": {
        "has_fault": True,
        "fault_types": ["weight_error"],
        "description": "weight sum = 80%, not 100%",
        "namespace": "default",
    },
    "weight_exceed_100": {
        "has_fault": True,
        "fault_types": ["weight_error", "routing_conflict"],
        "description": "weight sum = 150%, exceeds 100%",
        "namespace": "default",
    },
    "correct_baseline": {
        "has_fault": False,
        "fault_types": ["correct"],
        "description": "correct config (negative control)",
        "namespace": "default",
    },
    "subset_host_mismatch": {
        "has_fault": True,
        "fault_types": ["missing_subset"],
        "description": "VS host != DR host",
        "namespace": "default",
    },
    "timeout_too_short": {
        "has_fault": True,
        "fault_types": ["timeout_error"],
        "description": "timeout 0.1s too short",
        "namespace": "default",
    },
}


# ─── 集群操作工具 ─────────────────────────────────────────────────────────────

class ClusterOps:
    """通过 SSH 远程操作 K8s 集群"""

    def __init__(self, ssh_host: str, ssh_user: str = "root", ssh_password: str = "",
                 namespace: str = "default"):
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.namespace = namespace
        self._ssh = None

    def _get_ssh(self):
        if self._ssh is None:
            import paramiko
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(self.ssh_host, username=self.ssh_user, password=self.ssh_password)
        return self._ssh

    def exec_remote(self, cmd: str, timeout: int = 60) -> tuple:
        ssh = self._get_ssh()
        logger.info(f"  [SSH] {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err

    def apply_yaml(self, yaml_path: str) -> bool:
        """将 YAML 配置注入集群"""
        logger.info(f"  [注入] kubectl apply -f ... -n {self.namespace}")
        with open(yaml_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 通过 SSH 传送 YAML 内容并 apply
        safe_content = content.replace("'", "'\\''")
        cmd = f"echo '{safe_content}' | kubectl apply -n {self.namespace} -f -"
        out, err = self.exec_remote(cmd)
        logger.info(f"    stdout: {out.strip()}")
        if err.strip():
            logger.warning(f"    stderr: {err.strip()}")
        return "configured" in out or "created" in out or "unchanged" in out

    def delete_yaml(self, yaml_path: str) -> bool:
        """从集群删除测试配置"""
        logger.info(f"  [清理] kubectl delete -f ... -n {self.namespace}")
        with open(yaml_path, "r", encoding="utf-8") as f:
            content = f.read()
        safe_content = content.replace("'", "'\\''")
        cmd = f"echo '{safe_content}' | kubectl delete -n {self.namespace} -f - --ignore-not-found"
        out, err = self.exec_remote(cmd)
        logger.info(f"    stdout: {out.strip()}")
        return True

    def wait_for_sync(self, seconds: int = 10):
        """等待 Istio 配置同步到数据面"""
        logger.info(f"  [等待] {seconds}s 让 Istio 将配置下发到 Envoy...")
        time.sleep(seconds)

    def close(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None


# ─── 静态分析（使用真实的 istio_config_parser） ────────────────────────────────

def run_static_analysis(namespace: str = "default") -> Dict[str, Any]:
    """
    使用 istio_config_parser.main_parser 做静态分析。
    前提：控制面和数据面配置已经导出到本地目录。
    """
    logger.info("=" * 50)
    logger.info("[静态分析] 使用 istio_config_parser")
    logger.info("=" * 50)

    from istio_config_parser.main_parser import parse_control_plane_from_dir, parse_data_plane_from_dir

    logger.info(f"  控制面目录: {CONTROL_PLANE_DIR}")
    logger.info(f"  数据面目录: {DATA_PLANE_DIR}")

    result = {"method": "static_real", "detected_faults": [], "raw": {}}

    try:
        cp = parse_control_plane_from_dir(CONTROL_PLANE_DIR, namespace=namespace)
        dp = parse_data_plane_from_dir(DATA_PLANE_DIR)
        result["raw"]["control_plane_services"] = list(cp.get("serviceRelations", {}).keys())
        result["raw"]["data_plane_services"] = list(dp.get("serviceRelations", {}).keys())

        # 用 StaticAnalyzer 做完整的一致性检查
        from consistency_checker.core.static_analyzer import StaticAnalyzer
        analyzer = StaticAnalyzer(config_dir=CONTROL_PLANE_DIR, namespace=namespace)
        analysis = analyzer.analyze()

        issues = analysis.get("plane_consistency_issues", [])
        result["raw"]["plane_consistency_issues"] = issues

        for issue in issues:
            result["detected_faults"].append({
                "fault_type": issue["type"],
                "severity": issue.get("severity", "unknown"),
                "description": issue.get("description", ""),
                "details": issue,
            })

        # 额外输出服务的 subset/weight 信息便于分析
        for svc_name, rels in cp.get("serviceRelations", {}).items():
            subsets = [s["name"] for s in rels.get("subsets", [])]
            weights = rels.get("weights", {})
            vs_list = rels.get("incomingVirtualServices", [])
            if subsets or weights or vs_list:
                logger.info(f"  [CP] {svc_name}: subsets={subsets}, weights={weights}, "
                            f"VS count={len(vs_list)}")

        for svc_name, rels in dp.get("serviceRelations", {}).items():
            weights = rels.get("weights", {})
            if weights:
                logger.info(f"  [DP] {svc_name}: weights={weights}")

    except Exception as e:
        logger.error(f"  [静态分析失败] {e}")
        import traceback
        traceback.print_exc()
        result["error"] = str(e)

    result["has_fault"] = len(result["detected_faults"]) > 0
    result["fault_types"] = list({f["fault_type"] for f in result["detected_faults"]})
    logger.info(f"  [静态结果] 检出故障数={len(result['detected_faults'])}, 类型={result['fault_types']}")
    return result


# ─── 动态测试（使用真实的 istio_Dynamic_Test） ─────────────────────────────────

def run_dynamic_test(
    cluster: ClusterOps,
    config_path: str,
    namespace: str = "default",
    ingress_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 istio_Dynamic_Test 做动态测试。
    流程：生成测试矩阵 → 驱动流量 → 验证结果
    """
    logger.info("=" * 50)
    logger.info("[动态测试] 使用 istio_Dynamic_Test")
    logger.info("=" * 50)

    result = {"method": "dynamic_real", "detected_faults": [], "raw": {}}

    if not ingress_url:
        ingress_url = f"http://{cluster.ssh_host}:30476/productpage"

    try:
        # 阶段 1: 从注入的配置生成 istio_config.json（供 generator 使用）
        docs = _parse_yaml(config_path)
        istio_config = _build_istio_config_json(docs, namespace)

        tmp_config = os.path.join(RESULTS_DIR, "tmp_istio_config.json")
        tmp_matrix = os.path.join(RESULTS_DIR, "tmp_test_matrix.json")
        os.makedirs(RESULTS_DIR, exist_ok=True)

        with open(tmp_config, "w", encoding="utf-8") as f:
            json.dump(istio_config, f, indent=2, ensure_ascii=False)

        # 阶段 2: 生成测试矩阵
        logger.info("  [阶段1] 生成测试矩阵...")
        from istio_Dynamic_Test.internal.testcase.generators import TestCaseGenerator

        service_deps_file = os.path.join(PROJECT_ROOT, "istio_Dynamic_Test", "service_dependencies.json")
        if not os.path.exists(service_deps_file):
            service_deps_file = _create_minimal_deps(docs, namespace)

        gen = TestCaseGenerator(tmp_config, service_deps_file, namespace=namespace)
        test_cases = gen.generate()
        matrix_data = {"global_settings": {"ingress_url": ingress_url}, "test_cases": test_cases}

        with open(tmp_matrix, "w", encoding="utf-8") as f:
            json.dump(matrix_data, f, indent=2, ensure_ascii=False)

        logger.info(f"  [阶段1] 生成 {len(test_cases)} 个测试用例")
        result["raw"]["test_cases_count"] = len(test_cases)
        result["raw"]["test_cases"] = test_cases

        if not test_cases:
            logger.warning("  [动态] 没有生成测试用例，跳过流量驱动")
            result["has_fault"] = False
            result["fault_types"] = []
            return result

        # 阶段 3: 驱动流量（简化版 — 直接在远程执行 curl/hey）
        logger.info("  [阶段2] 驱动测试流量...")
        dynamic_faults = _drive_traffic_and_analyze(cluster, test_cases, ingress_url, namespace)
        result["detected_faults"].extend(dynamic_faults)

    except Exception as e:
        logger.error(f"  [动态测试失败] {e}")
        import traceback
        traceback.print_exc()
        result["error"] = str(e)

    result["has_fault"] = len(result["detected_faults"]) > 0
    result["fault_types"] = list({f["fault_type"] for f in result["detected_faults"]})
    logger.info(f"  [动态结果] 检出故障数={len(result['detected_faults'])}, 类型={result['fault_types']}")
    return result


def _drive_traffic_and_analyze(
    cluster: ClusterOps,
    test_cases: List[Dict],
    ingress_url: str,
    namespace: str,
) -> List[Dict]:
    """发送请求并分析响应，检测运行时异常"""
    faults = []
    for tc in test_cases:
        case_id = tc.get("case_id", "unknown")
        case_type = tc.get("case_type", "")
        url = tc.get("url", ingress_url)
        method = tc.get("method", "GET")
        headers = tc.get("headers", {})
        expected = tc.get("expected_behavior", {})
        test_type = tc.get("test_type", "single_request")

        logger.info(f"    [{case_id}] type={case_type}, url={url}")

        header_args = " ".join(f'-H "{k}: {v}"' for k, v in headers.items())

        if test_type == "load_test":
            concurrency = tc.get("concurrency", 5)
            count = tc.get("request_count", 50)
            cmd = f'hey -n {count} -c {concurrency} {header_args} "{url}" 2>&1 | tail -20'
            out, err = cluster.exec_remote(cmd, timeout=120)

            exp_weights = expected.get("weights", {})
            if exp_weights:
                actual_503_rate = _parse_error_rate(out)
                if actual_503_rate > 0.1:
                    faults.append({
                        "fault_type": "weight_error",
                        "severity": "medium",
                        "description": f"[{case_id}] 负载测试 503 错误率 {actual_503_rate:.1%}，流量分配可能异常",
                        "details": {"case_id": case_id, "error_rate": actual_503_rate, "raw_output": out[:500]},
                    })
        else:
            cmd = f'curl -s -o /dev/null -w "%{{http_code}} %{{time_total}}" {header_args} "{url}"'
            out, err = cluster.exec_remote(cmd, timeout=30)
            parts = out.strip().split()
            status_code = int(parts[0]) if parts else 0
            response_time = float(parts[1]) if len(parts) > 1 else 0

            exp_status = expected.get("status_code", 200)
            if status_code == 503:
                faults.append({
                    "fault_type": "missing_subset",
                    "severity": "high",
                    "description": f"[{case_id}] 返回 503 (No Route)，目标 subset/cluster 可能不存在",
                    "details": {"case_id": case_id, "status_code": status_code, "expected": exp_status},
                })
            elif status_code == 504 or (expected.get("timeout") and response_time > expected.get("timeout", 999)):
                faults.append({
                    "fault_type": "timeout_error",
                    "severity": "medium",
                    "description": f"[{case_id}] 请求超时 (status={status_code}, time={response_time:.2f}s)",
                    "details": {"case_id": case_id, "status_code": status_code, "time": response_time},
                })
            elif status_code != exp_status and exp_status:
                faults.append({
                    "fault_type": "routing_error",
                    "severity": "medium",
                    "description": f"[{case_id}] 状态码 {status_code} != 期望 {exp_status}",
                    "details": {"case_id": case_id, "actual": status_code, "expected": exp_status},
                })

    return faults


def _parse_error_rate(hey_output: str) -> float:
    """从 hey 输出中提取错误率"""
    import re
    total = 0
    errors = 0
    for line in hey_output.split("\n"):
        m = re.search(r"\[200\]\s+(\d+)\s+responses", line)
        if m:
            total += int(m.group(1))
        m = re.search(r"\[503\]\s+(\d+)\s+responses", line)
        if m:
            errors += int(m.group(1))
    # 尝试从 Status code distribution 解析
    for line in hey_output.split("\n"):
        m = re.search(r"\[503\]\s+(\d+)\s+responses", line)
        if m:
            errors = int(m.group(1))
        m = re.search(r"(\d+) requests done", line, re.IGNORECASE)
        if m:
            total = int(m.group(1))
    return errors / total if total > 0 else 0


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _parse_yaml(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f.read()) if d]


def _build_istio_config_json(docs: List[Dict], namespace: str) -> Dict:
    """将 YAML docs 转成 TestCaseGenerator 需要的 istio_config.json 格式"""
    config: Dict[str, List] = {
        "virtualservices": [],
        "destinationrules": [],
        "gateways": [],
        "services": [],
        "envoyfilters": [],
    }
    kind_map = {
        "VirtualService": "virtualservices",
        "DestinationRule": "destinationrules",
        "Gateway": "gateways",
        "Service": "services",
        "EnvoyFilter": "envoyfilters",
    }
    for doc in docs:
        key = kind_map.get(doc.get("kind"))
        if key:
            config[key].append(doc)
    return config


def _create_minimal_deps(docs: List[Dict], namespace: str) -> str:
    """创建最小的 service_dependencies.json"""
    services = set()
    for doc in docs:
        kind = doc.get("kind", "")
        if kind in ("VirtualService", "DestinationRule"):
            name = doc.get("metadata", {}).get("name", "")
            if name:
                services.add(name)
    deps = {svc: [] for svc in services}
    path = os.path.join(RESULTS_DIR, "tmp_service_deps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(deps, f, indent=2)
    return path


# ─── 导出配置 ─────────────────────────────────────────────────────────────────

def export_configs(cluster: ClusterOps, namespace: str = "default"):
    """从集群导出控制面+数据面配置到本地"""
    logger.info("=" * 50)
    logger.info("[导出] 从集群导出控制面和数据面配置")
    logger.info("=" * 50)

    # 导出控制面
    try:
        from istio_config_parser.istio_monitor.export_control_plane_config import export_control_plane_config
        logger.info(f"  [控制面] -> {CONTROL_PLANE_DIR}")
        export_control_plane_config(
            output_dir=CONTROL_PLANE_DIR,
            k8s_host=cluster.ssh_host,
        )
    except Exception as e:
        logger.error(f"  [控制面导出失败] {e}")

    # 导出数据面
    try:
        from istio_config_parser.istio_monitor.export_data_plane_config import export_data_plane_config
        logger.info(f"  [数据面] -> {DATA_PLANE_DIR}")
        export_data_plane_config(
            output_dir=DATA_PLANE_DIR,
            method="istioctl",
            namespace=namespace,
        )
    except Exception as e:
        logger.warning(f"  [数据面导出警告] {e}，将使用已有的本地配置")


# ─── 消融主流程 ───────────────────────────────────────────────────────────────

def run_ablation_real(
    case_name: str,
    ssh_host: str,
    ssh_user: str = "root",
    ssh_password: str = "",
    method: Optional[str] = None,
    skip_inject: bool = False,
    skip_export: bool = False,
    ingress_url: Optional[str] = None,
):
    gt = GROUND_TRUTH.get(case_name)
    if not gt:
        logger.error(f"未知用例: {case_name}, 可选: {list(GROUND_TRUTH.keys())}")
        return

    config_path = os.path.join(CONFIGS_DIR, f"{case_name}.yaml")
    if not os.path.exists(config_path):
        logger.error(f"配置文件不存在: {config_path}")
        return

    namespace = gt.get("namespace", "default")
    cluster = ClusterOps(ssh_host, ssh_user, ssh_password, namespace)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"消融实验 (真实集群): {case_name}")
    logger.info(f"  描述: {gt['description']}")
    logger.info(f"  预期故障: {gt['fault_types']}")
    logger.info(f"  集群: {ssh_host}")
    logger.info("=" * 60)

    results = {"case_name": case_name, "ground_truth": gt}

    try:
        # ── 步骤 1: 注入配置 ──
        if not skip_inject:
            logger.info("\n[步骤1] 注入测试配置到集群...")
            ok = cluster.apply_yaml(config_path)
            if not ok:
                logger.error("  配置注入失败!")
                return
            cluster.wait_for_sync(15)
        else:
            logger.info("\n[步骤1] 跳过注入（--skip-inject）")

        # ── 步骤 2: 导出配置 ──
        if not skip_export:
            logger.info("\n[步骤2] 导出集群配置到本地...")
            export_configs(cluster, namespace)
        else:
            logger.info("\n[步骤2] 跳过导出（--skip-export），使用现有本地配置")

        # ── 步骤 3: 静态分析 ──
        if method in (None, "static"):
            logger.info("\n[步骤3] 静态分析...")
            sr = run_static_analysis(namespace)
            results["static_result"] = sr
            logger.info(f"\n{'='*40}")
            logger.info(f"  [静态] 检出={sr['has_fault']}, 故障类型={sr['fault_types']}")
            for f in sr["detected_faults"]:
                logger.info(f"    -> {f['fault_type']}: {f['description']}")

        # ── 步骤 4: 动态测试 ──
        if method in (None, "dynamic"):
            logger.info("\n[步骤4] 动态测试...")
            dr = run_dynamic_test(cluster, config_path, namespace, ingress_url)
            results["dynamic_result"] = dr
            logger.info(f"\n{'='*40}")
            logger.info(f"  [动态] 检出={dr['has_fault']}, 故障类型={dr['fault_types']}")
            for f in dr["detected_faults"]:
                logger.info(f"    -> {f['fault_type']}: {f['description']}")

    finally:
        # ── 步骤 5: 清理 ──
        if not skip_inject:
            logger.info("\n[步骤5] 清理测试配置...")
            cluster.delete_yaml(config_path)
        cluster.close()

    # ── 保存结果 ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(RESULTS_DIR, f"ablation_real_{case_name}_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_serialize_result(results), f, indent=2, ensure_ascii=False)
    logger.info(f"\n结果已保存: {out_path}")

    # ── 打印对比 ──
    _print_comparison(results, method)


def _serialize_result(results: Dict) -> Dict:
    out = {"case_name": results["case_name"], "ground_truth": results["ground_truth"]}
    for key in ("static_result", "dynamic_result"):
        r = results.get(key)
        if r:
            out[key] = {
                "method": r["method"],
                "has_fault": r["has_fault"],
                "fault_types": r["fault_types"],
                "detected_faults": r["detected_faults"],
            }
    return out


def _print_comparison(results: Dict, method: Optional[str]):
    print("\n" + "=" * 70)
    print(f"  消融实验结果: {results['case_name']}")
    print(f"  Ground Truth: has_fault={results['ground_truth']['has_fault']}, "
          f"types={results['ground_truth']['fault_types']}")
    print("-" * 70)

    for m in ("static", "dynamic"):
        if method and method != m:
            continue
        r = results.get(f"{m}_result")
        if not r:
            continue
        name = "Static" if m == "static" else "Dynamic"
        print(f"  [{name:>8}] has_fault={r['has_fault']}, fault_types={r['fault_types']}")
        for f in r["detected_faults"]:
            print(f"             -> {f['fault_type']}: {f['description'][:80]}")

    print("=" * 70)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="消融实验 (真实集群): 注入配置 -> 静态/动态检测 -> 对比结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--case", type=str, help="测试用例名 (不含 .yaml)")
    parser.add_argument("--list", action="store_true", help="列出所有可用用例")
    parser.add_argument("--method", choices=["static", "dynamic"], help="只运行静态或动态")
    parser.add_argument("--ssh-host", default=os.getenv("SSH_HOST", "192.168.92.131"), help="集群节点 SSH 地址")
    parser.add_argument("--ssh-user", default=os.getenv("SSH_USER", "root"))
    parser.add_argument("--ssh-password", default=os.getenv("SSH_PASSWORD", ""))
    parser.add_argument("--ingress-url", default=None, help="Ingress URL (默认自动拼接)")
    parser.add_argument("--skip-inject", action="store_true", help="跳过注入步骤（配置已在集群中）")
    parser.add_argument("--skip-export", action="store_true", help="跳过导出步骤（使用现有本地配置）")
    args = parser.parse_args()

    if args.list:
        print("\n可用测试用例:")
        for name, gt in GROUND_TRUTH.items():
            print(f"  {name:<26} {gt['description']}")
        print()
        return

    if not args.case:
        parser.error("请指定 --case <用例名> 或使用 --list 查看可用用例")

    run_ablation_real(
        case_name=args.case,
        ssh_host=args.ssh_host,
        ssh_user=args.ssh_user,
        ssh_password=args.ssh_password,
        method=args.method,
        skip_inject=args.skip_inject,
        skip_export=args.skip_export,
        ingress_url=args.ingress_url,
    )


if __name__ == "__main__":
    main()
