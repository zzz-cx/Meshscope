"""
中间表示（Intermediate Representation, IR）模型
统一表示控制平面和数据平面的配置，便于一致性验证
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from istio_config_parser.models.function_models import FunctionType
from istio_config_parser.models.alignment_models import AlignedFunctionPair, AlignmentStatus


class ConsistencyStatus(Enum):
    """一致性状态"""
    CONSISTENT = "consistent"  # 一致
    INCONSISTENT = "inconsistent"  # 不一致
    PARTIAL_CONSISTENT = "partial_consistent"  # 部分一致
    NOT_APPLICABLE = "not_applicable"  # 不适用
    UNKNOWN = "unknown"  # 未知


@dataclass
class ConsistencyIssue:
    """一致性问题"""
    field_path: str  # 字段路径
    control_plane_value: Any  # 控制平面值
    data_plane_value: Any  # 数据平面值
    severity: str = "warning"  # 严重程度: error, warning, info
    description: str = ""  # 问题描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'field_path': self.field_path,
            'control_plane_value': str(self.control_plane_value),
            'data_plane_value': str(self.data_plane_value),
            'severity': self.severity,
            'description': self.description
        }


@dataclass
class FunctionIR:
    """功能中间表示"""
    function_type: FunctionType
    service_name: str
    namespace: str
    
    # 统一的配置字段
    config: Dict[str, Any] = field(default_factory=dict)
    
    # 一致性验证结果
    consistency_status: ConsistencyStatus = ConsistencyStatus.UNKNOWN
    issues: List[ConsistencyIssue] = field(default_factory=list)
    
    # 原始对齐对引用
    aligned_pair: Optional[AlignedFunctionPair] = None
    
    def get_key(self) -> str:
        """生成唯一标识键"""
        return f"{self.namespace}.{self.service_name}.{self.function_type.value}"
    
    def add_issue(self, issue: ConsistencyIssue):
        """添加一致性问题"""
        self.issues.append(issue)
        
        # 更新一致性状态
        if self.consistency_status == ConsistencyStatus.CONSISTENT:
            if issue.severity == "error":
                self.consistency_status = ConsistencyStatus.INCONSISTENT
            else:
                self.consistency_status = ConsistencyStatus.PARTIAL_CONSISTENT
    
    def has_issues(self) -> bool:
        """是否有一致性问题"""
        return len(self.issues) > 0
    
    def get_error_count(self) -> int:
        """获取错误数量"""
        return sum(1 for issue in self.issues if issue.severity == "error")
    
    def get_warning_count(self) -> int:
        """获取警告数量"""
        return sum(1 for issue in self.issues if issue.severity == "warning")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'function_type': self.function_type.value,
            'service_name': self.service_name,
            'namespace': self.namespace,
            'config': self.config,
            'consistency_status': self.consistency_status.value,
            'issues': [issue.to_dict() for issue in self.issues],
            'error_count': self.get_error_count(),
            'warning_count': self.get_warning_count()
        }


@dataclass
class ServiceIR:
    """服务级中间表示"""
    service_name: str
    namespace: str
    
    # 各种功能的IR
    functions: Dict[str, FunctionIR] = field(default_factory=dict)
    
    def add_function_ir(self, function_ir: FunctionIR):
        """添加功能IR"""
        self.functions[function_ir.function_type.value] = function_ir
    
    def get_function_ir(self, function_type: FunctionType) -> Optional[FunctionIR]:
        """获取指定功能的IR"""
        return self.functions.get(function_type.value)
    
    def has_function(self, function_type: FunctionType) -> bool:
        """是否有指定功能"""
        return function_type.value in self.functions
    
    def get_consistency_status(self) -> ConsistencyStatus:
        """获取整体一致性状态"""
        if not self.functions:
            return ConsistencyStatus.NOT_APPLICABLE
        
        statuses = [func.consistency_status for func in self.functions.values()]
        
        # 如果有任何不一致，则整体不一致
        if ConsistencyStatus.INCONSISTENT in statuses:
            return ConsistencyStatus.INCONSISTENT
        
        # 如果有部分一致，则整体部分一致
        if ConsistencyStatus.PARTIAL_CONSISTENT in statuses:
            return ConsistencyStatus.PARTIAL_CONSISTENT
        
        # 如果全部一致，则整体一致
        if all(s == ConsistencyStatus.CONSISTENT for s in statuses):
            return ConsistencyStatus.CONSISTENT
        
        return ConsistencyStatus.UNKNOWN
    
    def get_all_issues(self) -> List[ConsistencyIssue]:
        """获取所有一致性问题"""
        issues = []
        for func in self.functions.values():
            issues.extend(func.issues)
        return issues
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'service_name': self.service_name,
            'namespace': self.namespace,
            'consistency_status': self.get_consistency_status().value,
            'functions': {
                func_type: func.to_dict()
                for func_type, func in self.functions.items()
            },
            'total_issues': len(self.get_all_issues()),
            'total_errors': sum(func.get_error_count() for func in self.functions.values()),
            'total_warnings': sum(func.get_warning_count() for func in self.functions.values())
        }


@dataclass
class SystemIR:
    """系统级中间表示"""
    services: Dict[str, ServiceIR] = field(default_factory=dict)
    
    def add_service_ir(self, service_ir: ServiceIR):
        """添加服务IR"""
        key = f"{service_ir.namespace}.{service_ir.service_name}"
        self.services[key] = service_ir
    
    def get_service_ir(self, service_name: str, namespace: str = "default") -> Optional[ServiceIR]:
        """获取指定服务的IR"""
        key = f"{namespace}.{service_name}"
        return self.services.get(key)
    
    def get_all_services(self) -> List[ServiceIR]:
        """获取所有服务IR"""
        return list(self.services.values())
    
    def get_inconsistent_services(self) -> List[ServiceIR]:
        """获取有一致性问题的服务"""
        return [
            service for service in self.services.values()
            if service.get_consistency_status() in [
                ConsistencyStatus.INCONSISTENT,
                ConsistencyStatus.PARTIAL_CONSISTENT
            ]
        ]
    
    def get_consistent_services(self) -> List[ServiceIR]:
        """获取一致的服务"""
        return [
            service for service in self.services.values()
            if service.get_consistency_status() == ConsistencyStatus.CONSISTENT
        ]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取系统级摘要"""
        total_services = len(self.services)
        consistent = len(self.get_consistent_services())
        inconsistent = len(self.get_inconsistent_services())
        
        total_issues = sum(len(service.get_all_issues()) for service in self.services.values())
        total_errors = sum(
            sum(func.get_error_count() for func in service.functions.values())
            for service in self.services.values()
        )
        total_warnings = sum(
            sum(func.get_warning_count() for func in service.functions.values())
            for service in self.services.values()
        )
        
        return {
            'total_services': total_services,
            'consistent_services': consistent,
            'inconsistent_services': inconsistent,
            'consistency_rate': consistent / total_services if total_services > 0 else 0,
            'total_issues': total_issues,
            'total_errors': total_errors,
            'total_warnings': total_warnings
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'summary': self.get_summary(),
            'services': {
                key: service.to_dict()
                for key, service in self.services.items()
            }
        }


