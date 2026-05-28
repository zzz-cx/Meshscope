"""按 TestCase 协议与策略选择 Executor。"""

from typing import Optional

from istio_Dynamic_Test.internal.models.protocol import Protocol
from istio_Dynamic_Test.internal.models.testcase import PolicyType, TestCase, TestType
from istio_Dynamic_Test.pkg.runtime.ssh import SSHClient
from istio_Dynamic_Test.internal.traffic.executors.base import BaseExecutor
from istio_Dynamic_Test.internal.traffic.executors.connection_pool_outlier import (
    ConnectionPoolOutlierExecutor,
)
from istio_Dynamic_Test.internal.traffic.executors.grpc import (
    GrpcExecutor,
    GrpcLoadExecutor,
    GrpcMeshExecutor,
)
from istio_Dynamic_Test.internal.traffic.executors.http import HttpExecutor
from istio_Dynamic_Test.internal.traffic.executors.load import LoadExecutor
from istio_Dynamic_Test.internal.traffic.executors.mesh import MeshExecutor


class ExecutorRegistry:
    """集中管理执行器实例与选择逻辑。"""

    def __init__(
        self,
        ssh_client: SSHClient,
        namespace: str = "default",
        custom: Optional[BaseExecutor] = None,
    ):
        self._custom = custom
        self._http = HttpExecutor(ssh_client)
        self._load = LoadExecutor(ssh_client)
        self._mesh = MeshExecutor(ssh_client, namespace=namespace)
        self._grpc = GrpcExecutor(ssh_client)
        self._grpc_load = GrpcLoadExecutor(ssh_client)
        self._grpc_mesh = GrpcMeshExecutor(ssh_client, namespace=namespace)
        self._cp_outlier = ConnectionPoolOutlierExecutor(ssh_client, namespace=namespace)

    def select(self, test_case: TestCase) -> BaseExecutor:
        if self._custom is not None:
            return self._custom
        if test_case.protocol == Protocol.GRPC:
            if (
                test_case.trigger_condition == "connection_pool_outlier_validation"
                or PolicyType.CONNECTION_POOL_OUTLIER in (test_case.policy_types or [])
            ):
                return self._cp_outlier
            if PolicyType.TRAFFIC_SPLIT in (test_case.policy_types or []):
                return self._grpc_mesh
            if test_case.test_type == TestType.LOAD_TEST:
                return self._grpc_load
            return self._grpc
        if (
            test_case.trigger_condition == "connection_pool_outlier_validation"
            or PolicyType.CONNECTION_POOL_OUTLIER in (test_case.policy_types or [])
        ):
            return self._cp_outlier
        if PolicyType.TRAFFIC_SPLIT in (test_case.policy_types or []):
            return self._mesh
        if test_case.test_type == TestType.LOAD_TEST:
            return self._load
        return self._http
