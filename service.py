from flask import Flask, send_file, send_from_directory, jsonify, Response
from flask_cors import CORS
from parse_yaml import parse_yaml_files, get_service_details
from parse_envoy_config import get_service_data_plane_config
import os
import mimetypes

# 添加 .jsx 和 .mjs 的 MIME 类型映射
mimetypes.add_type('text/javascript', '.jsx')
mimetypes.add_type('text/javascript', '.mjs')

app = Flask(__name__, static_folder='static')
CORS(app)

@app.route('/')
def serve_react_app():
    return send_file('static/index.html')

@app.route('/static/js/<path:filename>')
def serve_js(filename):
    try:
        # 确定文件路径
        if filename.startswith('components/'):
            directory = app.root_path + '/static/js/components'
            file = filename.replace('components/', '')
        elif filename.startswith('styles/'):
            directory = app.root_path + '/static/js/styles'
            file = filename.replace('styles/', '')
        elif filename.startswith('utils/'):
            directory = app.root_path + '/static/js/utils'
            file = filename.replace('utils/', '')
        else:
            directory = app.root_path + '/static/js'
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
        data = parse_yaml_files('online-boutique-service.yaml', 'online-boutique.yaml')
        return jsonify(data)
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
        control_plane_details = get_service_details(service_name)
        data_plane_details = get_service_data_plane_config(service_name)
        
        details = {
            'relations': control_plane_details['relations'],
            'configurations': control_plane_details['configurations'],
            'dataPlane': {
                'inbound': data_plane_details['inbound'],
                'outbound': data_plane_details['outbound'],
                'weights': data_plane_details['weights']  # 确保权重数据被传递
            }
        }
        
        print(f"\nService details for {service_name}:")
        print("Data plane details:", data_plane_details)  # 添加数据平面配置的调试输出
        
        return jsonify(details)
    except Exception as e:
        print(f"Error getting details for {service_name}: {e}")
        return jsonify({
            'relations': {
                'incomingVirtualServices': [],
                'subsets': [],
                'rateLimit': None
            },
            'configurations': {
                'virtualServices': [],
                'destinationRules': [],
                'envoyFilters': []
            },
            'dataPlane': {
                'inbound': [],
                'outbound': [],
                'weights': {}
            }
        })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)