from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .schema import AnalysisRecord, ClientProfile


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.database_path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    client_code TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def upsert_client(self, profile: ClientProfile) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clients(client_code, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(client_code) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (profile.client_code, profile.model_dump_json(), now),
            )
            conn.commit()

    def list_clients(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT client_code FROM clients ORDER BY client_code").fetchall()
        return [r["client_code"] for r in rows]

    def get_client(self, client_code: str) -> ClientProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM clients WHERE client_code = ?", (client_code,)
            ).fetchone()
        if not row:
            return None
        return ClientProfile.model_validate_json(row["profile_json"])

    def save_analysis(self, record: AnalysisRecord) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO analyses(client_code, created_at, record_json) VALUES (?, ?, ?)",
                (
                    record.client_profile.client_code,
                    record.created_at.isoformat(),
                    record.model_dump_json(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_analyses(self, client_code: str | None = None, limit: int = 50) -> list[dict]:
        query = "SELECT id, client_code, created_at, record_json FROM analyses"
        params: list[object] = []
        if client_code:
            query += " WHERE client_code = ?"
            params.append(client_code)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        out = []
        for r in rows:
            record = json.loads(r["record_json"])
            out.append(
                {
                    "id": r["id"],
                    "client_code": r["client_code"],
                    "created_at": r["created_at"],
                    "record": record,
                }
            )
        return out

    def get_analysis(self, analysis_id: int) -> AnalysisRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        if not row:
            return None
        return AnalysisRecord.model_validate_json(row["record_json"])
