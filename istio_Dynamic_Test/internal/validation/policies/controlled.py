"""Legacy summary statistics are not evidence of retry or circuit breaking."""
from istio_Dynamic_Test.internal.models.testcase import (
    ValidationDetail, ValidationResult, ValidationStatus,
)
from .base import BaseValidator


def unavailable(test_case):
    message = (
        "需要隔离受控后端和可归因的实际尝试/代理溢出证据；"
        "未修改 VS，未发送无触发保证的负载。使用 relations --execute --profiles 执行新流程。"
        "连接池溢出与 outlierDetection 分开验证，异常实例摘除目前未提供通用执行器。"
    )
    return ValidationResult(
        case_id=test_case.case_id, overall_status=ValidationStatus.INCONCLUSIVE,
        details=[ValidationDetail(dimension="受控触发能力", status=ValidationStatus.INCONCLUSIVE,
                                  message=message)],
        summary="INCONCLUSIVE: " + message,
    )


class ControlledProbeRequiredValidator(BaseValidator):
    def __init__(self, *args, **kwargs):
        pass

    def validate(self, test_case, execution=None, collection=None):
        return unavailable(test_case)
