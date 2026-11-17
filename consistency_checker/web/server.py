"""
Web可视化服务器

提供交互式Web界面展示一致性验证结果
包括静态分析和动态测试功能
"""

import os
import sys
import json
import logging
import subprocess
import time
from typing import Optional, Dict, Any, List

try:
    from flask import Flask, render_template, jsonify, request, send_from_directory, send_file
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    Flask = None

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from consistency_checker.config import get_config, export_endpoints, apply_endpoints
from consistency_checker.core.orchestrator import Pipeline
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer
from consistency_checker.web.connectivity import probe_connectivity, invalidate_cache
from consistency_checker.storage import get_store

logger = logging.getLogger(__name__)

_NS_CACHE = {"ts": 0.0, "data": None}
_NS_CACHE_TTL = 15.0
_SYSTEM_NS_TAIL = ("kube-node-lease", "kube-public", "kube-system")


def _latest_dynamic_report_path(cfg) -> Optional[str]:
    dirs = []
    for path in (
        getattr(cfg, "verification_dir", None),
        os.path.join(getattr(cfg, "project_root", ""), "results/reports"),
        os.path.join(getattr(cfg, "project_root", ""), "istio_Dynamic_Test/results/verification"),
    ):
        if path and os.path.isdir(path) and path not in dirs:
            dirs.append(path)
    candidates = []
    for folder in dirs:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".json") or name.endswith("_summary.json"):
                continue
            if name.startswith("dynamic_test_") or name.startswith("istio_verification_"):
                candidates.append(os.path.join(folder, name))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _kubectl_out(args, timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        return ""


def list_cluster_namespaces(force: bool = False) -> Dict[str, Any]:
    """只列 kubectl get ns 能看到的命名空间，已删除的实验 ns 不出现。"""
    now = time.time()
    if not force and _NS_CACHE["data"] and now - _NS_CACHE["ts"] < _NS_CACHE_TTL:
        return _NS_CACHE["data"]
    try:
        from_ns = _kubectl_out(["get", "ns", "-o", "jsonpath={.items[*].metadata.name}"])
        names = {item for item in from_ns.split() if item}
        if not names:
            return {"ok": False, "namespaces": [], "error": "无法列出命名空间"}
        ordered = sorted(names)
        head = [n for n in ordered if n not in _SYSTEM_NS_TAIL]
        tail = [n for n in _SYSTEM_NS_TAIL if n in names]
        if "default" in head:
            head.remove("default")
            head.insert(0, "default")
        payload = {"ok": True, "namespaces": head + tail, "error": ""}
        _NS_CACHE["ts"] = time.time()
        _NS_CACHE["data"] = payload
        return payload
    except FileNotFoundError:
        return {"ok": False, "namespaces": [], "error": "本机未安装 kubectl"}

# 导入 istio_config_parser 和 istio_Dynamic_Test 的功能
try:
    from istio_config_parser.main_parser import (
        parse_static_semantic,
        load_aligned_semantic,
        AlignedModelMissingError,
    )
    from istio_Dynamic_Test.internal.testcase.generators import SemanticGenerator
    from istio_Dynamic_Test.internal.pipeline import DynamicTester
    from istio_Dynamic_Test.internal.models import TestSuite
    from istio_Dynamic_Test.internal.validation import run_verification
    MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"部分模块导入失败: {e}")
    MODULES_AVAILABLE = False
    parse_static_semantic = None
    SemanticGenerator = None
    load_aligned_semantic = None

    class AlignedModelMissingError(FileNotFoundError):
        pass