class IRBuilder:
    """IR构建器"""
    
    @staticmethod
    def build_from_aligned_pairs(
        aligned_pairs: Dict[str, AlignedFunctionPair]
    ) -> SystemIR:
        """
        从对齐的功能对构建系统IR
        
        Args:
            aligned_pairs: 对齐后的功能对字典
            
        Returns:
            系统级IR
        """
        system_ir = SystemIR()
        
        # 按服务分组
        service_groups: Dict[str, Dict[str, AlignedFunctionPair]] = {}
        
        for key, pair in aligned_pairs.items():
            service_key = f"{pair.namespace}.{pair.service_name}"
            
            if service_key not in service_groups:
                service_groups[service_key] = {}
            
            service_groups[service_key][pair.function_type.value] = pair
        
        # 为每个服务构建ServiceIR
        for service_key, function_pairs in service_groups.items():
            namespace, service_name = service_key.split('.', 1)
            
            service_ir = ServiceIR(
                service_name=service_name,
                namespace=namespace
            )
            
            # 为每个功能构建FunctionIR
            for func_type_str, pair in function_pairs.items():
                function_ir = IRBuilder._build_function_ir(pair)
                service_ir.add_function_ir(function_ir)
            
            system_ir.add_service_ir(service_ir)
        
        return system_ir
    
    @staticmethod
    def _build_function_ir(pair: AlignedFunctionPair) -> FunctionIR:
        """从对齐对构建功能IR"""
        function_ir = FunctionIR(
            function_type=pair.function_type,
            service_name=pair.service_name,
            namespace=pair.namespace,
            aligned_pair=pair
        )
        
        # 根据对齐状态设置一致性状态
        if pair.alignment_status == AlignmentStatus.MATCHED:
            function_ir.consistency_status = ConsistencyStatus.CONSISTENT
        elif pair.alignment_status == AlignmentStatus.CONTROL_ONLY:
            function_ir.consistency_status = ConsistencyStatus.NOT_APPLICABLE
            function_ir.add_issue(ConsistencyIssue(
                field_path="data_plane",
                control_plane_value="configured",
                data_plane_value="missing",
                severity="error",
                description="数据平面缺少对应配置"
            ))
        elif pair.alignment_status == AlignmentStatus.DATA_ONLY:
            function_ir.consistency_status = ConsistencyStatus.NOT_APPLICABLE
            function_ir.add_issue(ConsistencyIssue(
                field_path="control_plane",
                control_plane_value="missing",
                data_plane_value="configured",
                severity="warning",
                description="控制平面缺少对应配置（可能是默认配置）"
            ))
        else:
            function_ir.consistency_status = ConsistencyStatus.UNKNOWN
        
        # 提取统一配置
        if pair.control_plane_model:
            function_ir.config['control_plane'] = pair.control_plane_model.to_dict()
        if pair.data_plane_model:
            function_ir.config['data_plane'] = pair.data_plane_model.to_dict()
        
        return function_ir


