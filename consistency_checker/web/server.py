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
from datetime import datetime

try:
    from flask import Flask, render_template, jsonify, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    Flask = None

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from consistency_checker.config import get_config
from consistency_checker.core.orchestrator import Pipeline
from consistency_checker.core.static_analyzer import StaticAnalyzer
from consistency_checker.core.dynamic_analyzer import DynamicAnalyzer

logger = logging.getLogger(__name__)

# 导入 istio_config_parser 和 istio_Dynamic_Test 的功能
try:
    from istio_config_parser.main_parser import (
        parse_unified_from_dir,
        parse_and_export_models,
        parse_control_plane_from_dir,
        parse_data_plane_from_dir
    )
    from istio_Dynamic_Test.generator.test_case_generator import TestCaseGenerator
    from istio_Dynamic_Test.checker.traffic_driver import TrafficDriver
    from istio_Dynamic_Test.verifier.main_verifier import run_verification
    MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"部分模块导入失败: {e}")
    MODULES_AVAILABLE = False


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
        
        @self.app.route('/api/report/<report_id>')
        def get_report(report_id):
            """获取指定报告"""
            return jsonify(self._load_report(report_id))
        
        @self.app.route('/api/run_pipeline', methods=['POST'])
        def run_pipeline():
            """执行流水线"""
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
        
        # 静态分析相关 API
        @self.app.route('/api/static/analyze', methods=['POST'])
        def run_static_analysis():
            """执行静态分析"""
            try:
                data = request.get_json() or {}
                namespace = data.get('namespace', self.namespace)
                use_unified = data.get('use_unified', True)
                
                if use_unified and MODULES_AVAILABLE:
                    # 使用统一解析器
                    system_ir = parse_unified_from_dir(
                        control_plane_dir=self.config.control_plane_config_dir,
                        data_plane_dir=self.config.data_plane_config_dir,
                        namespace=namespace if namespace != "default" else None
                    )
                    
                    # 转换为字典格式
                    result = {
                        "success": True,
                        "summary": system_ir.get_summary(),
                        "services": [
                            {
                                "service_name": svc.service_name,
                                "namespace": svc.namespace,
                                "consistency_status": svc.get_consistency_status().value,
                                "functions": {
                                    func_type: {
                                        "consistency_status": func_ir.consistency_status.value,
                                        "issues": [
                                            {
                                                "field_path": issue.field_path,
                                                "severity": issue.severity.value,
                                                "control_plane_value": issue.control_plane_value,
                                                "data_plane_value": issue.data_plane_value,
                                                "description": issue.description
                                            }
                                            for issue in func_ir.issues
                                        ]
                                    }
                                    for func_type, func_ir in svc.functions.items()
                                }
                            }
                            for svc in system_ir.get_all_services()
                        ]
                    }
                    
                    # 使用 StaticAnalyzer 生成图数据
                    static_analyzer = StaticAnalyzer(namespace=namespace)
                    static_result = static_analyzer.analyze()
                    
                    result["graph_data"] = {
                        "nodes": [
                            {
                                "id": node.service_name,
                                "label": node.service_name,
                                "namespace": node.namespace,
                                "type": node.node_type,
                                "subsets": node.subsets,
                                "has_virtualservice": node.has_virtualservice,
                                "has_destinationrule": node.has_destinationrule,
                                "policies": node.has_policies
                            }
                            for node in static_result.get('service_nodes', [])
                        ],
                        "edges": [
                            {
                                "id": edge.edge_id,
                                "source": edge.source,
                                "target": edge.target,
                                "type": edge.edge_type,
                                "weight": edge.weight,
                                "label": edge.label
                            }
                            for edge in static_result.get('config_edges', [])
                        ]
                    }
                    
                    return jsonify(result)
                else:
                    # 使用旧版解析器
                    static_analyzer = StaticAnalyzer(namespace=namespace)
                    result = static_analyzer.analyze()
                    
                    return jsonify({
                        "success": True,
                        "summary": result.get('summary', {}),
                        "graph_data": {
                            "nodes": [
                                {
                                    "id": node.service_name,
                                    "label": node.service_name,
                                    "namespace": node.namespace,
                                    "type": node.node_type,
                                    "subsets": node.subsets,
                                    "has_virtualservice": node.has_virtualservice,
                                    "has_destinationrule": node.has_destinationrule,
                                    "policies": node.has_policies
                                }
                                for node in result.get('service_nodes', [])
                            ],
                            "edges": [
                                {
                                    "id": edge.edge_id,
                                    "source": edge.source,
                                    "target": edge.target,
                                    "type": edge.edge_type,
                                    "weight": edge.weight,
                                    "label": edge.label
                                }
                                for edge in result.get('config_edges', [])
                            ]
                        },
                        "policies": [
                            {
                                "policy_id": p.policy_id,
                                "policy_type": p.policy_type.value,
                                "source_service": p.source_service,
                                "target_service": p.target_service,
                                "config_name": p.config_name,
                                "config_type": p.config_type
                            }
                            for p in result.get('static_policies', [])
                        ]
                    })
            except Exception as e:
                logger.error(f"静态分析失败: {e}", exc_info=True)
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
        
        # 动态测试相关 API
        @self.app.route('/api/dynamic/generate_matrix', methods=['POST'])
        def generate_test_matrix():
            """生成测试矩阵"""
            try:
                data = request.get_json() or {}
                config_path = data.get('config_path', 'istio_Dynamic_Test/generator/istio_config.json')
                service_deps_path = data.get('service_deps_path', 'istio_Dynamic_Test/service_dependencies.json')
                namespace = data.get('namespace', self.namespace)
                output_path = data.get('output_path', 'istio_Dynamic_Test/generator/output_matrix.json')
                ingress_url = data.get('ingress_url', 'http://localhost:8080')
                
                if not MODULES_AVAILABLE:
                    return jsonify({
                        "success": False,
                        "error": "istio_Dynamic_Test 模块不可用"
                    }), 500
                
                generator = TestCaseGenerator(
                    config_path=config_path,
                    service_deps_path=service_deps_path if os.path.exists(service_deps_path) else None,
                    namespace=namespace
                )
                
                # generate() 返回的是 test_cases 列表，需要包装成完整的测试矩阵格式
                test_cases = generator.generate()
                
                # 确保 test_cases 是列表
                if not isinstance(test_cases, list):
                    test_cases = list(test_cases) if test_cases else []
                
                # 构建完整的测试矩阵数据结构
                test_matrix = {
                    "global_settings": {
                        "ingress_url": ingress_url
                    },
                    "test_cases": test_cases
                }
                
                # 保存测试矩阵
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(test_matrix, f, indent=2, ensure_ascii=False)
                
                return jsonify({
                    "success": True,
                    "test_matrix": test_matrix,
                    "output_path": output_path,
                    "total_cases": len(test_cases)
                })
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
                matrix_file = data.get('matrix_file', 'istio_Dynamic_Test/generator/output_matrix.json')
                ssh_config = data.get('ssh_config', {})
                namespace = data.get('namespace', self.namespace)
                
                if not MODULES_AVAILABLE:
                    return jsonify({
                        "success": False,
                        "error": "istio_Dynamic_Test 模块不可用"
                    }), 500
                
                traffic_driver = TrafficDriver(
                    matrix_file=matrix_file,
                    ssh_config=ssh_config if ssh_config else None,
                    namespace=namespace
                )
                
                # 执行测试（run() 方法不返回结果，结果存储在实例属性中）
                traffic_driver.run()
                
                return jsonify({
                    "success": True,
                    "message": "动态测试执行完成",
                    "total_cases": len(traffic_driver.test_cases),
                    "http_results": traffic_driver.http_results if hasattr(traffic_driver, 'http_results') else {}
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
                matrix_file = data.get('matrix_file', 'istio_Dynamic_Test/generator/output_matrix.json')
                log_dir = data.get('log_dir', 'istio_Dynamic_Test/results/envoy_logs')
                output_dir = data.get('output_dir', 'istio_Dynamic_Test/results/verification')
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
    
    def _render_index(self):
        """渲染主页"""
        # 完整的HTML返回，包含静态分析和动态测试功能
        html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Istio配置一致性验证系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px 20px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
        .card { background: white; border-radius: 8px; padding: 25px; margin: 20px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        .tabs { display: flex; border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; }
        .tab { padding: 12px 24px; cursor: pointer; border: none; background: none; font-size: 16px; color: #64748b; transition: all 0.3s; }
        .tab.active { color: #667eea; border-bottom: 2px solid #667eea; font-weight: bold; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .btn { display: inline-block; padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; text-decoration: none; transition: background 0.3s; margin: 5px; }
        .btn:hover { background: #5568d3; }
        .btn-secondary { background: #48bb78; }
        .btn-secondary:hover { background: #38a169; }
        .btn-danger { background: #f56565; }
        .btn-danger:hover { background: #e53e3e; }
        .form-group { margin: 15px 0; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: bold; color: #334155; }
        .form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 5px; font-size: 14px; }
        .status-badge { padding: 5px 12px; border-radius: 15px; font-size: 12px; font-weight: bold; }
        .status-consistent { background: #48bb78; color: white; }
        .status-inconsistent { background: #f56565; color: white; }
        .status-partial { background: #ed8936; color: white; }
        .loading { text-align: center; padding: 40px; color: #999; }
        #graph-container { width: 100%; height: 600px; border: 1px solid #e2e8f0; border-radius: 8px; margin: 20px 0; background: #fafafa; }
        .result-panel { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0; }
        .result-panel h3 { margin-bottom: 10px; color: #334155; }
        .result-panel pre { background: white; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 12px; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
    <div class="header">
        <h1>🔍 Istio配置一致性验证系统</h1>
        <p style="margin-top: 10px; opacity: 0.9;">全局化、系统化的配置验证与可视化平台</p>
    </div>
    
    <div class="container">
        <div class="card">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('static')">📋 静态分析</button>
                <button class="tab" onclick="switchTab('dynamic')">🔄 动态测试</button>
                <button class="tab" onclick="switchTab('consistency')">✅ 一致性验证</button>
            </div>
            
            <!-- 静态分析标签页 -->
            <div id="static-tab" class="tab-content active">
                <h2>静态配置分析</h2>
                <p style="color: #64748b; margin-bottom: 20px;">通过控制层和数据面提取到的文件进行解析并分析为model的形式，并给出对应的配置依赖图</p>
                
                <div class="form-group">
                    <label>命名空间:</label>
                    <input type="text" id="static-namespace" value="default" placeholder="default">
                </div>
                
                <button class="btn" onclick="runStaticAnalysis()">🚀 执行静态分析</button>
                <button class="btn btn-secondary" onclick="loadStaticResults()">📊 查看结果</button>
                
                <div id="static-status" style="margin-top: 15px; padding: 10px; border-radius: 5px; display: none;"></div>
                
                <div id="static-results" style="margin-top: 20px;"></div>
                <div id="graph-container"></div>
            </div>
            
            <!-- 动态测试标签页 -->
            <div id="dynamic-tab" class="tab-content">
                <h2>动态测试</h2>
                <p style="color: #64748b; margin-bottom: 20px;">通过istio_Dynamic_Test的测试逻辑进行测试，返回对应的动态测试报告</p>
                
                <div class="form-group">
                    <label>命名空间:</label>
                    <input type="text" id="dynamic-namespace" value="default" placeholder="default">
                </div>
                
                <div class="form-group">
                    <label>配置文件路径:</label>
                    <input type="text" id="config-path" value="istio_Dynamic_Test/generator/istio_config.json">
                </div>
                
                <div class="form-group">
                    <label>Ingress URL (入口地址):</label>
                    <input type="text" id="ingress-url" value="http://localhost:8080" placeholder="http://192.168.92.131:30476/productpage">
                    <small style="color: #64748b; display: block; margin-top: 5px;">用于动态测试的入口地址，例如: http://192.168.92.131:30476/productpage</small>
                </div>
                
                <div class="form-group">
                    <label>服务依赖文件路径 (可选):</label>
                    <input type="text" id="service-deps-path" value="istio_Dynamic_Test/service_dependencies.json" placeholder="可选">
                </div>
                
                <button class="btn" onclick="generateTestMatrix()">📝 生成测试矩阵</button>
                <button class="btn btn-secondary" onclick="runDynamicTests()">🚀 执行动态测试</button>
                <button class="btn btn-secondary" onclick="verifyDynamicTests()">✅ 验证测试结果</button>
                <button class="btn btn-secondary" onclick="analyzeDynamicResults()">📊 分析结果</button>
                
                <div id="dynamic-status" style="margin-top: 15px; padding: 10px; border-radius: 5px; display: none;"></div>
                
                <div id="dynamic-results" style="margin-top: 20px;"></div>
            </div>
            
            <!-- 一致性验证标签页 -->
            <div id="consistency-tab" class="tab-content">
                <h2>一致性验证</h2>
                <p style="color: #64748b; margin-bottom: 20px;">执行完整的一致性验证流水线</p>
                
                <div class="form-group">
                    <label>命名空间:</label>
                    <input type="text" id="consistency-namespace" value="default" placeholder="default">
                </div>
                
                <button class="btn" onclick="runPipeline()">🚀 执行完整流水线</button>
                <button class="btn btn-secondary" onclick="loadReports()">📊 刷新报告列表</button>
                
                <div id="consistency-status" style="margin-top: 15px; padding: 10px; border-radius: 5px; display: none;"></div>
                
                <div id="reports-container">
                    <div class="loading">加载中...</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // 标签切换
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById(tabName + '-tab').classList.add('active');
        }
        
        // 静态分析
        function runStaticAnalysis() {
            const statusDiv = document.getElementById('static-status');
            const namespace = document.getElementById('static-namespace').value;
            
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#e6fffa';
            statusDiv.style.color = '#234e52';
            statusDiv.innerHTML = '⏳ 正在执行静态分析，请稍候...';
            
            axios.post('/api/static/analyze', {
                namespace: namespace,
                use_unified: true
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.style.color = '#22543d';
                statusDiv.innerHTML = '✅ 静态分析完成！';
                
                displayStaticResults(response.data);
                if (response.data.graph_data) {
                    drawGraph(response.data.graph_data);
                }
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.style.color = '#742a2a';
                statusDiv.innerHTML = '❌ 分析失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function displayStaticResults(data) {
            const container = document.getElementById('static-results');
            let html = '<div class="result-panel">';
            html += '<h3>分析摘要</h3>';
            html += '<pre>' + JSON.stringify(data.summary || {}, null, 2) + '</pre>';
            html += '</div>';
            
            if (data.policies && data.policies.length > 0) {
                html += '<div class="result-panel">';
                html += '<h3>策略列表 (' + data.policies.length + ')</h3>';
                html += '<pre>' + JSON.stringify(data.policies.slice(0, 10), null, 2) + '</pre>';
                html += '</div>';
            }
            
            container.innerHTML = html;
        }
        
        function drawGraph(graphData) {
            const container = document.getElementById('graph-container');
            const width = container.clientWidth;
            const height = 600;
            
            d3.select('#graph-container').selectAll('*').remove();
            
            const svg = d3.select('#graph-container')
                .append('svg')
                .attr('width', width)
                .attr('height', height);
            
            // 创建力导向图
            const simulation = d3.forceSimulation(graphData.nodes)
                .force('link', d3.forceLink(graphData.edges).id(d => d.id))
                .force('charge', d3.forceManyBody().strength(-300))
                .force('center', d3.forceCenter(width / 2, height / 2));
            
            // 绘制边
            const link = svg.append('g')
                .selectAll('line')
                .data(graphData.edges)
                .enter()
                .append('line')
                .attr('stroke', '#999')
                .attr('stroke-width', d => d.weight ? d.weight / 10 : 2)
                .attr('stroke-opacity', 0.6);
            
            // 绘制节点
            const node = svg.append('g')
                .selectAll('circle')
                .data(graphData.nodes)
                .enter()
                .append('circle')
                .attr('r', 20)
                .attr('fill', '#667eea')
                .call(drag(simulation));
            
            // 添加标签
            const label = svg.append('g')
                .selectAll('text')
                .data(graphData.nodes)
                .enter()
                .append('text')
                .text(d => d.label || d.id)
                .attr('font-size', 12)
                .attr('dx', 25)
                .attr('dy', 5);
            
            // 更新位置
            simulation.on('tick', () => {
                link
                    .attr('x1', d => d.source.x)
                    .attr('y1', d => d.source.y)
                    .attr('x2', d => d.target.x)
                    .attr('y2', d => d.target.y);
                
                node
                    .attr('cx', d => d.x)
                    .attr('cy', d => d.y);
                
                label
                    .attr('x', d => d.x)
                    .attr('y', d => d.y);
            });
            
            function drag(simulation) {
                function dragstarted(event) {
                    if (!event.active) simulation.alphaTarget(0.3).restart();
                    event.subject.fx = event.subject.x;
                    event.subject.fy = event.subject.y;
                }
                
                function dragged(event) {
                    event.subject.fx = event.x;
                    event.subject.fy = event.y;
                }
                
                function dragended(event) {
                    if (!event.active) simulation.alphaTarget(0);
                    event.subject.fx = null;
                    event.subject.fy = null;
                }
                
                return d3.drag()
                    .on('start', dragstarted)
                    .on('drag', dragged)
                    .on('end', dragended);
            }
        }
        
        // 动态测试
        function generateTestMatrix() {
            const statusDiv = document.getElementById('dynamic-status');
            const namespace = document.getElementById('dynamic-namespace').value;
            const configPath = document.getElementById('config-path').value;
            const ingressUrl = document.getElementById('ingress-url').value;
            const serviceDepsPath = document.getElementById('service-deps-path').value;
            
            if (!ingressUrl) {
                statusDiv.style.display = 'block';
                statusDiv.style.background = '#fff5f5';
                statusDiv.style.color = '#742a2a';
                statusDiv.innerHTML = '❌ 请输入 Ingress URL';
                return;
            }
            
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#e6fffa';
            statusDiv.style.color = '#234e52';
            statusDiv.innerHTML = '⏳ 正在生成测试矩阵...';
            
            axios.post('/api/dynamic/generate_matrix', {
                namespace: namespace,
                config_path: configPath,
                ingress_url: ingressUrl,
                service_deps_path: serviceDepsPath || undefined
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.innerHTML = '✅ 测试矩阵生成成功！共 ' + response.data.total_cases + ' 个测试用例';
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.innerHTML = '❌ 生成失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function runDynamicTests() {
            const statusDiv = document.getElementById('dynamic-status');
            const namespace = document.getElementById('dynamic-namespace').value;
            
            statusDiv.style.display = 'block';
            statusDiv.innerHTML = '⏳ 正在执行动态测试，请稍候...';
            
            axios.post('/api/dynamic/run_tests', {
                namespace: namespace
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.innerHTML = '✅ 动态测试执行完成！';
                displayDynamicResults(response.data);
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.innerHTML = '❌ 执行失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function verifyDynamicTests() {
            const statusDiv = document.getElementById('dynamic-status');
            const namespace = document.getElementById('dynamic-namespace').value;
            
            statusDiv.style.display = 'block';
            statusDiv.innerHTML = '⏳ 正在验证测试结果...';
            
            axios.post('/api/dynamic/verify', {
                namespace: namespace
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.innerHTML = '✅ 验证完成！';
                displayDynamicResults(response.data);
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.innerHTML = '❌ 验证失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function analyzeDynamicResults() {
            const statusDiv = document.getElementById('dynamic-status');
            const namespace = document.getElementById('dynamic-namespace').value;
            
            statusDiv.style.display = 'block';
            statusDiv.innerHTML = '⏳ 正在分析结果...';
            
            axios.post('/api/dynamic/analyze', {
                namespace: namespace
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.innerHTML = '✅ 分析完成！';
                displayDynamicResults(response.data.result);
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.innerHTML = '❌ 分析失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function displayDynamicResults(data) {
            const container = document.getElementById('dynamic-results');
            let html = '<div class="result-panel">';
            html += '<h3>测试结果</h3>';
            html += '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            html += '</div>';
            container.innerHTML = html;
        }
        
        // 一致性验证
        function runPipeline() {
            const statusDiv = document.getElementById('consistency-status');
            const namespace = document.getElementById('consistency-namespace').value;
            
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#e6fffa';
            statusDiv.style.color = '#234e52';
            statusDiv.innerHTML = '⏳ 正在执行流水线，请稍候...';
            
            axios.post('/api/run_pipeline', {
                namespace: namespace
            })
            .then(response => {
                statusDiv.style.background = '#f0fff4';
                statusDiv.style.color = '#22543d';
                statusDiv.innerHTML = '✅ 流水线执行成功！报告ID: ' + response.data.report_id;
                
                setTimeout(() => {
                    loadReports();
                }, 1000);
            })
            .catch(error => {
                statusDiv.style.background = '#fff5f5';
                statusDiv.style.color = '#742a2a';
                statusDiv.innerHTML = '❌ 执行失败: ' + (error.response?.data?.error || error.message);
            });
        }
        
        function loadReports() {
            const container = document.getElementById('reports-container');
            container.innerHTML = '<div class="loading">加载中...</div>';
            
            axios.get('/api/reports')
                .then(response => {
                    const reports = response.data.reports || [];
                    
                    if (reports.length === 0) {
                        container.innerHTML = '<p style="padding: 20px; text-align: center; color: #999;">暂无报告</p>';
                        return;
                    }
                    
                    let html = '<ul class="reports-list">';
                    reports.forEach(report => {
                        const statusClass = 'status-' + report.status;
                        html += `
                            <li class="report-item">
                                <div>
                                    <strong>${report.title}</strong>
                                    <div style="font-size: 14px; color: #666; margin-top: 5px;">
                                        ID: ${report.id} | 时间: ${report.timestamp}
                                    </div>
                                </div>
                                <div>
                                    <span class="status-badge ${statusClass}">${report.status.toUpperCase()}</span>
                                    <a href="/api/report/${report.id}" target="_blank" class="btn" style="margin-left: 10px; padding: 8px 16px; font-size: 14px;">查看详情</a>
                                </div>
                            </li>
                        `;
                    });
                    html += '</ul>';
                    
                    container.innerHTML = html;
                })
                .catch(error => {
                    console.error('加载报告失败:', error);
                    container.innerHTML = '<p style="padding: 20px; text-align: center; color: #f56565;">加载失败: ' + error.message + '</p>';
                });
        }
        
        // 页面加载时自动获取报告列表
        document.addEventListener('DOMContentLoaded', loadReports);
    </script>
</body>
</html>
        """
        return html
    
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


