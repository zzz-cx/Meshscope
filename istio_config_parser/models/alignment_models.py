"""
模型对齐层（Model Alignment Layer）
用于将控制平面和数据平面的功能模型进行对齐和匹配
"""
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from istio_config_parser.models.function_models import (
    AnyFunctionModel, FunctionType
)
from istio_config_parser.models.semantic_tuple import (
    compare_tuples,
    function_model_to_tuples,
)


class AlignmentStatus(Enum):
    """对齐状态"""
    MATCHED = "matched"  # 完全匹配
    PARTIAL_MATCHED = "partial_matched"  # 部分匹配
    CONTROL_ONLY = "control_only"  # 仅控制平面
    DATA_ONLY = "data_only"  # 仅数据平面
    MISMATCHED = "mismatched"  # 不匹配


def _destination_port_score(model: AnyFunctionModel) -> int:
    """同服务多 vhost 时，优先保留应用端口（9080）而不是 kube Service 端口 80。"""
    dests: List[Any] = []
    if getattr(model, "destinations", None):
        dests.extend(model.destinations or [])
    for route in getattr(model, "routes", None) or []:
        if isinstance(route, dict):
            dests.extend(route.get("destinations") or [])
    ports = []
    for dest in dests:
        if hasattr(dest, "port"):
            ports.append(dest.port)
        elif isinstance(dest, dict):
            ports.append(dest.get("port"))
    numeric = []
    for port in ports:
        try:
            if port is not None:
                numeric.append(int(port))
        except (TypeError, ValueError):
            continue
    if any(p != 80 for p in numeric):
        return 2
    if numeric:
        return 1
    return 0


@dataclass
class AlignedFunctionPair:
    """对齐的功能对"""
    function_type: FunctionType
    service_name: str
    namespace: str
    
    control_plane_model: Optional[AnyFunctionModel] = None
    data_plane_model: Optional[AnyFunctionModel] = None
    
    alignment_status: AlignmentStatus = AlignmentStatus.MATCHED
    differences: List[Dict[str, Any]] = field(default_factory=list)
    control_tuples: List[Dict[str, Any]] = field(default_factory=list)
    data_tuples: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_key(self) -> str:
        """生成唯一标识键"""
        return f"{self.namespace}.{self.service_name}.{self.function_type.value}"
    
    def has_control_plane(self) -> bool:
        """是否有控制平面配置"""
        return self.control_plane_model is not None
    
    def has_data_plane(self) -> bool:
        """是否有数据平面配置"""
        return self.data_plane_model is not None
    
    def is_complete(self) -> bool:
        """是否两个平面都有配置"""
        return self.has_control_plane() and self.has_data_plane()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'function_type': self.function_type.value,
            'service_name': self.service_name,
            'namespace': self.namespace,
            'control_plane': self.control_plane_model.to_dict() if self.control_plane_model else None,
            'data_plane': self.data_plane_model.to_dict() if self.data_plane_model else None,
            'alignment_status': self.alignment_status.value,
            'differences': self.differences,
            'control_tuples': self.control_tuples,
            'data_tuples': self.data_tuples,
        }


