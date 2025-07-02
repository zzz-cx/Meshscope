from dill.logger import trace
import requests
import json
import istio_Dynamic_Test.utils.trace_utils as trace_utils

zipkin_url = "http://192.168.92.131:31443"
ingress_url = "http://192.168.92.131:30476/productpage"
all_trees = []
for i in range(10):
    headers, trace_id = trace_utils.gen_trace_headers()
    resp = requests.get(ingress_url, headers=headers)
    print("请求状态码:", resp.status_code)
    print("traceId:", trace_id)
    print(f"在 Zipkin 查询 traceId: {trace_id}")
    trace_utils.wait_for_trace(zipkin_url, trace_id)
    tree_list = trace_utils.get_service_chain_by_traceid(zipkin_url, trace_id)
    all_trees.extend(tree_list)
# 选最大树
largest_tree = trace_utils.select_largest_tree(all_trees)
print("最终主调用链:")
trace_utils.print_trace_tree([largest_tree])
# 保存到文件
with open("trace_chain.txt", "w", encoding="utf-8") as f:
    trace_utils.print_trace_tree([largest_tree], file=f)
with open("trace_chain.json", "w", encoding="utf-8") as f:
    json.dump(largest_tree, f, ensure_ascii=False, indent=2)
print("主链路已保存到 trace_chain.txt 和 trace_chain.json")