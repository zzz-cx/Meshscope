"""HTTP URL 拼装。"""


def compose_request_url(target_url: str, path: str) -> str:
    """合并 ingress 基础 URL 与用例 path，避免重复拼接 path 段。"""
    base = (target_url or "").rstrip("/")
    p = (path or "").strip()
    if not p or p == "/":
        return base if base else "/"
    if not p.startswith("/"):
        p = "/" + p
    if not base:
        return p
    if base.endswith(p):
        return base
    return f"{base}{p}"
