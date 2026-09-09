"""SQLite 持久化：报告、检验记录、图与对齐产物。

本机单文件即可，不另起数据库进程。JSON / HTML 仍可导出，列表与详情以库为准。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    title TEXT,
    namespace TEXT,
    timestamp TEXT,
    overall_status TEXT,
    consistency_rate REAL,
    total_policies INTEGER DEFAULT 0,
    verified_policies INTEGER DEFAULT 0,
    finding_count INTEGER DEFAULT 0,
    html_path TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    report_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    inconsistency_type TEXT,
    severity TEXT,
    layer TEXT,
    resource_kind TEXT,
    resource_name TEXT,
    resource_namespace TEXT,
    function_type TEXT,
    alignment_status TEXT,
    description TEXT,
    affected_services_json TEXT,
    affected_subsets_json TEXT,
    sdecl_json TEXT,
    sdp_json TEXT,
    srt_json TEXT,
    root_cause TEXT,
    record_json TEXT NOT NULL,
    PRIMARY KEY (report_id, finding_id),
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS graphs (
    report_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (report_id, kind)
);

CREATE TABLE IF NOT EXISTS artifacts (
    kind TEXT NOT NULL,
    report_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, report_id)
);

CREATE INDEX IF NOT EXISTS idx_findings_layer ON findings(layer);
CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(inconsistency_type);
CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(timestamp DESC);
"""


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