@dataclass
class SimpleIR:
    """简化版IR表示
    格式:
    {
        "service": str,
        "policy_type": str,
        "match": Dict[str, Any],
        "action": Dict[str, Any],
        "source": str  # "control_plane" or "data_plane"
    }
    """
    service: str
    policy_type: str
    match: Dict[str, Any] = field(default_factory=dict)
    action: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'service': self.service,
            'policy_type': self.policy_type,
            'match': self.match,
            'action': self.action,
            'source': self.source
        }


class SimpleIRConverter:
    """简化IR转换器"""
    
    @staticmethod
    def function_type_to_policy_type(function_type: FunctionType) -> str:
        """将功能类型转换为策略类型"""
        mapping = {
            FunctionType.ROUTING: "route",
            FunctionType.TRAFFIC_SHIFTING: "route",
            FunctionType.CIRCUIT_BREAKER: "circuit_breaker",
            FunctionType.RATE_LIMIT: "rate_limit",
            FunctionType.RETRY: "retry",
            FunctionType.TIMEOUT: "timeout",
            FunctionType.FAULT_INJECTION: "fault_injection",
            FunctionType.LOAD_BALANCING: "load_balancing",
        }
        return mapping.get(function_type, function_type.value)
    
    @staticmethod
    def extract_match_from_model(model_dict: Dict[str, Any], function_type: FunctionType) -> Dict[str, Any]:
        """从功能模型中提取匹配条件"""
        match = {}
        
        if function_type == FunctionType.ROUTING:
            # 从路由规则中提取第一个匹配条件
            routes = model_dict.get('routes', [])
            if routes and len(routes) > 0:
                route_match = routes[0].get('match', {})
                if route_match:
                    # 提取path信息
                    uri = route_match.get('uri', {})
                    if uri:
                        # 优先使用prefix/exact/regex
                        if 'prefix' in uri:
                            match['path'] = uri['prefix']
                        elif 'exact' in uri:
                            match['path'] = uri['exact']
                        elif 'regex' in uri:
                            match['path'] = uri['regex']
                    # 提取headers
                    headers = route_match.get('headers', {})
                    if headers:
                        match['headers'] = headers
                    # 提取method
                    method = route_match.get('method')
                    if method:
                        match['method'] = method
        elif function_type == FunctionType.TRAFFIC_SHIFTING:
            # 流量分流通常使用默认匹配（所有路径）
            match['path'] = "/"
        
        return match if match else {"path": "/"}
    
    @staticmethod
    def extract_action_from_model(model_dict: Dict[str, Any], function_type: FunctionType) -> Dict[str, Any]:
        """从功能模型中提取动作"""
        action = {}
        
        if function_type == FunctionType.TRAFFIC_SHIFTING:
            # 从destinations中提取权重分配
            destinations = model_dict.get('destinations', [])
            route_weights = {}
            
            total_weight = sum(d.get('weight', 0) for d in destinations)
            if total_weight > 0:
                for dest in destinations:
                    subset = dest.get('subset')
                    weight = dest.get('weight', 0)
                    # 转换为0-1之间的比例
                    if subset:
                        route_weights[subset] = round(weight / total_weight, 2)
                
                if route_weights:
                    action['route_weights'] = route_weights
        
        elif function_type == FunctionType.ROUTING:
            # 从路由规则中提取目标
            routes = model_dict.get('routes', [])
            if routes and len(routes) > 0:
                destinations = routes[0].get('destinations', [])
                if destinations:
                    action['destinations'] = destinations
        
        elif function_type == FunctionType.CIRCUIT_BREAKER:
            # 提取熔断配置
            connection_pool = model_dict.get('connection_pool')
            outlier_detection = model_dict.get('outlier_detection')
            if connection_pool:
                action['connection_pool'] = connection_pool
            if outlier_detection:
                action['outlier_detection'] = outlier_detection
        
        elif function_type == FunctionType.RATE_LIMIT:
            # 提取限流配置
            rules = model_dict.get('rules', [])
            if rules:
                action['rules'] = rules
        
        elif function_type == FunctionType.RETRY:
            # 提取重试配置
            retry_policy = model_dict.get('retry_policy')
            if retry_policy:
                action['retry_policy'] = retry_policy
        
        elif function_type == FunctionType.TIMEOUT:
            # 提取超时配置
            timeout = model_dict.get('timeout')
            if timeout:
                action['timeout'] = timeout
        
        elif function_type == FunctionType.FAULT_INJECTION:
            # 提取故障注入配置
            delay = model_dict.get('delay')
            abort = model_dict.get('abort')
            if delay:
                action['delay'] = delay
            if abort:
                action['abort'] = abort
        
        return action
    
    @staticmethod
    def convert_function_ir_to_simple(function_ir: FunctionIR, plane_type: str = "control_plane") -> List[SimpleIR]:
        """
        将FunctionIR转换为简化IR列表
        
        Args:
            function_ir: 功能IR
            plane_type: 平面类型 ("control_plane" 或 "data_plane")
            
        Returns:
            简化IR列表（可能包含多个规则）
        """
        simple_irs = []
        
        # 获取对应平面的配置
        plane_config = function_ir.config.get(plane_type, {})
        if not plane_config:
            return simple_irs
        
        policy_type = SimpleIRConverter.function_type_to_policy_type(function_ir.function_type)
        
        # 提取match和action
        match = SimpleIRConverter.extract_match_from_model(plane_config, function_ir.function_type)
        action = SimpleIRConverter.extract_action_from_model(plane_config, function_ir.function_type)
        
        # 创建简化IR
        simple_ir = SimpleIR(
            service=function_ir.service_name,
            policy_type=policy_type,
            match=match,
            action=action,
            source=plane_type
        )
        
        simple_irs.append(simple_ir)
        
        return simple_irs
    
    @staticmethod
    def convert_service_ir_to_simple(service_ir: ServiceIR, plane_type: str = "control_plane") -> List[SimpleIR]:
        """
        将ServiceIR转换为简化IR列表
        
        Args:
            service_ir: 服务IR
            plane_type: 平面类型
            
        Returns:
            简化IR列表
        """
        simple_irs = []
        
        for func_ir in service_ir.functions.values():
            irs = SimpleIRConverter.convert_function_ir_to_simple(func_ir, plane_type)
            simple_irs.extend(irs)
        
        return simple_irs
    
    @staticmethod
    def convert_system_ir_to_simple(system_ir: SystemIR, plane_type: str = "control_plane") -> List[SimpleIR]:
        """
        将SystemIR转换为简化IR列表
        
        Args:
            system_ir: 系统IR
            plane_type: 平面类型
            
        Returns:
            简化IR列表
        """
        simple_irs = []
        
        for service_ir in system_ir.services.values():
            irs = SimpleIRConverter.convert_service_ir_to_simple(service_ir, plane_type)
            simple_irs.extend(irs)
        
        return simple_irs
    
    @staticmethod
    def convert_function_ir_to_both_planes(function_ir: FunctionIR) -> Dict[str, List[SimpleIR]]:
        """
        将FunctionIR转换为控制平面和数据平面的简化IR
        
        Returns:
            {"control_plane": [...], "data_plane": [...]}
        """
        result = {
            "control_plane": [],
            "data_plane": []
        }
        
        # 转换控制平面
        if "control_plane" in function_ir.config:
            result["control_plane"] = SimpleIRConverter.convert_function_ir_to_simple(
                function_ir, "control_plane"
            )
        
        # 转换数据平面
        if "data_plane" in function_ir.config:
            result["data_plane"] = SimpleIRConverter.convert_function_ir_to_simple(
                function_ir, "data_plane"
            )
        
        return result
