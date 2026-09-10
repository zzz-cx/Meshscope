"""持久化层。"""

from consistency_checker.storage.sqlite_store import SqliteStore, get_store

__all__ = ["SqliteStore", "get_store"]
