import requests
import uuid
from py_zipkin.zipkin import ZipkinAttrs
import time
import json

def gen_trace_headers():
    trace_id = uuid.uuid4().hex[:16]
    span_id = uuid.uuid4().hex[:16]
    parent_span_id = None
    flags = '0'
    is_sampled = '1'
    zipkin_attrs = ZipkinAttrs(trace_id, span_id, parent_span_id, flags, is_sampled)
    headers = {
        'x-b3-traceid': zipkin_attrs.trace_id,
        'x-b3-spanid': zipkin_attrs.span_id,
        'x-b3-sampled': zipkin_attrs.is_sampled,
    }
    return headers, zipkin_attrs.trace_id

def build_trace_tree(spans):
    # 兼容嵌套结构
    if spans and isinstance(spans[0], list):
        spans = spans[0]
    id_map = {span['id']: span for span in spans}
    parent_map = {}
    for span in spans:
        parent_map.setdefault(span.get('parentId'), []).append(span)
    roots = [span for span in spans if not span.get('parentId') or span.get('parentId') not in id_map]
    def build_node(span):
        svc = span.get('localEndpoint', {}).get('serviceName')
        children = [build_node(child) for child in parent_map.get(span['id'], [])]
        return {'service': svc, 'children': children}
    return [build_node(root) for root in roots]

def print_trace_tree(tree, indent=0, file=None):
    for node in tree:
        line = '  ' * indent + node['service']
        if file:
            print(line, file=file)
        else:
            print(line)
        print_trace_tree(node['children'], indent + 1, file)

def get_service_chain_by_traceid(zipkin_base_url, trace_id):
    resp = requests.get(f"{zipkin_base_url}/api/v2/trace/{trace_id}")
    if resp.status_code != 200:
        print(f"Zipkin返回非200: {resp.status_code}")
        print(resp.text)
        return []
    try:
        spans = resp.json()
    except Exception as e:
        print("Zipkin返回内容无法解析为JSON:", resp.text)
        return []
    # 返回树结构
    return build_trace_tree(spans)

def wait_for_trace(zipkin_url, trace_id, max_wait=300):
    for i in range(max_wait):
        resp = requests.get(f"{zipkin_url}/api/v2/trace/{trace_id}")
        if resp.status_code == 200:
            return resp.json()
        time.sleep(1)
    print(f"traceId {trace_id} not found after {max_wait} seconds")
    return None

def count_nodes(tree):
    if not tree:
        return 0
    return 1 + sum(count_nodes(child) for child in tree.get('children', []))

def select_largest_tree(trees):
    if not trees:
        return None
    return max(trees, key=count_nodes)

if __name__ == "__main__":
    zipkin_url = "http://192.168.92.131:31443"
    ingress_url = "http://192.168.92.131:30476/productpage"
    all_trees = []
    for i in range(10):
        headers, trace_id = gen_trace_headers()
        resp = requests.get(ingress_url, headers=headers)
        print("请求状态码:", resp.status_code)
        print("traceId:", trace_id)
        print(f"在 Zipkin 查询 traceId: {trace_id}")
        wait_for_trace(zipkin_url, trace_id)
        tree_list = get_service_chain_by_traceid(zipkin_url, trace_id)
        all_trees.extend(tree_list)
    # 选最大树
    largest_tree = select_largest_tree(all_trees)
    print("最终主调用链:")
    print_trace_tree([largest_tree])
    # 保存到文件
    with open("trace_chain.txt", "w", encoding="utf-8") as f:
        print_trace_tree([largest_tree], file=f)
    with open("trace_chain.json", "w", encoding="utf-8") as f:
        json.dump(largest_tree, f, ensure_ascii=False, indent=2)
    print("主链路已保存到 trace_chain.txt 和 trace_chain.json")
