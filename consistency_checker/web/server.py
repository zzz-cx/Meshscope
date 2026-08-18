"""
Web可视化服务器

提供交互式Web界面展示一致性验证结果
包括静态分析和动态测试功能
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any

try:
    from flask import Flask, render_template, jsonify, request, send_from_directory
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

logger = logging.getLogger(__name__)

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
            })

        @self.app.route('/api/connectivity')
        def connectivity():
            """集群与可观测组件连通状态"""
            force = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
            return jsonify(probe_connectivity(self.config, force=force))

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
        
        @self.app.route('/api/run_pipeline', methods=['POST'])
        def run_pipeline():
            """按模块顺序执行：静态对齐 → 动态读结果 → 构图。不额外做第二套分析。"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace)
                
                pipeline = Pipeline(namespace=namespace)
                report = pipeline.run_full_pipeline()
                
                return jsonify({
                    "success": True,
                    "report_id": report.report_id,
                    "message": "流水线执行成功"
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
            graph_file = os.path.join(
                self.config.visualization_output_dir,
                f"{report_id}_graph.json"
            )
            
            if os.path.exists(graph_file):
                with open(graph_file, 'r', encoding='utf-8') as f:
                    return jsonify(json.load(f))
            else:
                return jsonify({"error": "图数据不存在"}), 404

        @self.app.route('/api/three_layer_graph/<report_id>')
        def get_three_layer_graph(report_id):
            """获取三层空间配置依赖图数据"""
            graph_file = os.path.join(
                self.config.visualization_output_dir,
                f"{report_id}_three_layer_graph.json"
            )
            if os.path.exists(graph_file):
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
        
        # parser：静态对齐 + 跨资源冲突
        @self.app.route('/api/static/analyze', methods=['POST'])
        def run_static_analysis():
            """parser 静态语义对齐（写出 aligned_semantic.json）。"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace)
                if namespace == "default":
                    namespace = None

                if not MODULES_AVAILABLE:
                    return jsonify({"success": False, "error": "parser 模块不可用"}), 500

                bundle = parse_static_semantic(
                    control_plane_dir=self.config.control_plane_config_dir,
                    data_plane_dir=self.config.data_plane_config_dir,
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
                namespace = data.get('namespace', self.namespace)
                output_path = data.get('output_path', self.config.test_matrix_file)
                ingress_url = data.get('ingress_url', self.config.get_ingress_url() or 'http://localhost:8080')

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
                return jsonify({
                    "success": True,
                    "module": "dynamic",
                    "test_matrix": test_matrix,
                    "output_path": output_path,
                    "total_cases": len(test_cases),
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
                suite = TestSuite.from_matrix_file(matrix_file)
                results = DynamicTester(ssh_config=ssh, namespace=namespace).run(suite)
                http_results = {}
                for pr in results:
                    if pr.execution:
                        http_results[pr.test_case.case_id] = {
                            "status_codes": pr.execution.status_codes,
                            "total_requests": pr.execution.total_requests,
                            "success_rate": pr.execution.success_rate,
                            "avg_response_time": pr.execution.avg_response_time,
                            "error_count": pr.execution.error_count,
                        }

                return jsonify({
                    "success": True,
                    "message": "动态测试执行完成",
                    "total_cases": len(suite.cases),
                    "http_results": http_results,
                })
            except Exception as e:
                logger.error(f"动态测试执行失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        @self.app.route('/api/dynamic/verify', methods=['POST'])
        def verify_dynamic_tests():
            """验证动态测试结果"""
            try:
                data = request.get_json() or {}
                matrix_file = data.get('matrix_file', self.config.test_matrix_file)
                log_dir = data.get('log_dir', self.config.envoy_logs_dir)
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
                
                dynamic_analyzer = DynamicAnalyzer(namespace=namespace)
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
    
    def _render_index(self):
        """兼容旧调用，转发到模板首页。"""
        return render_template(
            'index.html',
            namespace=self.namespace,
            istio_config_file=self.config.istio_config_file,
            service_dependencies_file=self.config.service_dependencies_file,
            ingress_url=self.config.get_ingress_url() or 'http://localhost:8080',
        )

    def _get_report_list(self):
        """获取报告列表"""
        reports = []
        output_dir = self.config.consistency_output_dir
        
        if not os.path.exists(output_dir):
            return {"reports": []}
        
        for filename in os.listdir(output_dir):
            if filename.startswith('report_') and filename.endswith('.json'):
                filepath = os.path.join(output_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        reports.append({
                            "id": data.get('report_id', ''),
                            "title": data.get('title', ''),
                            "timestamp": data.get('timestamp', ''),
                            "status": data.get('consistency_check', {}).get('overall_status', 'unknown'),
                            "consistency_rate": data.get('consistency_check', {}).get('consistency_rate', 0.0)
                        })
                except Exception as e:
                    logger.error(f"读取报告失败 {filename}: {e}")
        
        # 按时间排序
        reports.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return {"reports": reports}
    
    def _load_report(self, report_id: str):
        """加载指定报告"""
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


