"""
Web可视化服务器

提供交互式Web界面展示一致性验证结果
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime

try:
    from flask import Flask, render_template, jsonify, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    Flask = None

from consistency_checker.config import get_config
from consistency_checker.core.orchestrator import Pipeline

logger = logging.getLogger(__name__)


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
    
    def _render_index(self):
        """渲染主页"""
        # 简单的HTML返回
        html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Istio一致性验证系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px 20px; text-align: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
        .card { background: white; border-radius: 8px; padding: 25px; margin: 20px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        .btn { display: inline-block; padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; text-decoration: none; transition: background 0.3s; }
        .btn:hover { background: #5568d3; }
        .btn-secondary { background: #48bb78; }
        .btn-secondary:hover { background: #38a169; }
        .reports-list { list-style: none; }
        .report-item { background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #667eea; display: flex; justify-content: space-between; align-items: center; }
        .status-badge { padding: 5px 12px; border-radius: 15px; font-size: 12px; font-weight: bold; }
        .status-consistent { background: #48bb78; color: white; }
        .status-inconsistent { background: #f56565; color: white; }
        .status-partial { background: #ed8936; color: white; }
        .loading { text-align: center; padding: 40px; color: #999; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
</head>
<body>
    <div class="header">
        <h1>🔍 Istio配置一致性验证系统</h1>
        <p style="margin-top: 10px; opacity: 0.9;">全局化、系统化的配置验证与可视化平台</p>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>快速操作</h2>
            <div style="margin-top: 20px;">
                <button class="btn" onclick="runPipeline()">🚀 执行完整流水线</button>
                <button class="btn btn-secondary" onclick="loadReports()" style="margin-left: 10px;">📊 刷新报告列表</button>
            </div>
            <div id="status" style="margin-top: 15px; padding: 10px; border-radius: 5px; display: none;"></div>
        </div>
        
        <div class="card">
            <h2>验证报告</h2>
            <div id="reports-container">
                <div class="loading">加载中...</div>
            </div>
        </div>
    </div>
    
    <script>
        // 加载报告列表
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
        
        // 执行流水线
        function runPipeline() {
            const statusDiv = document.getElementById('status');
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#e6fffa';
            statusDiv.style.color = '#234e52';
            statusDiv.innerHTML = '⏳ 正在执行流水线，请稍候...';
            
            axios.post('/api/run_pipeline', {
                namespace: 'default'
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