class ModelAligner:
    """模型对齐器"""
    
    def __init__(self, tau: float = 0.1, timeout_abs: float = 0.0):
        self.aligned_pairs: Dict[str, AlignedFunctionPair] = {}
        self.tau = tau
        self.timeout_abs = timeout_abs
    
    def align(
        self,
        control_plane_models: Dict[str, List[AnyFunctionModel]],
        data_plane_models: Dict[str, List[AnyFunctionModel]]
    ) -> Dict[str, AlignedFunctionPair]:
        """
        对齐控制平面和数据平面的功能模型
        
        Args:
            control_plane_models: 控制平面模型字典 {function_type: [models]}
            data_plane_models: 数据平面模型字典 {function_type: [models]}
            
        Returns:
            对齐后的功能对字典 {key: AlignedFunctionPair}
        """
        self.aligned_pairs = {}
        
        # 收集所有功能类型
        all_function_types = set()
        all_function_types.update(control_plane_models.keys())
        all_function_types.update(data_plane_models.keys())
        
        # 对每种功能类型进行对齐
        for func_type_str in all_function_types:
            # 转换字符串为枚举
            try:
                func_type = FunctionType(func_type_str)
            except ValueError:
                continue
            
            cp_models = control_plane_models.get(func_type_str, [])
            dp_models = data_plane_models.get(func_type_str, [])
            
            # 按服务和命名空间建立索引
            cp_index = self._index_models(cp_models)
            dp_index = self._index_models(dp_models)
            
            # 获取所有服务键
            all_keys = set(cp_index.keys()) | set(dp_index.keys())
            
            # 为每个服务创建对齐对
            for key in all_keys:
                namespace, service_name = self._parse_key(key)
                
                cp_model = cp_index.get(key)
                dp_model = dp_index.get(key)
                
                # 创建对齐对
                pair = AlignedFunctionPair(
                    function_type=func_type,
                    service_name=service_name,
                    namespace=namespace,
                    control_plane_model=cp_model,
                    data_plane_model=dp_model
                )
                
                cp_objs = function_model_to_tuples(pair.control_plane_model) if pair.control_plane_model else []
                dp_objs = function_model_to_tuples(pair.data_plane_model) if pair.data_plane_model else []
                pair.control_tuples = [t.to_dict() for t in cp_objs]
                pair.data_tuples = [t.to_dict() for t in dp_objs]
                pair.alignment_status, pair.differences = self._determine_alignment_status(pair, cp_objs, dp_objs)
                
                # 存储对齐对
                pair_key = pair.get_key()
                self.aligned_pairs[pair_key] = pair
        
        return self.aligned_pairs
    
    def _index_models(self, models: List[AnyFunctionModel]) -> Dict[str, AnyFunctionModel]:
        """
        为模型建立索引
        
        Returns:
            {namespace.service_name: model}
        """
        index = {}
        for model in models:
            key = f"{model.namespace}.{model.service_name}"
            if key not in index:
                index[key] = model
            elif _destination_port_score(model) > _destination_port_score(index[key]):
                # 同服务多 vhost（:80 Service 端口 vs :9080 应用端口）时保留应用端口投影
                index[key] = model
        return index
    
    def _parse_key(self, key: str) -> Tuple[str, str]:
        """解析键为命名空间和服务名"""
        parts = key.split('.', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return 'default', parts[0]
    
    def _determine_alignment_status(self, pair: AlignedFunctionPair, cp_tuples=None, dp_tuples=None):
        """离散字段精确相等，数值约束允许容差 tau。"""
        if pair.has_control_plane() and not pair.has_data_plane():
            return AlignmentStatus.CONTROL_ONLY, [{"kind": "presence", "description": "仅控制面有该功能"}]
        if pair.has_data_plane() and not pair.has_control_plane():
            return AlignmentStatus.DATA_ONLY, [{"kind": "presence", "description": "仅数据面有该功能"}]
        if not pair.has_control_plane() and not pair.has_data_plane():
            return AlignmentStatus.MISMATCHED, [{"kind": "presence", "description": "两侧均缺失"}]

        if cp_tuples is None:
            cp_tuples = function_model_to_tuples(pair.control_plane_model)
        if dp_tuples is None:
            dp_tuples = function_model_to_tuples(pair.data_plane_model)
        diffs: List[Dict[str, Any]] = []
        if len(cp_tuples) == 1 and len(dp_tuples) == 1:
            diffs = compare_tuples(cp_tuples[0], dp_tuples[0], self.tau, self.timeout_abs)
        else:
            dp_by_pred = {str(t.predicate): t for t in dp_tuples}
            used = set()
            for ct in cp_tuples:
                dt = dp_by_pred.get(str(ct.predicate))
                if dt is None and len(dp_tuples) == 1:
                    dt = dp_tuples[0]
                if dt is None:
                    diffs.append({
                        "kind": "discrete",
                        "field": "predicate",
                        "control": ct.predicate,
                        "data": None,
                        "description": "控制面规则在数据面无对应匹配条件",
                    })
                    continue
                used.add(id(dt))
                diffs.extend(compare_tuples(ct, dt, self.tau, self.timeout_abs))
            for dt in dp_tuples:
                if id(dt) not in used and len(cp_tuples) != 1:
                    diffs.append({
                        "kind": "discrete",
                        "field": "predicate",
                        "control": None,
                        "data": dt.predicate,
                        "description": "数据面规则在控制面无对应匹配条件",
                    })
        discrete = [d for d in diffs if d.get("kind") == "discrete"]
        if not diffs:
            return AlignmentStatus.MATCHED, []
        if discrete:
            return AlignmentStatus.MISMATCHED, diffs
        return AlignmentStatus.PARTIAL_MATCHED, diffs
    
    def get_matched_pairs(self) -> List[AlignedFunctionPair]:
        """获取完全匹配的对"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.alignment_status == AlignmentStatus.MATCHED
        ]

    def get_aligned_pairs(self) -> List[AlignedFunctionPair]:
        """完全匹配或部分匹配：可作为动态期望来源。"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.alignment_status in (AlignmentStatus.MATCHED, AlignmentStatus.PARTIAL_MATCHED)
        ]
    
    def get_control_only_pairs(self) -> List[AlignedFunctionPair]:
        """获取仅控制平面的对"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.alignment_status == AlignmentStatus.CONTROL_ONLY
        ]
    
    def get_data_only_pairs(self) -> List[AlignedFunctionPair]:
        """获取仅数据平面的对"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.alignment_status == AlignmentStatus.DATA_ONLY
        ]
    
    def get_pairs_by_service(self, service_name: str) -> List[AlignedFunctionPair]:
        """获取指定服务的所有对齐对"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.service_name == service_name
        ]
    
    def get_pairs_by_function_type(self, function_type: FunctionType) -> List[AlignedFunctionPair]:
        """获取指定功能类型的所有对齐对"""
        return [
            pair for pair in self.aligned_pairs.values()
            if pair.function_type == function_type
        ]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取对齐摘要"""
        total = len(self.aligned_pairs)
        matched = len(self.get_matched_pairs())
        partial = len([p for p in self.aligned_pairs.values() if p.alignment_status == AlignmentStatus.PARTIAL_MATCHED])
        mismatched = len([p for p in self.aligned_pairs.values() if p.alignment_status == AlignmentStatus.MISMATCHED])
        control_only = len(self.get_control_only_pairs())
        data_only = len(self.get_data_only_pairs())
        
        return {
            'total_pairs': total,
            'matched': matched,
            'partial_matched': partial,
            'mismatched': mismatched,
            'control_only': control_only,
            'data_only': data_only,
            'match_rate': (matched + partial) / total if total > 0 else 0,
            'tau': self.tau,
            'timeout_abs': self.timeout_abs,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'aligned_pairs': {
                key: pair.to_dict()
                for key, pair in self.aligned_pairs.items()
            },
            'summary': self.get_summary()
        }


