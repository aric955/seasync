"""
SeaSync V2.2 ProjectManager — SQLite 单例
负责项目生命周期管理：创建、加载、保存、列表。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import sqlite3
import json
import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from threading import local

from .data_models import (
    DataSourceMeta,
    AssociationResult,
    AlignmentResult,
    EventRecord,
)
from .association_config import AssociationConfig


class ProjectManager:
    """SQLite 单例，管理 SeaSync 项目数据库。"""

    _instance: Optional["ProjectManager"] = None
    _local = local()

    def __new__(cls, db_path: Optional[str] = None) -> "ProjectManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None) -> None:
        if self._initialized:
            return
        if db_path is None:
            # 默认：用户文档目录下的 seasync_projects.db
            docs = Path.home() / "Documents" / "SeaSync"
            docs.mkdir(parents=True, exist_ok=True)
            db_path = str(docs / "seasync_projects.db")
        self._db_path = db_path
        self._init_db()
        self._initialized = True

    # ── 连接管理（线程本地）─────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── 初始化数据库 Schema ───────────────────────────────────

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS data_sources (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL,
                meta_json   TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS association_results (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL,
                created_at  REAL NOT NULL,
                pairs_json  TEXT NOT NULL DEFAULT '[]',
                config_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS alignment_results (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL,
                created_at  REAL NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL,
                record_json TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ds_project   ON data_sources(project_id);
            CREATE INDEX IF NOT EXISTS idx_ar_project   ON association_results(project_id);
            CREATE INDEX IF NOT EXISTS idx_ev_project   ON events(project_id);
        """)
        conn.commit()

    # ── 项目 CRUD ─────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        description: str = "",
        config: Optional[AssociationConfig] = None,
    ) -> Dict[str, Any]:
        """创建新项目，返回项目元数据字典。"""
        import time as _time

        pid = str(uuid.uuid4())
        now = _time.time()
        cfg = config.to_dict() if config else AssociationConfig().to_dict()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO projects (id,name,description,created_at,updated_at,config_json)"
            " VALUES (?,?,?,?,?,?)",
            (pid, name, description, now, now, json.dumps(cfg, ensure_ascii=False)),
        )
        conn.commit()
        return {"id": pid, "name": name, "description": description, "created_at": now}

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """加载项目元数据，不含关联数据。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目（不含敏感字段）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id,name,description,created_at,updated_at FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[AssociationConfig] = None,
    ) -> bool:
        """更新项目元数据。"""
        import time as _time

        now = _time.time()
        project = self.get_project(project_id)
        if not project:
            return False
        fields, vals = [], []
        if name is not None:
            fields.append("name=?"); vals.append(name)
        if description is not None:
            fields.append("description=?"); vals.append(description)
        if config is not None:
            fields.append("config_json=?"); vals.append(json.dumps(config.to_dict(), ensure_ascii=False))
        fields.append("updated_at=?"); vals.append(now)
        vals.append(project_id)
        conn = self._get_conn()
        conn.execute(f"UPDATE projects SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
        return True

    def delete_project(self, project_id: str) -> bool:
        """删除项目及其所有关联数据（级联）。"""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        conn.commit()
        return cur.rowcount > 0

    # ── 数据源 ────────────────────────────────────────────────

    def add_data_source(self, project_id: str, meta: DataSourceMeta) -> str:
        """添加数据源，返回 source_id。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO data_sources (id,project_id,meta_json) VALUES (?,?,?)",
            (meta.id, project_id, json.dumps({
                "id": meta.id,
                "type": meta.type,
                "format": meta.format,
                "file_path": meta.file_path,
                "time_offset": meta.time_offset,
                "time_range": meta.time_range,
                "data_shape": meta.data_shape,
            }, ensure_ascii=False)),
        )
        conn.commit()
        return meta.id

    def list_data_sources(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT meta_json FROM data_sources WHERE project_id=?", (project_id,)
        ).fetchall()
        return [json.loads(r["meta_json"]) for r in rows]

    def remove_data_source(self, source_id: str) -> bool:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM data_sources WHERE id=?", (source_id,))
        conn.commit()
        return cur.rowcount > 0

    # ── 关联结果 ───────────────────────────────────────────────

    def save_association_result(
        self, project_id: str, result: AssociationResult, config: Optional[AssociationConfig] = None
    ) -> str:
        """保存关联结果，返回 result_id。"""
        import time as _time

        rid = str(uuid.uuid4())
        now = _time.time()
        cfg = config.to_dict() if config else {}
        pairs = [
            {
                "radar_track_id": p.radar_track_id,
                "ais_mmsi": p.ais_mmsi,
                "confidence": p.confidence,
                "method": p.method,
                "verified": p.verified,
                "top_candidates": p.top_candidates,
            }
            for p in result.pairs
        ]
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO association_results (id,project_id,created_at,pairs_json,config_json)"
            " VALUES (?,?,?,?,?)",
            (rid, project_id, now, json.dumps(pairs, ensure_ascii=False), json.dumps(cfg, ensure_ascii=False)),
        )
        conn.commit()
        return rid

    def list_association_results(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id,created_at,pairs_json,config_json FROM association_results"
            " WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r, pairs_json=json.loads(r["pairs_json"]), config_json=json.loads(r["config_json"]))
                for r in rows]

    # ── 对齐结果 ──────────────────────────────────────────────

    def save_alignment_result(
        self, project_id: str, result: AlignmentResult
    ) -> str:
        """保存对齐结果，返回 result_id。"""
        import time as _time

        rid = str(uuid.uuid4())
        now = _time.time()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO alignment_results (id,project_id,created_at,result_json)"
            " VALUES (?,?,?,?)",
            (rid, project_id, now, json.dumps({
                "offset": result.offset,
                "quality_score": result.quality_score,
                "suggestion": result.suggestion,
                "needs_manual": result.needs_manual,
            }, ensure_ascii=False)),
        )
        conn.commit()
        return rid

    def list_alignment_results(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id,created_at,result_json FROM alignment_results"
            " WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r, result_json=json.loads(r["result_json"])) for r in rows]

    # ── 事件记录 ───────────────────────────────────────────────

    def add_event(self, project_id: str, record: EventRecord) -> str:
        """添加事件，返回 event_id。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO events (id,project_id,record_json) VALUES (?,?,?)",
            (record.id, project_id, json.dumps({
                "id": record.id,
                "time": record.time,
                "name": record.name,
                "severity": record.severity,
                "description": record.description,
                "evidence_path": record.evidence_path,
                "auto_detected": record.auto_detected,
            }, ensure_ascii=False)),
        )
        conn.commit()
        return record.id

    def list_events(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT record_json FROM events WHERE project_id=? ORDER BY time ASC",
            (project_id,),
        ).fetchall()
        return [json.loads(r["record_json"]) for r in rows]

    # ── 统计摘要 ──────────────────────────────────────────────

    def get_project_summary(self, project_id: str) -> Dict[str, int]:
        """返回项目各表的记录数。"""
        conn = self._get_conn()
        ds_count = conn.execute(
            "SELECT COUNT(*) FROM data_sources WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        ar_count = conn.execute(
            "SELECT COUNT(*) FROM association_results WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        ev_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        return {"data_sources": ds_count, "association_results": ar_count, "events": ev_count}
