"""ConfigGenerator —— 从 Istio 配置文件生成测试用例。

复用原有 generator/test_case_generator.py 中的全部解析逻辑，
包裹为符合 BaseGenerator 接口的新版 Generator。

支持在生成前从控制面配置目录同步最新配置到 istio_config.json。
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from istio_Dynamic_Test.models.test_case import TestCase, TestSuite, TestType, PolicyType
from .base import BaseGenerator

# 复用原有 TestCaseGenerator 的核心逻辑
from istio_Dynamic_Test.generators.test_case_generator import TestCaseGenerator as _LegacyGenerator


def _load_control_plane_config(control_plane_path: str, namespace: str) -> Dict[str, Any]:
    """从控制面配置目录加载 VirtualService 和 DestinationRule。"""
    base = Path(control_plane_path)
    vs_list: List[Dict] = []
    dr_list: List[Dict] = []

    for res_dir, kind in [("virtualservices", "VirtualService"), ("destinationrules", "DestinationRule")]:
        dir_path = base / res_dir
        if not dir_path.exists():
            continue
        for fp in dir_path.rglob("*.yaml"):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for doc in yaml.safe_load_all(f):
                        if not doc or doc.get("kind") != kind:
                            continue
                        ns = (doc.get("metadata") or {}).get("namespace", "")
                        if ns and ns != namespace:
                            continue
                        if kind == "VirtualService":
                            vs_list.append(doc)
                        else:
                            dr_list.append(doc)
            except Exception:
                pass

    return {"virtualServices": vs_list, "destinationRules": dr_list}


def _k8s_to_istio_config_format(resource: Dict) -> Dict:
    """将 K8s 资源格式转为 istio_config 的 {name, spec} 格式。"""
    meta = resource.get("metadata") or {}
    name = meta.get("name", "unnamed")
    spec = resource.get("spec") or {}
    return {"name": name, "spec": spec}


class ConfigGenerator(BaseGenerator):
    """从 Istio 配置（JSON / YAML 目录）生成测试用例矩阵。

    内部委托给原有 ``TestCaseGenerator``，并将输出统一为
    ``TestCase`` 数据模型。

    若指定 control_plane_config_path，在 generate 前会从控制面配置
    同步最新 VirtualService/DestinationRule 到 istio_config.json。

    Args:
        config_path: Istio 配置文件路径（JSON 或包含 YAML 的目录）。
        service_deps_path: 服务依赖关系 JSON 路径（可选）。
        ingress_url: 集群入口 URL。
        namespace: 目标命名空间。
        control_plane_config_path: 控制面配置目录（如 istio_monitor/istio_control_config），
            若指定则在生成前同步最新配置到 config_path。
    """

    def __init__(
        self,
        config_path: str,
        service_deps_path: Optional[str] = None,
        ingress_url: str = "",
        namespace: str = "default",
        control_plane_config_path: Optional[str] = None,
    ):
        self._config_path = config_path
        self._service_deps_path = service_deps_path
        self._ingress_url = ingress_url
        self._namespace = namespace
        self._control_plane_path = control_plane_config_path

    def sync_from_control_plane(self, control_plane_path: Optional[str] = None) -> bool:
        """
        从控制面配置目录同步最新 VirtualService/DestinationRule 到 istio_config.json。
        保留原有 enabled_policies、description 等元数据。

        Returns:
            True 若成功同步并写回，False 若跳过（路径无效或 config_path 非 JSON）。
        """
        path = control_plane_path or self._control_plane_path
        if not path or not os.path.isdir(path):
            return False
        if not self._config_path.lower().endswith(".json"):
            return False

        cp_config = _load_control_plane_config(path, self._namespace)
        if not cp_config["virtualServices"] and not cp_config["destinationRules"]:
            return False

        # 读取现有配置以保留 enabled_policies 等
        existing: Dict[str, Any] = {}
        if os.path.isfile(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        # 转为 istio_config 格式并合并
        updated = {
            "description": existing.get(
                "description",
                "声明需要进行动态测试的 Istio 策略。基于控制面配置同步。",
            ),
            "enabled_policies": existing.get(
                "enabled_policies",
                {"routing": True, "retry": True, "circuit_breaker": True, "rate_limit": False, "fault_injection": True},
            ),
            # 保留用户在 istio_config.json 中声明的其他资源（例如限流 EnvoyFilter），避免被控制面同步覆盖。
            # 控制面同步当前只负责 VS/DR；其余资源以用户本地配置为准。
            "envoyFilters": existing.get("envoyFilters", []),
            "virtualServices": [_k8s_to_istio_config_format(vs) for vs in cp_config["virtualServices"]],
            "destinationRules": [_k8s_to_istio_config_format(dr) for dr in cp_config["destinationRules"]],
        }

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)

        return True

    def generate(self) -> List[TestCase]:
        # 若指定控制面配置路径，先同步最新配置
        if self._control_plane_path:
            if self.sync_from_control_plane():
                print(f"  [CONFIG] 已从控制面同步配置: {self._control_plane_path} -> {self._config_path}")

        legacy = _LegacyGenerator(
            self._config_path,
            service_deps_path=self._service_deps_path,
            namespace=self._namespace,
        )
        raw_cases: List[Dict[str, Any]] = legacy.generate()

        # 对 meshscope-verify：LegacyGenerator 会做“正交最小化”，导致只保留少数代表用例；
        # 当用户要求“对所有服务的配置进行检测”时，这种最小化会漏覆盖。
        # 这里补充：基于入口 VS（meshscope-synth-ingress）的每个 /s{i}/ 路由，追加 1 条 routing 检测用例，
        # 确保所有服务至少被命中一次（基于控制面同步后的真实配置）。
        try:
            extra = _build_ingress_route_probe_cases(self._config_path, self._ingress_url, self._namespace)
            if extra:
                raw_cases.extend(extra)
        except Exception:
            pass

        cases = [
            TestCase.from_matrix_dict(rc, self._ingress_url)
            for rc in raw_cases
        ]

        # ── 单入口（meshscope-synth-ingress）模型对齐：强制让用例走真实入口路径 ──────────
        # 你当前 meshscope-verify 的真实入口是 /s0/ /s1/ ...，仅靠 Host/FQDN 去打 "/" 会导致：
        # - 故障注入/熔断等策略“注入了但流量没命中入口路由”
        # - 用例数与实际入口可测对象不一致
        cases = _rewrite_meshscope_ingress_cases(cases)

        # ── 基于“当前控制面真实 VS”过滤：没有 timeout 的路由不生成 timeout 用例 ────────────
        # 真实集群里 meshscope-synth-ingress 的 /s{i}/ 路由若未配置 timeout，
        # 则 timeout validator 无论怎么跑都会是 WARNING（因为策略根本不存在）。
        # 这里直接剔除这些 timeout 用例，保证“只验证实际已部署的策略”。
        try:
            ingress_timeout_routes = _extract_ingress_timeout_routes(self._config_path, self._namespace)
            if ingress_timeout_routes is not None:
                filtered: List[TestCase] = []
                dropped = 0
                for tc in cases:
                    if PolicyType.TIMEOUT not in (tc.policy_types or []):
                        filtered.append(tc)
                        continue
                    svc = _normalize_service_name(tc.source_service or tc.host or "")
                    if svc.startswith("meshscope-svc-") and tc.path:
                        if not ingress_timeout_routes.get(tc.path, False):
                            dropped += 1
                            continue
                    filtered.append(tc)
                if dropped:
                    print(f"  [CONFIG] 用例过滤：入口 VS 未配置 timeout，剔除 timeout 用例 {dropped} 条")
                cases = filtered
        except Exception:
            pass

        # ── 关键增强：只验证“当前集群真实存在”的服务/策略 ─────────────────
        # 解决问题：
        # 1) 控制面快照可能残留 VS/DR（如 meshscope-svc-0002），但集群里实际没有对应 Service；
        # 2) meshscope-verify 未部署 EnvoyFilter/限流配置时，rate_limit 用例必失败且无意义。
        try:
            existing_svcs = _list_k8s_services(self._namespace)
            if existing_svcs:
                filtered: List[TestCase] = []
                dropped = 0
                for tc in cases:
                    # host='*' 时优先用 source_service 作为“真实目标服务”进行存在性过滤
                    src = (tc.source_service or "").strip()
                    svc = _normalize_service_name(src or (tc.host or ""))
                    if svc and svc not in existing_svcs and svc != "*":
                        dropped += 1
                        continue
                    filtered.append(tc)
                if dropped:
                    print(f"  [CONFIG] 用例过滤：按集群 Service 存在性剔除 {dropped} 条")
                cases = filtered

            # rate_limit：若命名空间无 EnvoyFilter，则剔除相关用例（避免“验证失败”误导）
            if not _has_envoyfilter(self._namespace):
                filtered = []
                dropped = 0
                for tc in cases:
                    if any(p.value == "rate_limit" for p in (tc.policy_types or [])):
                        dropped += 1
                        continue
                    filtered.append(tc)
                if dropped:
                    print(f"  [CONFIG] 用例过滤：namespace 未发现 EnvoyFilter，剔除 rate_limit {dropped} 条")
                cases = filtered
        except Exception:
            pass

        return cases

    def generate_suite(self, ingress_url: str = "") -> TestSuite:
        url = ingress_url or self._ingress_url
        cases = self.generate()
        return TestSuite(
            cases=cases,
            global_settings={"ingress_url": url},
        )

    # ── 便捷方法：与旧版 CLI 兼容 ────────────────────────────────────────

    def save_matrix(self, output_path: str = "output_matrix.json") -> str:
        """将生成的测试矩阵保存为旧版 JSON 格式（兼容 traffic_driver）。"""
        legacy = _LegacyGenerator(
            self._config_path,
            service_deps_path=self._service_deps_path,
            namespace=self._namespace,
        )
        raw_cases = legacy.generate()
        data = {
            "global_settings": {"ingress_url": self._ingress_url},
            "test_cases": raw_cases,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return output_path


def _kubectl_env() -> Dict[str, str]:
    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        env.pop(k, None)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _list_k8s_services(namespace: str) -> List[str]:
    """列出 namespace 下真实存在的 Service 名称列表。失败则返回空列表（不影响生成）。"""
    cmd = ["kubectl", "-n", namespace, "get", "svc", "-o", "jsonpath={.items[*].metadata.name}"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_kubectl_env(), universal_newlines=True)
    if p.returncode != 0:
        return []
    names = (p.stdout or "").strip().split()
    return [n for n in names if n]


def _has_envoyfilter(namespace: str) -> bool:
    cmd = ["kubectl", "-n", namespace, "get", "envoyfilter", "-o", "name"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_kubectl_env(), universal_newlines=True)
    if p.returncode != 0:
        return False
    return bool((p.stdout or "").strip())


def _normalize_service_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    if n == "*":
        return "*"
    # FQDN -> short
    if ".svc.cluster.local" in n:
        n = n.split(".svc.cluster.local", 1)[0]
    # meshscope-svc-0000.meshscope-verify -> meshscope-svc-0000
    if "." in n:
        n = n.split(".", 1)[0]
    return n


def _rewrite_meshscope_ingress_cases(cases: List[TestCase]) -> List[TestCase]:
    """
    将 meshscope-svc-XXXX 的用例重写为：
    - host='*'（避免 LoadExecutor 自动加 Host 头造成“根路径命中兜底路由”）
    - path='/s{idx}/'（保证走 meshscope-synth-ingress 的真实入口路由）
    并保留 source_service 用于采集/归因。
    """
    import re

    def _idx_from_svc(s: str) -> int:
        m = re.match(r"^meshscope-svc-(\d{4})$", s or "")
        return int(m.group(1)) if m else -1

    rewritten: List[TestCase] = []
    for tc in cases:
        svc = _normalize_service_name(tc.host or tc.source_service or "")
        idx = _idx_from_svc(svc)
        if idx >= 0:
            # 只要是 meshscope 合成服务，就强制走 /s{idx}/ 入口
            tc.source_service = svc
            tc.host = "*"  # 入口 VS hosts="*"，我们用 path 选路由即可
            # 若 generator 已有更具体 path（例如 /s0/v0/），保留；否则补 /s{idx}/
            if not (tc.path or "").startswith("/s"):
                tc.path = f"/s{idx}/"
        rewritten.append(tc)
    return rewritten


def _extract_ingress_timeout_routes(config_path: str, namespace: str) -> Optional[Dict[str, bool]]:
    """
    从同步后的 istio_config.json 里提取 meshscope-synth-ingress 上每个 path 前缀是否配置了 timeout。
    返回形如：{"/s0/": True, "/s1/": False, ...}
    若找不到 ingress VS，则返回 None（不做过滤）。
    """
    if not config_path or not str(config_path).endswith(".json") or not os.path.isfile(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    vs_items = data.get("virtualServices") or []
    ingress = None
    for it in vs_items:
        if (it.get("name") or "") == "meshscope-synth-ingress":
            ingress = it.get("spec") or {}
            break
    if not ingress:
        return None

    result: Dict[str, bool] = {}
    for http in (ingress.get("http") or []):
        timeout = http.get("timeout")
        has_timeout = bool(timeout)
        for m in (http.get("match") or []):
            uri = (m.get("uri") or {})
            prefix = uri.get("prefix")
            if prefix:
                result[prefix] = has_timeout
    return result


def _build_ingress_route_probe_cases(config_path: str, ingress_url: str, namespace: str) -> List[Dict[str, Any]]:
    """
    读取同步后的 istio_config.json，从 meshscope-synth-ingress 的 http.match[].uri.prefix 中提取路由，
    为每个 prefix 生成 1 条 single_request routing 探测用例：
    - host='*'，path=prefix
    - source_service=route destination host（用于 Collector/过滤/归因）
    """
    if not config_path or not str(config_path).endswith(".json") or not os.path.isfile(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    vs_items = data.get("virtualServices") or []
    ingress = None
    for it in vs_items:
        if (it.get("name") or "") == "meshscope-synth-ingress":
            ingress = it.get("spec") or {}
            break
    if not ingress:
        return []

    out: List[Dict[str, Any]] = []
    for http in (ingress.get("http") or []):
        matches = http.get("match") or []
        if not matches:
            continue
        # 取第一个 route destination host 作为 source_service
        route = (http.get("route") or [])
        if not route:
            continue
        dest0 = (route[0].get("destination") or {})
        dest_host = (dest0.get("host") or "").split(".")[0]
        if not dest_host:
            continue
        for m in matches:
            uri = (m.get("uri") or {})
            prefix = uri.get("prefix")
            if not prefix:
                continue
            # 用一个稳定的 pseudo case_id，避免与 legacy 的 case_XXX 冲突（后续 from_matrix_dict 会保留）
            cid = f"probe_{dest_host}_{prefix.strip('/').replace('/', '_')}"
            out.append({
                "case_id": cid,
                "description": f"[ALL-SVC-PROBE] 路由探测: GET {prefix} -> {dest_host}",
                "type": "single_request",
                "request_params": {"host": "*", "path": prefix},
                "expected_outcome": {"destination": "v1", "note": "覆盖所有入口路由，确保所有服务至少被命中一次"},
                "source_service": dest_host,
                "test_strategies": ["routing"],
            })
    return out