@dataclass
class AlignmentResult:
    """对齐结果"""
    aligner: ModelAligner
    
    def __post_init__(self):
        self.summary = self.aligner.get_summary()
    
    def get_all_pairs(self) -> Dict[str, AlignedFunctionPair]:
        """获取所有对齐对"""
        return self.aligner.aligned_pairs
    
    def get_matched_pairs(self) -> List[AlignedFunctionPair]:
        """获取匹配的对"""
        return self.aligner.get_matched_pairs()
    
    def get_unmatched_pairs(self) -> List[AlignedFunctionPair]:
        """获取未匹配的对"""
        return [
            pair for pair in self.aligner.aligned_pairs.values()
            if pair.alignment_status != AlignmentStatus.MATCHED
        ]
    
    def get_services(self) -> List[str]:
        """获取所有服务名称"""
        services = set()
        for pair in self.aligner.aligned_pairs.values():
            services.add(pair.service_name)
        return sorted(list(services))
    
    def filter_by_service(self, service_name: str) -> List[AlignedFunctionPair]:
        """按服务名过滤"""
        return self.aligner.get_pairs_by_service(service_name)
    
    def filter_by_function_type(self, function_type: FunctionType) -> List[AlignedFunctionPair]:
        """按功能类型过滤"""
        return self.aligner.get_pairs_by_function_type(function_type)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'summary': self.summary,
            'aligned_pairs': self.aligner.to_dict()['aligned_pairs']
        }

