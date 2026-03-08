from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass(slots=True)
class PaperRecord:
    paper_id: str
    source_date: str
    title: str
    summary: str
    url: str
    arxiv_id: str | None
    relevance: str
    combined_score: float
    keyword_score: float
    llm_score: float | None
    reason: str
    metadata: dict[str, Any]


class StateDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fetch_state (
                    date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    file_path TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_state (
                    paper_id TEXT PRIMARY KEY,
                    source_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    url TEXT,
                    arxiv_id TEXT,
                    relevance TEXT NOT NULL,
                    combined_score REAL NOT NULL,
                    keyword_score REAL NOT NULL,
                    llm_score REAL,
                    reason TEXT,
                    metadata_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_paper_source_date
                ON paper_state(source_date);

                CREATE TABLE IF NOT EXISTS download_state (
                    arxiv_id TEXT PRIMARY KEY,
                    paper_id TEXT,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS digest_state (
                    window_key TEXT PRIMARY KEY,
                    output_path TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        self._conn.close()

    def was_date_synced(self, date_str: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM fetch_state WHERE date = ?",
            (date_str,),
        ).fetchone()
        return bool(row and row["status"] == "success")

    def latest_success_fetch_date(self) -> str | None:
        row = self._conn.execute(
            "SELECT date FROM fetch_state WHERE status = 'success' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return row["date"] if row else None

    def mark_date_sync(
        self,
        date_str: str,
        status: str,
        file_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO fetch_state(date, status, file_path, error, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    status = excluded.status,
                    file_path = excluded.file_path,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (date_str, status, file_path, error, _now()),
            )

    def upsert_paper(self, record: PaperRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO paper_state(
                    paper_id, source_date, title, summary, url, arxiv_id,
                    relevance, combined_score, keyword_score, llm_score, reason,
                    metadata_json, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    source_date = excluded.source_date,
                    title = excluded.title,
                    summary = excluded.summary,
                    url = excluded.url,
                    arxiv_id = excluded.arxiv_id,
                    relevance = excluded.relevance,
                    combined_score = excluded.combined_score,
                    keyword_score = excluded.keyword_score,
                    llm_score = excluded.llm_score,
                    reason = excluded.reason,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.paper_id,
                    record.source_date,
                    record.title,
                    record.summary,
                    record.url,
                    record.arxiv_id,
                    record.relevance,
                    record.combined_score,
                    record.keyword_score,
                    record.llm_score,
                    record.reason,
                    json.dumps(record.metadata, ensure_ascii=False),
                    _now(),
                ),
            )

    def is_pdf_downloaded(self, arxiv_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM download_state WHERE arxiv_id = ?",
            (arxiv_id,),
        ).fetchone()
        return bool(row and row["status"] == "success")

    def get_pdf_download_path(self, arxiv_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT file_path, status FROM download_state WHERE arxiv_id = ?",
            (arxiv_id,),
        ).fetchone()
        if row and row["status"] == "success":
            return row["file_path"]
        return None

    def mark_pdf_download(
        self,
        arxiv_id: str,
        paper_id: str | None,
        file_path: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO download_state(arxiv_id, paper_id, file_path, status, error, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(arxiv_id) DO UPDATE SET
                    paper_id = excluded.paper_id,
                    file_path = excluded.file_path,
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (arxiv_id, paper_id, file_path, status, error, _now()),
            )

    def get_digest_checksum(self, window_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT checksum FROM digest_state WHERE window_key = ?",
            (window_key,),
        ).fetchone()
        return row["checksum"] if row else None

    def upsert_digest(self, window_key: str, output_path: str, checksum: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO digest_state(window_key, output_path, checksum, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(window_key) DO UPDATE SET
                    output_path = excluded.output_path,
                    checksum = excluded.checksum,
                    updated_at = excluded.updated_at
                """,
                (window_key, output_path, checksum, _now()),
            )
