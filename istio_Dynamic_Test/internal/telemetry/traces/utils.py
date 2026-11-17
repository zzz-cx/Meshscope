"""
链路追踪工具：仅支持 Jaeger API，用于 Istio 动态行为验证。
通过 get_observability_config 获取 Jaeger 地址。
API 路径：{base_url}/jaeger/api/services 等，可通过 JAEGER_BASE_PATH 覆盖（默认 /jaeger，空字符串表示 /api）。
采集结果保存到 results/Tracing 目录。
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime

import requests
from py_zipkin.zipkin import ZipkinAttrs

from .observability_config import get_observability_config

# 采集结果保存目录：istio_Dynamic_Test/results/Tracing
_TRACING_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results", "Tracing")


def _ensure_tracing_dir():
    """确保 Tracing 目录存在。"""
    os.makedirs(_TRACING_DIR, exist_ok=True)
    return _TRACING_DIR


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

def _safe_str(val) -> str:
    """将值转为 UTF-8 安全字符串，避免乱码。"""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    s = str(val)
    # 替换无效 surrogate 字符
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _jaeger_span_to_zipkin(span: dict, processes: dict = None) -> dict:
    """将 Jaeger span 格式转为 Zipkin 兼容格式（含 id, parentId, localEndpoint.serviceName）。"""
    span_id = _safe_str(span.get("spanID") or span.get("id", ""))
    refs = span.get("references") or []
    parent_id = refs[0].get("spanID") if refs and refs[0].get("refType") == "CHILD_OF" else None
    if parent_id is not None:
        parent_id = _safe_str(parent_id)
    processes = processes or {}
    process = span.get("process") or processes.get(span.get("processID"), {})
    if isinstance(process, str):
        process = processes.get(process, {})
    service_name = _safe_str(
        process.get("serviceName")
        or (span.get("tags") or {}).get("peer.service")
        or "unknown"
    )
    return {
        "id": span_id,
        "parentId": parent_id,
        "localEndpoint": {"serviceName": service_name},
        "name": _safe_str(span.get("operationName", "")),
        "duration": span.get("duration", 0),
    }


def build_trace_tree(spans):
    """从 span 列表构建调用树（Jaeger 格式）。"""
    if not spans:
        return []
    normalized = []
    for s in spans:
        if "spanID" in s or "operationName" in s:
            normalized.append(_jaeger_span_to_zipkin(s))
        else:
            normalized.append(s)
    spans = normalized

    id_map = {span["id"]: span for span in spans}
    parent_map = {}
    for span in spans:
        parent_map.setdefault(span.get("parentId"), []).append(span)
    roots = [span for span in spans if not span.get("parentId") or span.get("parentId") not in id_map]

    def build_node(span):
        svc = span.get("localEndpoint", {}).get("serviceName")
        children = [build_node(child) for child in parent_map.get(span["id"], [])]
        return {"service": svc, "children": children}

    return [build_node(root) for root in roots]

def print_trace_tree(tree, indent=0, file=None):
    for node in tree:
        line = '  ' * indent + (node.get('service') or 'unknown')
        if file:
            print(line, file=file)
        else:
            print(line)
        print_trace_tree(node['children'], indent + 1, file)

# ---------- Jaeger API ----------
# GET /jaeger/api/services
# GET /jaeger/api/traces?service=xxx&limit=20
# GET /jaeger/api/traces/{traceID}


def _jaeger_api_base(base_url: str) -> str:
    """
    API 基础路径，拼接为 {base_url}{path}，最终 API 为 {result}/api/...。
    默认 path=/jaeger，即 API 在 http://host:16686/jaeger/api 下。
    可通过 JAEGER_BASE_PATH 覆盖：设为 "" 表示 API 在根路径 /api。
    """
    path = os.environ.get("JAEGER_BASE_PATH", "/jaeger").rstrip("/")
    base = base_url.rstrip("/")
    if not path:
        return base
    return f"{base}{path}" if path.startswith("/") else f"{base}/{path}"


def _safe_json(resp):
    """安全解析 JSON，非 JSON 响应返回 None。强制 UTF-8 避免乱码。"""
    try:
        if not resp.text:
            return None
        # 强制使用 UTF-8 解析，避免 Jaeger 返回非 UTF-8 时出现乱码
        resp.encoding = resp.encoding or "utf-8"
        return resp.json()
    except (json.JSONDecodeError, ValueError, requests.exceptions.JSONDecodeError):
        return None


def check_jaeger(base_url: str) -> dict:
    """
    检测 Jaeger API 是否可达。返回 {"ok": bool, "services": list, "message": str}。
    """
    url = f"{_jaeger_api_base(base_url)}/api/services"
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as e:
        return {"ok": False, "services": [], "message": f"连接失败: {e}"}
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return {
            "ok": False,
            "services": [],
            "message": f"返回 HTML 而非 JSON (content-type={ct})，请检查代理是否将 /api/* 转发到 Jaeger，或使用 kubectl port-forward svc/jaeger-query 16686:16686",
        }
    data = _safe_json(resp)
    if not isinstance(data, dict):
        return {"ok": False, "services": [], "message": "响应非 JSON"}
    services = data.get("data") or []
    return {"ok": True, "services": services, "message": f"OK, {len(services)} 个服务"}


def _fetch_trace_jaeger(base_url: str, trace_id: str) -> list:
    """通过 Jaeger API 获取单个 trace，并转为 Zipkin 兼容的 span 列表。"""
    url = f"{_jaeger_api_base(base_url)}/api/traces/{trace_id}"
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    data = _safe_json(resp)
    if not isinstance(data, dict):
        return []
    traces = data.get("data") or []
    if not traces:
        return []
    trace = traces[0]
    spans = trace.get("spans") or []
    processes = trace.get("processes") or {}
    return [_jaeger_span_to_zipkin(s, processes) for s in spans]


def fetch_traces_by_service(
    base_url: str,
    service: str,
    limit: int = 20,
    start: int = None,
    end: int = None,
) -> list:
    """按服务名查询 traces（Jaeger API）。"""
    url = f"{_jaeger_api_base(base_url)}/api/traces"
    params = {"service": service, "limit": limit}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    data = _safe_json(resp)
    if not isinstance(data, dict):
        return []
    return data.get("data") or []


def get_services_list(base_url: str) -> list:
    """获取所有服务列表（Jaeger API）。"""
    url = f"{_jaeger_api_base(base_url)}/api/services"
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    data = _safe_json(resp)
    if not isinstance(data, dict):
        return []
    return data.get("data") or []


def get_service_chain_by_traceid(tracing_base_url: str, trace_id: str):
    """根据 traceId 获取调用链树结构（Jaeger API）。"""
    if not tracing_base_url:
        cfg = get_observability_config()
        tracing_base_url = cfg.get("tracing_url") or cfg.get("zipkin_url") or ""
    spans = _fetch_trace_jaeger(tracing_base_url, trace_id)
    if not spans:
        return []
    return build_trace_tree(spans)


def wait_for_trace(tracing_url: str, trace_id: str, max_wait: int = 300):
    """等待 trace 出现并返回 spans（Jaeger API）。"""
    for _ in range(max_wait):
        spans = _fetch_trace_jaeger(tracing_url, trace_id)
        if spans:
            return spans
        time.sleep(1)
    return None

def count_nodes(tree):
    if not tree:
        return 0
    return 1 + sum(count_nodes(child) for child in tree.get('children', []))

def select_largest_tree(trees):
    if not trees:
        return None
    return max(trees, key=count_nodes)

def collect_trace_chain(
    service: str = "productpage",
    num_requests: int = 30,
    ingress_path: str = "/productpage",
) -> dict:
    """
    自动化采集调用链：发送请求 → 调用 Jaeger API → 选择 span 数量最多的 trace，返回其最大调用树。
    """
    cfg = get_observability_config(ingress_path=ingress_path)
    tracing_url = cfg.get("tracing_url") or cfg.get("zipkin_url")
    ingress_url = cfg.get("ingress_url")

    if not tracing_url or not ingress_url:
        raise RuntimeError("未找到 Jaeger 或 ingress 服务，请部署或设置 JAEGER_URL 环境变量")

    # 收集 (spans, tree_list)，按 span 数量选择最完整的 trace
    trace_candidates = []
    for _ in range(num_requests):
        headers, trace_id = gen_trace_headers()
        requests.get(ingress_url, headers=headers)
        spans = wait_for_trace(tracing_url, trace_id)
        if spans:
            tree_list = build_trace_tree(spans)
            trace_candidates.append((len(spans), spans, tree_list))

    if not trace_candidates:
        return {"tree": None, "tracing_url": tracing_url, "span_count": 0}

    # 选择 span 数量最多的 trace，再从中取节点最多的树（应对多 root 情况）
    best = max(trace_candidates, key=lambda x: x[0])
    _, _, tree_list = best
    largest = select_largest_tree(tree_list)
    return {"tree": largest, "tracing_url": tracing_url, "span_count": best[0]}


if __name__ == "__main__":
    # 修复 Windows 控制台中文乱码
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    cfg = get_observability_config(ingress_path="/productpage")
    tracing_url = cfg.get("tracing_url") or cfg.get("zipkin_url")

    if not tracing_url:
        print("未找到 Jaeger 服务，请部署或设置 JAEGER_URL 环境变量")
        exit(1)

    print(f"Jaeger URL: {tracing_url}")
    check = check_jaeger(tracing_url)
    print(f"连接检测: {check['message']}")
    if not check["ok"]:
        exit(1)
    if check["services"]:
        print(f"服务列表: {check['services'][:8]}...")

    result = collect_trace_chain(service="productpage", num_requests=30)
    largest_tree = result["tree"]
    print(f"Jaeger URL: {result['tracing_url']}")
    if result.get("span_count"):
        print(f"已选择 span 数最多的 trace（共 {result['span_count']} 个 span）")
    if not largest_tree:
        print("未采集到有效调用链")
        exit(1)
    print("最终主调用链:")
    print_trace_tree([largest_tree])

    _ensure_tracing_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = os.path.join(_TRACING_DIR, f"trace_chain_{ts}.txt")
    json_path = os.path.join(_TRACING_DIR, f"trace_chain_{ts}.json")
    with open(txt_path, "w", encoding="utf-8") as f:
        print_trace_tree([largest_tree], file=f)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(largest_tree, f, ensure_ascii=False, indent=2)
    print(f"主链路已保存到 {txt_path}")
    print(f"JSON 已保存到 {json_path}")
