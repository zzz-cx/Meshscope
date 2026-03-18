"""ConfigGenerator —— 从 Istio 配置文件生成测试用例。

复用原有 generator/test_case_generator.py 中的全部解析逻辑，
包裹为符合 BaseGenerator 接口的新版 Generator。

支持在生成前从控制面配置目录同步最新配置到 istio_config.json。
"""

from __future__ import annotations

import json
import os
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

        return [
            TestCase.from_matrix_dict(rc, self._ingress_url)
            for rc in raw_cases
        ]

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
