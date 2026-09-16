from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jieba


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageResult:
    document_id: int
    deduplicated: bool


class DocumentStore:
    """SQLite source of truth plus a jieba-backed FTS5 projection."""

    def __init__(self, database_path: str, dictionary_path: str):
        self.database_path = Path(database_path)
        self.dictionary_path = Path(dictionary_path)
        self.schema_path = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
        self.initialization_error: str | None = None

    @property
    def available(self) -> bool:
        return self.initialization_error is None and self.database_path.exists()

    def initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            if self.dictionary_path.is_file() and self.dictionary_path.stat().st_size:
                jieba.load_userdict(str(self.dictionary_path))
            with self._connect() as connection:
                connection.executescript(self.schema_path.read_text(encoding="utf-8"))
            self.initialization_error = None
        except Exception as exc:
            self.initialization_error = f"{exc.__class__.__name__}: {str(exc)[:180]}"

    def persist(
        self,
        *,
        requested_url: str,
        final_url: str,
        content: str,
        page: dict[str, Any],
        strategy: str,
        status_code: int | None,
        content_type: str | None,
        attempts: list[dict[str, Any]],
        raw_response: dict[str, Any],
    ) -> StorageResult:
        self._require_available()
        normalized_hash_source = unicodedata.normalize("NFKC", content).replace("\r\n", "\n").strip()
        content_hash = hashlib.sha256(normalized_hash_source.encode("utf-8")).hexdigest()
        tags = self.normalize_tags(page.get("tags"))
        now = datetime.now(UTC).isoformat()
        document_url = self._as_text(page.get("url")) or final_url
        hostname = self._as_text(page.get("hostname")) or urlsplit(document_url).hostname or ""
        if not hostname:
            raise StorageError("document hostname is required")

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT id FROM documents WHERE content_hash = ?", (content_hash,)).fetchone()
                if existing:
                    document_id = int(existing["id"])
                    deduplicated = True
                    connection.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO documents (
                            url, canonical_url, title, description, author, site_name, hostname,
                            language, pagetype, published_at, content, content_hash, tags_json,
                            metadata_json, raw_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_url,
                            final_url,
                            self._as_text(page.get("title")),
                            self._as_text(page.get("description")),
                            self._as_text(page.get("author")),
                            self._as_text(page.get("sitename")),
                            hostname,
                            self._as_text(page.get("language")),
                            self._as_text(page.get("pagetype")),
                            self._as_text(page.get("date")),
                            content,
                            content_hash,
                            self._json(tags),
                            self._json(page),
                            self._json(raw_response),
                            now,
                            now,
                        ),
                    )
                    document_id = int(cursor.lastrowid)
                    deduplicated = False

                connection.execute(
                    """
                    INSERT INTO document_search (document_id, title_tokens, description_tokens, tags_tokens, content_tokens)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        title_tokens = excluded.title_tokens,
                        description_tokens = excluded.description_tokens,
                        tags_tokens = excluded.tags_tokens,
                        content_tokens = excluded.content_tokens
                    """,
                    (
                        document_id,
                        self.tokenize(self._as_text(page.get("title")) or ""),
                        self.tokenize(self._as_text(page.get("description")) or ""),
                        self.tokenize(" ".join(tags)),
                        self.tokenize(content),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO fetches (document_id, requested_url, final_url, strategy, status_code, content_type, attempts_json, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (document_id, requested_url, final_url, strategy, status_code, content_type, self._json(attempts), now),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"database write failed: {str(exc)[:180]}") from exc
        return StorageResult(document_id=document_id, deduplicated=deduplicated)

    def search(
        self,
        *,
        query: str,
        hostname: str | None,
        published_after: str | None,
        published_before: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        self._require_available()
        match_query = self._fts_prefix_query(query)
        if not match_query:
            return []
        filters: list[str] = ["documents_fts MATCH ?"]
        params: list[Any] = [match_query]
        if hostname:
            filters.append("d.hostname = ?")
            params.append(hostname)
        if published_after:
            filters.append("d.published_at >= ?")
            params.append(published_after)
        if published_before:
            filters.append("d.published_at <= ?")
            params.append(published_before)
        params.append(limit)
        sql = f"""
            SELECT d.id, d.title, d.url, d.canonical_url, d.hostname, d.published_at,
                   bm25(documents_fts, 5.0, 2.0, 3.0, 1.0) AS score,
                   snippet(documents_fts, 3, '<mark>', '</mark>', '…', 40) AS snippet
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.rowid
            WHERE {' AND '.join(filters)}
            ORDER BY score
            LIMIT ?
        """
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"database search failed: {str(exc)[:180]}") from exc
        return [dict(row) for row in rows]

    def tokenize(self, text: str) -> str:
        return " ".join(token.strip() for token in jieba.cut(text) if token.strip())

    @staticmethod
    def normalize_tags(value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value] if value else []
        normalized: list[str] = []
        for item in values:
            if not isinstance(item, str):
                continue
            for tag in item.replace("，", ",").split(","):
                tag = tag.strip()
                if tag and tag not in normalized:
                    normalized.append(tag)
        return normalized

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _require_available(self) -> None:
        if not self.available:
            raise StorageError(self.initialization_error or "storage is not initialized")

    def _fts_prefix_query(self, query: str) -> str:
        tokens = [token.replace('"', "") for token in jieba.cut(query) if token.strip()]
        return " AND ".join(f'"{token}"*' for token in tokens if token)

    @staticmethod
    def _as_text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
