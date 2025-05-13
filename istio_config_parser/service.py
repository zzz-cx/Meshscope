import sys
import os
from flask import Flask, send_file, send_from_directory, jsonify, Response
from flask_cors import CORS
import mimetypes
import json

# 添加项目根目录到 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from istio_config_parser.main_parser import parse_control_plane_from_dir, parse_data_plane_from_dir

# 添加 .jsx 和 .mjs 的 MIME 类型映射
mimetypes.add_type('text/javascript', '.jsx')
mimetypes.add_type('text/javascript', '.mjs')

app = Flask(__name__, static_folder='static')
CORS(app)

@app.route('/')
def serve_react_app():
    return send_file(os.path.join(os.path.dirname(__file__), 'static/index.html'))

@app.route('/static/js/<path:filename>')
def serve_js(filename):
    try:
        # 确定文件路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        if filename.startswith('components/'):
            directory = os.path.join(current_dir, 'static/js/components')
            file = filename.replace('components/', '')
        elif filename.startswith('styles/'):
            directory = os.path.join(current_dir, 'static/js/styles')
            file = filename.replace('styles/', '')
        elif filename.startswith('utils/'):
            directory = os.path.join(current_dir, 'static/js/utils')
            file = filename.replace('utils/', '')
        else:
            directory = os.path.join(current_dir, 'static/js')
            file = filename

        file_path = os.path.join(directory, file)

        # 确定 MIME 类型
        if file.endswith('.css'):
            content_type = 'text/css'
        elif file.endswith(('.js', '.jsx', '.mjs')):
            content_type = 'text/javascript'
        else:
            content_type = mimetypes.guess_type(file)[0] or 'application/octet-stream'

        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 返回响应
        response = Response(content)
        response.headers['Content-Type'] = f'{content_type}; charset=utf-8'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    except Exception as e:
        print(f"Error serving {filename}: {e}")
        return '', 404

@app.route('/api/services')
def get_services():
    try:
        # 使用新的解析器
        current_dir = os.path.dirname(os.path.abspath(__file__))
        control_plane = parse_control_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config'), 
            'online-boutique'
        )
        data_plane = parse_data_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config')
        )
        
        # 合并控制平面和数据平面的结果
        result = {
            'services': control_plane['services'],
            'serviceRelations': {},
            'configurations': control_plane['configurations']
        }
        
        # 合并服务关系
        for service_name in set(control_plane['serviceRelations'].keys()) | set(data_plane['serviceRelations'].keys()):
            result['serviceRelations'][service_name] = {
                'incomingVirtualServices': control_plane['serviceRelations'].get(service_name, {}).get('incomingVirtualServices', []),
                'subsets': control_plane['serviceRelations'].get(service_name, {}).get('subsets', []),
                'rateLimit': control_plane['serviceRelations'].get(service_name, {}).get('rateLimit', []),
                'gateways': control_plane['serviceRelations'].get(service_name, {}).get('gateways', []),
                'dataPlane': {
                    'inbound': data_plane['serviceRelations'].get(service_name, {}).get('inbound', []),
                    'outbound': data_plane['serviceRelations'].get(service_name, {}).get('outbound', []),
                    'weights': data_plane['serviceRelations'].get(service_name, {}).get('weights', {})
                }
            }
        
        return jsonify(result)
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({
            'services': [],
            'serviceRelations': {},
            'configurations': {}
        })

@app.route('/api/services/<service_name>/details')
def get_service_detail(service_name):
    try:
        # 解析配置
        current_dir = os.path.dirname(os.path.abspath(__file__))
        control_plane = parse_control_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config'), 
            'online-boutique'
        )
        data_plane = parse_data_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config')
        )
        
        # 获取服务详情
        service_relations = control_plane['serviceRelations'].get(service_name, {})
        data_plane_relations = data_plane['serviceRelations'].get(service_name, {})
        
        # 获取完整的服务配置
        configurations = control_plane['configurations'].get(service_name, {})
        
        # 构建返回的详细信息
        details = {
            'relations': {
                'incomingVirtualServices': service_relations.get('incomingVirtualServices', []),
                'subsets': service_relations.get('subsets', []),
                'rateLimit': service_relations.get('rateLimit', []),
                'gateways': service_relations.get('gateways', []),
                'circuitBreaker': service_relations.get('circuitBreaker', None)
            },
            'configurations': configurations,  # 直接使用完整的配置对象
            'dataPlane': {
                'inbound': data_plane_relations.get('inbound', []),
                'outbound': data_plane_relations.get('outbound', []),
                'weights': data_plane_relations.get('weights', {})
            }
        }
        
        return jsonify(details)
    except Exception as e:
        print(f"Error getting details for {service_name}: {e}")
        return jsonify({
            'relations': {
                'incomingVirtualServices': [],
                'subsets': [],
                'rateLimit': [],
                'gateways': []
            },
            'configurations': {
                'virtualServices': [],
                'destinationRules': [],
                'envoyFilters': [],
                'weights': {},
                'circuitBreaker': None
            },
            'dataPlane': {
                'inbound': [],
                'outbound': [],
                'weights': {}
            }
        })

@app.route('/debug/api/services/<service_name>/details')
def debug_service_detail(service_name):
    """调试端点，用于显示API响应的详细信息"""
    try:
        # 解析配置
        current_dir = os.path.dirname(os.path.abspath(__file__))
        control_plane = parse_control_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config'), 
            'online-boutique'
        )
        data_plane = parse_data_plane_from_dir(
            os.path.join(current_dir, 'istio_control_config')
        )
        
        # 获取服务详情
        service_relations = control_plane['serviceRelations'].get(service_name, {})
        data_plane_relations = data_plane['serviceRelations'].get(service_name, {})
        configurations = control_plane['configurations'].get(service_name, {})
        
        # 构建详细信息
        details = {
            'relations': service_relations,
            'configurations': configurations,
            'dataPlane': data_plane_relations
        }
        
        # 格式化输出
        formatted_json = json.dumps(details, indent=2, ensure_ascii=False)
        response = Response(formatted_json, mimetype='application/json')
        return response
    except Exception as e:
        error_msg = f"Error debugging details for {service_name}: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 