class SqliteStore:
    """检验结果的 SQLite 仓库。"""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()
        logger.info("SQLite 已就绪: %s", self.path)

    def save_report(
        self,
        payload: Dict[str, Any],
        html_path: Optional[str] = None,
    ) -> str:
        """写入一份完整报告及其检验记录。"""
        report_id = payload.get("report_id") or payload.get("id")
        if not report_id:
            raise ValueError("报告缺少 report_id")
        cc = payload.get("consistency_check") or {}
        records = (
            payload.get("records")
            or payload.get("detailed_findings")
            or cc.get("inconsistencies")
            or []
        )
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._connect()
            try:
                # DELETE + INSERT，兼容 SQLite < 3.24（CentOS 7 为 3.7.17，无 UPSERT）
                conn.execute("DELETE FROM findings WHERE report_id = ?", (report_id,))
                conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
                conn.execute(
                    """
                    INSERT INTO reports (
                        id, title, namespace, timestamp, overall_status, consistency_rate,
                        total_policies, verified_policies, finding_count, html_path,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        payload.get("title"),
                        payload.get("namespace"),
                        payload.get("timestamp") or now,
                        cc.get("overall_status") or "unknown",
                        float(cc.get("consistency_rate") or 0),
                        int(cc.get("total_policies") or 0),
                        int(cc.get("verified_policies") or 0),
                        len(records),
                        html_path,
                        _dumps(payload),
                        now,
                    ),
                )
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    fid = rec.get("id") or rec.get("inconsistency_id") or rec.get("type")
                    if not fid:
                        continue
                    conn.execute(
                        """
                        INSERT INTO findings (
                            report_id, finding_id, inconsistency_type, severity, layer,
                            resource_kind, resource_name, resource_namespace, function_type,
                            alignment_status, description, affected_services_json,
                            affected_subsets_json, sdecl_json, sdp_json, srt_json,
                            root_cause, record_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            str(fid),
                            rec.get("inconsistency_type") or rec.get("type"),
                            rec.get("severity"),
                            rec.get("layer"),
                            rec.get("resource_kind"),
                            rec.get("resource_name"),
                            rec.get("resource_namespace"),
                            rec.get("function_type"),
                            rec.get("alignment_status"),
                            rec.get("description") or rec.get("title"),
                            _dumps(rec.get("affected_services") or []),
                            _dumps(rec.get("affected_subsets") or []),
                            _dumps(rec.get("Sdecl") or rec.get("s_decl")),
                            _dumps(rec.get("Sdp") or rec.get("s_dp")),
                            _dumps(rec.get("Srt") or rec.get("s_rt")),
                            rec.get("root_cause"),
                            _dumps(rec),
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
        logger.info("已写入报告 %s（%s 条记录）", report_id, len(records))
        return str(report_id)

    def list_reports(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, title, namespace, timestamp, overall_status, consistency_rate,
                           finding_count, html_path
                    FROM reports
                    ORDER BY timestamp DESC
                    """
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "namespace": row["namespace"],
                "timestamp": row["timestamp"],
                "status": row["overall_status"],
                "consistency_rate": row["consistency_rate"],
                "record_count": row["finding_count"],
                "has_html": bool(row["html_path"] and os.path.exists(row["html_path"] or "")),
            }
            for row in rows
        ]

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload_json FROM reports WHERE id = ?", (report_id,)
                ).fetchone()
            finally:
                conn.close()
        if not row:
            return None
        return _loads(row["payload_json"])

    def save_graph(self, report_id: str, kind: str, payload: Dict[str, Any]) -> None:
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM graphs WHERE report_id = ? AND kind = ?",
                    (report_id, kind),
                )
                conn.execute(
                    """
                    INSERT INTO graphs (report_id, kind, payload_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (report_id, kind, _dumps(payload), now),
                )
                conn.commit()
            finally:
                conn.close()

    def get_graph(self, report_id: str, kind: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if report_id == "latest":
                    row = conn.execute(
                        """
                        SELECT payload_json FROM graphs
                        WHERE kind = ?
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (kind,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT payload_json FROM graphs WHERE report_id = ? AND kind = ?",
                        (report_id, kind),
                    ).fetchone()
            finally:
                conn.close()
        return _loads(row["payload_json"]) if row else None

    def save_artifact(self, kind: str, payload: Any, report_id: str = "") -> None:
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._connect()
            try:
                rid = report_id or ""
                conn.execute(
                    "DELETE FROM artifacts WHERE kind = ? AND report_id = ?",
                    (kind, rid),
                )
                conn.execute(
                    """
                    INSERT INTO artifacts (kind, report_id, payload_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (kind, rid, _dumps(payload), now),
                )
                conn.commit()
            finally:
                conn.close()

    def get_artifact(self, kind: str, report_id: str = "") -> Optional[Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload_json FROM artifacts WHERE kind = ? AND report_id = ?",
                    (kind, report_id or ""),
                ).fetchone()
            finally:
                conn.close()
        return _loads(row["payload_json"]) if row else None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
                findings = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
                graphs = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
            finally:
                conn.close()
        return {
            "engine": "sqlite",
            "path": self.path,
            "reports": reports,
            "findings": findings,
            "graphs": graphs,
        }

    def import_json_reports(self, directory: str) -> int:
        """把 results/consistency/report_*.json 补进库（已有 id 则覆盖）。"""
        if not os.path.isdir(directory):
            return 0
        vis_dir = None
        count = 0
        for name in os.listdir(directory):
            if not (name.startswith("report_") and name.endswith(".json")):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("跳过无法导入的报告 %s: %s", path, exc)
                continue
            report_id = payload.get("report_id") or name[:-5]
            html = None
            parent = os.path.dirname(os.path.dirname(path))
            vis_dir = vis_dir or os.path.join(parent, "visualization")
            candidate = os.path.join(vis_dir, f"{report_id}_report.html")
            if os.path.exists(candidate):
                html = candidate
            self.save_report(payload, html_path=html)
            graph_file = os.path.join(vis_dir, f"{report_id}_three_layer_graph.json")
            if os.path.exists(graph_file):
                with open(graph_file, "r", encoding="utf-8") as f:
                    self.save_graph(report_id, "three_layer", json.load(f))
            topo = os.path.join(vis_dir, f"{report_id}_graph.json")
            if os.path.exists(topo):
                with open(topo, "r", encoding="utf-8") as f:
                    self.save_graph(report_id, "topology", json.load(f))
            count += 1
        if count:
            logger.info("从目录导入 %s 份报告: %s", count, directory)
        return count


_STORE: Optional[SqliteStore] = None
_STORE_PATH: Optional[str] = None
_STORE_LOCK = threading.Lock()


def get_store(path: Optional[str] = None) -> SqliteStore:
    """进程内单例。"""
    global _STORE, _STORE_PATH
    if path is None:
        from consistency_checker.config import get_config
        path = get_config().database_path
    path = os.path.abspath(path)
    with _STORE_LOCK:
        if _STORE is None or _STORE_PATH != path:
            _STORE = SqliteStore(path)
            _STORE_PATH = path
        return _STORE