class WebServer:
    """Web可视化服务器"""
    
    def __init__(self, port: int = 8080, namespace: str = "default"):
        """
        初始化Web服务器
        
        Args:
            port: 服务器端口
            namespace: Kubernetes命名空间
        """
        if not FLASK_AVAILABLE:
            raise ImportError("Flask未安装，请运行: pip install flask")
        
        self.port = port
        self.namespace = namespace
        self.config = get_config()
        
        # 创建Flask应用
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        
        self.app = Flask(
            __name__,
            template_folder=template_dir,
            static_folder=static_dir
        )
        
        self._setup_routes()
        from consistency_checker.web.relational import install_relational_api
        install_relational_api(self.app, self.config, self.namespace)
        from consistency_checker.web.demo import install_demo
        install_demo(self.app)
        self.store = get_store(self.config.database_path)
        imported = self.store.import_json_reports(self.config.consistency_output_dir)
        if imported:
            logger.info("已从 JSON 导入 %s 份报告到 SQLite", imported)
    
    def _setup_routes(self):
        """设置路由"""
        
        @self.app.route('/')
        def index():
            """主页"""
            return self._render_index()
        
        @self.app.route('/api/reports')
        def list_reports():
            """列出所有报告"""
            return jsonify(self._get_report_list())

        @self.app.route('/api/summary')
        def summary():
            """总览统计"""
            reports = self._get_report_list().get('reports', [])
            latest = reports[0] if reports else None
            return jsonify({
                'report_count': len(reports),
                'latest': latest,
                'namespace': self.namespace,
                'storage': self.store.stats(),
            })

        @self.app.route('/api/storage')
        def storage_info():
            """SQLite 存储状态。"""
            return jsonify(self.store.stats())

        @self.app.route('/api/connectivity')
        def connectivity():
            """集群与可观测组件连通状态"""
            force = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
            return jsonify(probe_connectivity(self.config, force=force))

        @self.app.route('/api/namespaces')
        def namespaces():
            """列出集群当前命名空间，供静态分析 / 动态验证下拉选择。"""
            force = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
            payload = list_cluster_namespaces(force=force)
            payload["current"] = self.config.namespace or self.namespace or "default"
            return jsonify(payload)

        @self.app.route('/api/endpoints', methods=['GET'])
        def get_endpoints():
            """当前可改的探测地址"""
            return jsonify(export_endpoints(self.config))

        @self.app.route('/api/endpoints', methods=['PUT', 'POST'])
        def update_endpoints():
            """保存探测地址并立即用于连通性检测"""
            data = request.get_json() or {}
            apply_endpoints(self.config, data)
            self.namespace = self.config.namespace or self.namespace
            invalidate_cache()
            payload = export_endpoints(self.config)
            payload['connectivity'] = probe_connectivity(self.config, force=True)
            return jsonify(payload)

        @self.app.route('/api/report/<report_id>')
        def get_report(report_id):
            """获取指定报告"""
            return jsonify(self._load_report(report_id))

        @self.app.route('/api/report/<report_id>', methods=['DELETE'])
        def delete_report(report_id):
            """删除 SQLite 中的报告，并清理对应 JSON / HTML / 图文件。"""
            removed = self.store.delete_report(report_id)
            files = self._remove_report_files(report_id, html_path=(removed or {}).get("html_path"))
            if not removed and not files:
                return jsonify({"success": False, "error": "报告不存在"}), 404
            return jsonify({
                "success": True,
                "report_id": report_id,
                "removed_files": files,
            })

        @self.app.route('/api/report/<report_id>/html')
        def get_report_html(report_id):
            """打开流水线写出的 HTML 报告。"""
            path = os.path.join(
                self.config.visualization_output_dir,
                f"{report_id}_report.html",
            )
            if not os.path.exists(path):
                return jsonify({"error": "HTML 报告不存在，请先执行完整流水线"}), 404
            return send_file(path, mimetype="text/html")
        
        @self.app.route('/api/run_pipeline', methods=['POST'])
        def run_pipeline():
            """按模块顺序执行：静态对齐 → 动态打流（受安全开关约束）→ 构图。"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace)
                if data.get('engine', self.config.validation_engine) != 'legacy':
                    from consistency_checker.web.relational import run_request
                    mode = 'run' if data.get('execute') else 'evaluate' if data.get('evidence') else 'plan'
                    return run_request(data, self.config, self.namespace, mode=mode)
                
                from istio_Dynamic_Test.internal.pipeline.guards import options_from_config, warning_lines
                safety = options_from_config(data)
                pipeline = Pipeline(namespace=namespace, safety=safety, execute_dynamic=True)
                report = pipeline.run_full_pipeline()
                
                return jsonify({
                    "success": True,
                    "report_id": report.report_id,
                    "message": "流水线执行成功",
                    "guards": safety.to_dict(),
                    "warnings": warning_lines(safety),
                })
            except Exception as e:
                logger.error(f"流水线执行失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/graph/<report_id>')
        def get_graph(report_id):
            """获取图数据"""
            data = self.store.get_graph(report_id, "topology")
            if data:
                return jsonify(data)
            graph_file = os.path.join(
                self.config.visualization_output_dir,
                f"{report_id}_graph.json"
            )
            if os.path.exists(graph_file):
                with open(graph_file, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
            return jsonify({"error": "图数据不存在"}), 404

        @self.app.route('/api/three_layer_graph/<report_id>')
        def get_three_layer_graph(report_id):
            """获取三层空间配置依赖图数据。report_id=latest 时取最近一次生成的图。"""
            vis_dir = self.config.visualization_output_dir
            if report_id == "latest":
                aligned = os.path.join(vis_dir, "aligned_three_layer_graph.json")
                if os.path.exists(aligned):
                    with open(aligned, "r", encoding="utf-8") as f:
                        return jsonify(json.load(f))
            data = self.store.get_graph(report_id, "three_layer")
            if data:
                return jsonify(data)
            graph_file = None
            if report_id == "latest":
                if os.path.isdir(vis_dir):
                    candidates = [
                        os.path.join(vis_dir, name)
                        for name in os.listdir(vis_dir)
                        if name.endswith("_three_layer_graph.json")
                    ]
                    if candidates:
                        graph_file = max(candidates, key=os.path.getmtime)
            else:
                graph_file = os.path.join(vis_dir, f"{report_id}_three_layer_graph.json")
            if graph_file and os.path.exists(graph_file):
                with open(graph_file, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
            return jsonify({"error": "三层图数据不存在"}), 404

        @self.app.route('/three_layer_graph')
        def three_layer_graph_viewer():
            """三层图查看器页面"""
            return send_from_directory(
                os.path.join(os.path.dirname(__file__), 'static'),
                'three_layer_graph_viewer.html'
            )
        
        @self.app.route('/api/static/snapshot', methods=['GET'])
        def static_snapshot():
            """返回已采集的对齐产物图，不重新解析。"""
            try:
                if load_aligned_semantic is None:
                    return jsonify({"success": False, "error": "parser 模块不可用"}), 500
                artifact = load_aligned_semantic()
                graph = artifact.get("graph_data") or {"nodes": [], "edges": []}
                summary = artifact.get("summary") or {}
                return jsonify({
                    "success": True,
                    "source": "aligned_semantic",
                    "live": False,
                    "generated_at": artifact.get("generated_at"),
                    "summary": summary,
                    "conflicts": artifact.get("conflicts") or [],
                    "expected_tuple_count": len(artifact.get("expected_tuples") or []),
                    "graph_data": graph,
                    "namespaces": (graph.get("metadata") or {}).get("namespaces") or [],
                    "namespace": artifact.get("namespace"),
                    "note": "这是上次静态对齐产物，不是 kubectl 实时列表。请点「执行静态分析」从集群重新采集。",
                })
            except Exception as e:
                logger.error("读取集群快照失败: %s", e, exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500

        # parser：静态对齐 + 跨资源冲突
        @self.app.route('/api/static/analyze', methods=['POST'])
        def run_static_analysis():
            """parser 静态语义对齐（写出 aligned_semantic.json）。"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace) or self.namespace
                if namespace in ("", "all"):
                    namespace = self.namespace

                if not MODULES_AVAILABLE:
                    return jsonify({"success": False, "error": "parser 模块不可用"}), 500

                collect_ns = namespace or self.namespace or "default"
                collect_note = self._refresh_from_cluster(collect_ns)

                bundle = parse_static_semantic(
                    control_plane_dir=self.config.control_plane_config_dir,
                    data_plane_dir=self.config.data_plane_config_dir,
                    ingress_plane_dir=self.config.ingress_plane_config_dir,
                    namespace=namespace,
                )
                artifact = bundle.get("artifact") or {}
                system_ir = bundle.get("system_ir")
                services_payload = []
                if system_ir is not None:
                    for svc in system_ir.get_all_services():
                        functions = {}
                        for func_type, func_ir in svc.functions.items():
                            key = func_type.value if hasattr(func_type, "value") else str(func_type)
                            functions[key] = {
                                "consistency_status": func_ir.consistency_status.value,
                                "issues": [
                                    {
                                        "field_path": issue.field_path,
                                        "severity": getattr(issue.severity, "value", issue.severity),
                                        "control_plane_value": issue.control_plane_value,
                                        "data_plane_value": issue.data_plane_value,
                                        "description": issue.description,
                                    }
                                    for issue in func_ir.issues
                                ],
                            }
                        services_payload.append({
                            "service_name": svc.service_name,
                            "namespace": svc.namespace,
                            "consistency_status": svc.get_consistency_status().value,
                            "functions": functions,
                        })

                return jsonify({
                    "success": True,
                    "module": "parser",
                    "artifact_path": bundle.get("artifact_path"),
                    "summary": bundle.get("summary") or artifact.get("summary") or {},
                    "conflicts": bundle.get("conflicts") or [],
                    "services": services_payload,
                    "graph_data": bundle.get("graph_data") or artifact.get("graph_data") or {"nodes": [], "edges": []},
                    "expected_tuple_count": len(artifact.get("expected_tuples") or []),
                    "collect_note": collect_note,
                })
            except Exception as e:
                logger.error(f"静态分析失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        # 动态测试：期望只来自对齐模型
        @self.app.route('/api/dynamic/generate', methods=['POST'])
        @self.app.route('/api/dynamic/generate_matrix', methods=['POST'])
        def generate_test_matrix():
            """从 aligned_semantic.json 生成测试矩阵。"""
            try:
                data = request.get_json() or {}
                from istio_Dynamic_Test.internal.traffic.entry import resolve_ingress_base
                namespace = data.get('namespace', self.namespace)
                output_path = data.get('output_path', self.config.test_matrix_file)
                ingress_url = resolve_ingress_base(
                    data.get('ingress_url') or self.config.get_ingress_url()
                ) or 'http://localhost:8080'

                if data.get('engine', self.config.validation_engine) != 'legacy':
                    from consistency_checker.web.relational import run_request
                    return run_request(data, self.config, self.namespace, mode='plan', matrix=True)

                if not MODULES_AVAILABLE:
                    return jsonify({
                        "success": False,
                        "error": "istio_Dynamic_Test 模块不可用"
                    }), 500

                generator = SemanticGenerator(
                    ingress_url=ingress_url,
                    namespace=namespace,
                )
                test_matrix = generator.generate_matrix()
                parent = os.path.dirname(output_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(test_matrix, f, indent=2, ensure_ascii=False)

                test_cases = test_matrix.get("test_cases") or []
                from istio_Dynamic_Test.internal.pipeline.guards import options_from_config, warning_lines
                from istio_Dynamic_Test.internal.pipeline.case_view import cases_from_matrix
                safety = options_from_config(data)
                return jsonify({
                    "success": True,
                    "module": "dynamic",
                    "test_matrix": test_matrix,
                    "output_path": output_path,
                    "total_cases": len(test_cases),
                    "cases": cases_from_matrix(test_matrix),
                    "guards": safety.to_dict(),
                    "warnings": warning_lines(safety),
                })
            except AlignedModelMissingError as e:
                logger.warning(f"生成测试矩阵被拒绝: {e}")
                return jsonify({"success": False, "error": str(e)}), 400
            except Exception as e:
                logger.error(f"生成测试矩阵失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/dynamic/run_tests', methods=['POST'])
        def run_dynamic_tests():
            """执行动态测试"""
            try:
                data = request.get_json() or {}
                matrix_file = data.get('matrix_file', self.config.test_matrix_file)
                if data.get('engine', self.config.validation_engine) != 'legacy':
                    from consistency_checker.web.relational import run_request
                    return run_request({**data, 'matrix_file': matrix_file}, self.config, self.namespace, mode='run')
                ssh_config = data.get('ssh_config', {
                    'host': self.config.ssh_host,
                    'user': self.config.ssh_user,
                    'password': self.config.ssh_password
                })
                namespace = data.get('namespace', self.namespace)
                
                if not MODULES_AVAILABLE:
                    return jsonify({
                        "success": False,
                        "error": "istio_Dynamic_Test 模块不可用"
                    }), 500
                
                ssh = None
                if ssh_config:
                    ssh = {
                        "hostname": ssh_config.get("host") or ssh_config.get("hostname"),
                        "username": ssh_config.get("user") or ssh_config.get("username"),
                        "password": ssh_config.get("password"),
                        "port": ssh_config.get("port", 22),
                    }
                from istio_Dynamic_Test.internal.traffic.entry import resolve_ingress_base
                from istio_Dynamic_Test.internal.pipeline.guards import options_from_config, warning_lines
                suite = TestSuite.from_matrix_file(matrix_file)
                ingress_url = resolve_ingress_base(
                    self.config.get_ingress_url() or self.config.ingress_url
                )
                safety = options_from_config(data)
                results = DynamicTester(
                    ssh_config=ssh,
                    namespace=namespace,
                    prometheus_url=self.config.prometheus_url,
                    ingress_url=ingress_url,
                    jaeger_url=self.config.jaeger_url,
                    zipkin_url=self.config.zipkin_url,
                    safety=safety,
                ).run(suite)
                from istio_Dynamic_Test.internal.pipeline.case_view import serialize_pipeline_results
                http_results = {}
                skipped_cases = []
                for pr in results:
                    if pr.execution:
                        http_results[pr.test_case.case_id] = {
                            "status_codes": pr.execution.status_codes,
                            "total_requests": pr.execution.total_requests,
                            "success_rate": pr.execution.success_rate,
                            "avg_response_time": pr.execution.avg_response_time,
                            "error_count": pr.execution.error_count,
                        }
                    elif pr.validation and pr.validation.overall_status.value == "skipped":
                        skipped_cases.append({
                            "case_id": pr.test_case.case_id,
                            "description": pr.test_case.description,
                            "summary": pr.validation.summary,
                        })
                        http_results[pr.test_case.case_id] = {
                            "skipped": True,
                            "message": pr.validation.summary,
                            "total_requests": 0,
                            "error_count": 0,
                        }

                cases = serialize_pipeline_results(results)
                return jsonify({
                    "success": True,
                    "message": "动态测试执行完成",
                    "total_cases": len(cases) or len(suite.cases),
                    "http_results": http_results,
                    "cases": cases,
                    "skipped": skipped_cases,
                    "guards": safety.to_dict(),
                    "warnings": warning_lines(safety),
                })
            except Exception as e:
                logger.error(f"动态测试执行失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500

        @self.app.route('/api/dynamic/results', methods=['GET'])
        def latest_dynamic_results():
            """最近一次动态验证的预期 / 实际 / 一致性。"""
            try:
                from istio_Dynamic_Test.internal.pipeline.case_view import cases_from_matrix, cases_from_report
                matrix = {}
                matrix_file = self.config.test_matrix_file
                if matrix_file and os.path.isfile(matrix_file):
                    with open(matrix_file, "r", encoding="utf-8") as f:
                        matrix = json.load(f) or {}
                report_path = _latest_dynamic_report_path(self.config)
                report = {}
                if report_path:
                    with open(report_path, "r", encoding="utf-8") as f:
                        report = json.load(f) or {}
                cases = cases_from_report(report, matrix) if report else cases_from_matrix(matrix)
                passed = sum(1 for c in cases if c.get("status") == "passed")
                failed = sum(1 for c in cases if c.get("status") == "failed")
                skipped = sum(1 for c in cases if c.get("status") == "skipped")
                return jsonify({
                    "success": True,
                    "cases": cases,
                    "total_cases": len(cases),
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "report_path": report_path,
                    "generated_at": report.get("generated_at"),
                })
            except Exception as e:
                logger.error(f"加载动态结果失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/api/dynamic/verify', methods=['POST'])
        def verify_dynamic_tests():
            """验证动态测试结果"""
            try:
                data = request.get_json() or {}
                matrix_file = data.get('matrix_file', self.config.test_matrix_file)
                log_dir = data.get('log_dir', self.config.envoy_logs_dir)
                if data.get('engine', self.config.validation_engine) != 'legacy':
                    from consistency_checker.web.relational import run_request
                    return run_request({**data, 'matrix_file': matrix_file}, self.config, self.namespace, mode='evaluate')
                output_dir = data.get('output_dir', self.config.verification_dir)
                config_file = data.get('config_file')
                
                if not MODULES_AVAILABLE:
                    return jsonify({
                        "success": False,
                        "error": "istio_Dynamic_Test 模块不可用"
                    }), 500
                
                # 运行验证
                run_verification(
                    matrix_file=matrix_file,
                    log_dir=log_dir,
                    output_dir=output_dir,
                    istio_config_file=config_file
                )
                
                # 查找最新的验证报告
                report_files = [
                    f for f in os.listdir(output_dir)
                    if f.startswith('istio_verification_') and f.endswith('.json')
                ]
                
                if report_files:
                    latest_report = max(
                        report_files,
                        key=lambda f: os.path.getmtime(os.path.join(output_dir, f))
                    )
                    report_path = os.path.join(output_dir, latest_report)
                    
                    with open(report_path, 'r', encoding='utf-8') as f:
                        report_data = json.load(f)
                    
                    return jsonify({
                        "success": True,
                        "report": report_data,
                        "report_path": report_path
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": "未找到验证报告"
                    }), 404
            except Exception as e:
                logger.error(f"验证动态测试失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/dynamic/analyze', methods=['POST'])
        def analyze_dynamic_results():
            """分析动态测试结果"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace)
                if data.get('engine', self.config.validation_engine) != 'legacy':
                    from pathlib import Path
                    from configpilot.workflow import load_json
                    directory = data.get('run_dir') or data.get('output_dir')
                    if not directory:
                        reports = list(Path(self.config.validation_output_dir).glob('*/run_report.json'))
                        if not reports:
                            return jsonify({'success': False, 'error': '没有新验证报告，请先规划或执行'}), 404
                        directory = str(max(reports, key=lambda path: path.stat().st_mtime).parent)
                    report = load_json(Path(directory)/'run_report.json')
                    return jsonify({'success': True, 'engine': 'relational', 'result': report,
                                    'diagnostics': load_json(Path(directory)/'diagnostics.json')})
                
                dynamic_analyzer = DynamicAnalyzer()
                result = dynamic_analyzer.analyze()
                
                return jsonify({
                    "success": True,
                    "result": result
                })
            except Exception as e:
                logger.error(f"分析动态测试结果失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500

        @self.app.route('/api/consistency/graph', methods=['POST', 'GET'])
        def consistency_graph():
            """checker：消费静态/动态产物生成三层图，不再二次解析。"""
            try:
                data = request.get_json(silent=True) or {}
                namespace = data.get('namespace') or request.args.get('namespace') or self.namespace
                if load_aligned_semantic is None:
                    return jsonify({"success": False, "error": "parser 模块不可用"}), 500
                try:
                    artifact = load_aligned_semantic()
                except AlignedModelMissingError as e:
                    return jsonify({"success": False, "error": str(e)}), 400

                analyzer = StaticAnalyzer(namespace=namespace)
                static_result = analyzer._consume_artifact(artifact)

                from consistency_checker.visualizer.three_layer_graph_generator import ThreeLayerGraphGenerator
                generator = ThreeLayerGraphGenerator.from_static_result(
                    static_result,
                    namespace=namespace,
                )
                generator.generate()
                graph_json = generator.to_d3_json()
                vis_dir = self.config.visualization_output_dir
                os.makedirs(vis_dir, exist_ok=True)
                out_path = os.path.join(vis_dir, "aligned_three_layer_graph.json")
                generator.save_to_file(out_path)
                try:
                    self.store.save_graph("latest", "three_layer", graph_json)
                except Exception as exc:
                    logger.warning("写入三层图到 SQLite 失败: %s", exc)
                return jsonify({
                    "success": True,
                    "module": "checker",
                    "graph": graph_json,
                    "graph_path": out_path,
                    "conflicts": artifact.get("conflicts") or [],
                    "summary": artifact.get("summary") or {},
                })
            except Exception as e:
                logger.error(f"生成三层图失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": str(e)}), 500

    def _refresh_from_cluster(self, namespace: str) -> str:
        """走原有 IstioSidecarMonitor 从集群刷新控制面 / 数据面 / Ingress。"""
        try:
            from istio_config_parser.istio_monitor.istio_sidecar_monitor import IstioSidecarMonitor
        except Exception as exc:
            logger.warning("监控器不可用，跳过采集: %s", exc)
            return "未采集（监控器不可用），将解析现有快照"

        monitor = IstioSidecarMonitor(
            interval=3600,
            output_dir=self.config.data_plane_config_dir,
            namespace=namespace or self.namespace or "default",
            config_types=["routes", "clusters", "listeners"],
            use_vm=False,
            vm_host=None,
            k8s_host=None,
            k8s_token=None,
        )
        monitor.control_plane_dir = self.config.control_plane_config_dir
        changes = monitor.update_now() or {}
        logger.info("集群采集完成，变更键: %s", list(changes.keys())[:12])
        keys = list(changes.keys())
        bits = []
        if any(k.startswith("control_plane") for k in keys):
            bits.append("控制面")
        if changes.get("ingress_gateway"):
            bits.append("Ingress")
        if changes.get("sidecar_dump") or any(k.startswith("sidecar_") for k in keys):
            bits.append("Sidecar")
        if not bits:
            return "监控采集没有写入新快照，将解析目录里已有文件（可能过期）"
        missing = [name for name in ("控制面", "Ingress", "Sidecar") if name not in bits]
        note = "已用监控从集群刷新：" + "、".join(bits)
        if missing:
            note += "；未刷新 " + "、".join(missing) + "（仍可能混入旧 dump）"
        return note

    def _render_index(self):
        """兼容旧调用，转发到模板首页。"""
        return render_template(
            'index.html',
            namespace=self.namespace,
            istio_config_file=self.config.istio_config_file,
            service_dependencies_file=self.config.service_dependencies_file,
            ingress_url=self.config.get_ingress_url() or 'http://localhost:8080',
        )

    def _is_safe_report_file(self, path: str) -> bool:
        """只允许删除报告导出文件，不对齐结果等共享产物。"""
        abs_path = os.path.abspath(path)
        name = os.path.basename(abs_path)
        if name in ("aligned_semantic.json", "aligned_three_layer_graph.json"):
            return False
        roots = [
            os.path.abspath(self.config.consistency_output_dir),
            os.path.abspath(self.config.visualization_output_dir),
        ]
        return any(abs_path == root or abs_path.startswith(root + os.sep) for root in roots)

    def _remove_report_files(self, report_id: str, html_path: Optional[str] = None) -> List[str]:
        """删除报告导出的 JSON / HTML / 图文件。"""
        removed: List[str] = []
        vis_dir = self.config.visualization_output_dir
        candidates = [
            os.path.join(self.config.consistency_output_dir, f"{report_id}.json"),
            os.path.join(vis_dir, f"{report_id}_report.html"),
            os.path.join(vis_dir, f"{report_id}_graph.json"),
            os.path.join(vis_dir, f"{report_id}_three_layer_graph.json"),
        ]
        if html_path:
            candidates.append(html_path)
        seen = set()
        for path in candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            if not self._is_safe_report_file(path):
                logger.warning("跳过非报告文件: %s", path)
                continue
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed.append(path)
            except OSError as exc:
                logger.warning("删除报告文件失败 %s: %s", path, exc)
        return removed

    def _get_report_list(self):
        """获取报告列表（SQLite 优先）。"""
        reports = self.store.list_reports()
        if reports:
            return {"reports": reports}
        return {"reports": []}

    def _load_report(self, report_id: str):
        """加载指定报告"""
        data = self.store.get_report(report_id)
        if data:
            return data
        filepath = os.path.join(self.config.consistency_output_dir, f"{report_id}.json")
        if not os.path.exists(filepath):
            return {"error": "报告不存在"}
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def run(self):
        """启动服务器"""
        logger.info(f"🌐 Web服务器启动成功")
        logger.info(f"   访问地址: http://localhost:{self.port}")
        logger.info(f"   命名空间: {self.namespace}")
        
        self.app.run(
            host='0.0.0.0',
            port=self.port,
            debug=False
        )

