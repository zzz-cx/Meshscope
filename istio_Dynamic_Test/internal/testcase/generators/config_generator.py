"""ConfigGenerator —— 动态用例入口。

期望只来自 parser 写出的 aligned_semantic.json（对齐后的语义元组）。
没有该文件时直接报错，不回退到 YAML / istio_config.json。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from istio_Dynamic_Test.internal.models.testcase import TestCase, TestSuite
from .base import BaseGenerator


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
    return {"name": meta.get("name", "unnamed"), "spec": resource.get("spec") or {}}


class ConfigGenerator(BaseGenerator):
    """从对齐后的语义模型生成测试用例。

    Args:
        config_path: 保留以兼容旧调用，sync_from_control_plane 仍会写入该路径。
        ingress_url: 集群入口 URL。
        namespace: 目标命名空间。
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
        """
        path = control_plane_path or self._control_plane_path
        if not path or not os.path.isdir(path):
            return False
        if not self._config_path.lower().endswith(".json"):
            return False

        cp_config = _load_control_plane_config(path, self._namespace)
        if not cp_config["virtualServices"] and not cp_config["destinationRules"]:
            return False

        existing: Dict[str, Any] = {}
        if os.path.isfile(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        updated = {
            "description": existing.get(
                "description",
                "声明需要进行动态测试的 Istio 策略。基于控制面配置同步。",
            ),
            "enabled_policies": existing.get(
                "enabled_policies",
                {"routing": True, "retry": True, "circuit_breaker": True, "rate_limit": False, "fault_injection": True},
            ),
            "envoyFilters": existing.get("envoyFilters", []),
            "virtualServices": [_k8s_to_istio_config_format(vs) for vs in cp_config["virtualServices"]],
            "destinationRules": [_k8s_to_istio_config_format(dr) for dr in cp_config["destinationRules"]],
        }

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
        return True

    def generate(self) -> List[TestCase]:
        from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator

        return SemanticGenerator(
            ingress_url=self._ingress_url,
            namespace=self._namespace,
        ).generate()

    def generate_suite(self, ingress_url: str = "") -> TestSuite:
        url = ingress_url or self._ingress_url
        return TestSuite(
            cases=self.generate(),
            global_settings={"ingress_url": url},
        )

    def save_matrix(self, output_path: str = "output_matrix.json") -> str:
        """将生成的测试矩阵保存为 JSON（来自对齐模型）。"""
        from istio_Dynamic_Test.internal.testcase.generators.semantic_generator import SemanticGenerator

        matrix = SemanticGenerator(
            ingress_url=self._ingress_url,
            namespace=self._namespace,
        ).generate_matrix()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(matrix, f, indent=2, ensure_ascii=False)
        return output_path
