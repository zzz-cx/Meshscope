"""传输协议枚举 —— 用于 Executor / Collector 按协议分发。"""

from enum import Enum


class Protocol(str, Enum):
    HTTP = "http"
    GRPC = "grpc"

    @classmethod
    def from_value(cls, value: str) -> "Protocol":
        if not value:
            return cls.HTTP
        v = str(value).strip().lower()
        for p in cls:
            if p.value == v:
                return p
        return cls.HTTP
