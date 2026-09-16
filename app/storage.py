from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jieba


class StorageError(RuntimeError):
    pass


def normalize_route_hostname(hostname: str) -> str:
    return hostname.strip().lower().removeprefix("www.")


@dataclass(frozen=True)
class StorageResult:
    document_id: int
    deduplicated: bool


@dataclass(frozen=True)
class FetchRoute:
    strategy: str
    extraction_method: str


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
                columns = {row[1] for row in connection.execute("PRAGMA table_info(api_keys)")}
                if "key_suffix" not in columns:
                    connection.execute("ALTER TABLE api_keys ADD COLUMN key_suffix TEXT")
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

    def list_documents(
        self,
        *,
        page: int,
        page_size: int,
        title: str | None = None,
        sitename: str | None = None,
        tags: str | None = None,
        content: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self._require_available()
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (("d.title", title), ("d.site_name", sitename), ("d.tags_json", tags)):
            if value:
                filters.append(f"{column} LIKE ?")
                params.append(f"%{value}%")
        if content:
            filters.append("(d.title LIKE ? OR d.content LIKE ?)")
            params.extend([f"%{content}%", f"%{content}%"])
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        offset = (page - 1) * page_size
        try:
            with self._connect() as connection:
                total = connection.execute(f"SELECT COUNT(*) FROM documents d {where}", params).fetchone()[0]
                rows = connection.execute(
                    f"""
                    SELECT d.id, d.title, d.url, d.site_name, d.hostname, d.published_at,
                           d.updated_at, (SELECT MAX(fetched_at) FROM fetches f WHERE f.document_id = d.id) AS fetched_at
                    FROM documents d {where}
                    ORDER BY COALESCE(d.published_at, d.updated_at) DESC
                    LIMIT ? OFFSET ?
                    """,
                    [*params, page_size, offset],
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"document listing failed: {str(exc)[:180]}") from exc
        return [dict(row) for row in rows], int(total)

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        self._require_available()
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
                if not row:
                    return None
                result = dict(row)
                result["tags"] = json.loads(result.pop("tags_json"))
                result["page"] = json.loads(result.pop("metadata_json"))
                result.pop("raw_json", None)
                result["fetches"] = [dict(fetch) for fetch in connection.execute(
                    "SELECT requested_url, final_url, strategy, status_code, content_type, attempts_json, fetched_at FROM fetches WHERE document_id = ? ORDER BY fetched_at DESC",
                    (document_id,),
                ).fetchall()]
                return result
        except (sqlite3.Error, ValueError) as exc:
            raise StorageError(f"document lookup failed: {str(exc)[:180]}") from exc

    def delete_document(self, document_id: int) -> bool:
        self._require_available()
        try:
            with self._connect() as connection:
                cursor = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise StorageError(f"document deletion failed: {str(exc)[:180]}") from exc

    def create_api_key(self, *, name: str, scopes: list[str], expires_at: str | None, pepper: str) -> tuple[str, dict[str, Any]]:
        self._require_available()
        token = "oma_" + secrets.token_urlsafe(32)
        prefix = token[:16]
        digest = hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO api_keys (name, key_prefix, key_suffix, secret_hmac, scopes_json, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, prefix, token[-4:], digest, self._json(scopes), now, expires_at),
                )
                key_id = int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise StorageError(f"api key creation failed: {str(exc)[:180]}") from exc
        return token, {"id": key_id, "name": name, "key_prefix": prefix, "key_suffix": token[-4:], "scopes": scopes, "created_at": now, "expires_at": expires_at}

    def authenticate_key(self, token: str, pepper: str) -> sqlite3.Row | None:
        self._require_available()
        prefix = token[:16]
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM api_keys WHERE key_prefix = ? AND revoked_at IS NULL",
                    (prefix,),
                ).fetchone()
                if not row:
                    return None
                if row["expires_at"] and row["expires_at"] <= datetime.now(UTC).isoformat():
                    return None
                expected = hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, row["secret_hmac"]):
                    return None
                connection.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (datetime.now(UTC).isoformat(), row["id"]))
                return row
        except sqlite3.Error as exc:
            raise StorageError(f"api key authentication failed: {str(exc)[:180]}") from exc

    def list_api_keys(self) -> list[dict[str, Any]]:
        self._require_available()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, name, key_prefix, key_suffix, scopes_json, created_at, expires_at, revoked_at, last_used_at FROM api_keys ORDER BY id DESC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"api key listing failed: {str(exc)[:180]}") from exc
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["scopes"] = json.loads(item.pop("scopes_json"))
            result.append(item)
        return result

    def revoke_api_key(self, key_id: int) -> bool:
        self._require_available()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (datetime.now(UTC).isoformat(), key_id),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise StorageError(f"api key revoke failed: {str(exc)[:180]}") from exc

    def get_route(self, hostname: str, target_kind: str) -> FetchRoute | None:
        self._require_available()
        hostname = normalize_route_hostname(hostname)
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT strategy, extraction_method FROM fetch_routes
                    WHERE hostname = ? AND target_kind = ? AND expires_at > ?
                    """,
                    (hostname, target_kind, now),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"route lookup failed: {str(exc)[:180]}") from exc
        return FetchRoute(strategy=row["strategy"], extraction_method=row["extraction_method"]) if row else None

    def record_route_success(
        self,
        *,
        hostname: str,
        target_kind: str,
        strategy: str,
        extraction_method: str,
        ttl_hours: int,
    ) -> None:
        self._require_available()
        hostname = normalize_route_hostname(hostname)
        now = datetime.now(UTC)
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        timestamp = now.isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO fetch_routes (
                        hostname, target_kind, strategy, extraction_method, success_count,
                        failure_count, last_success_at, expires_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)
                    ON CONFLICT(hostname, target_kind) DO UPDATE SET
                        strategy = excluded.strategy,
                        extraction_method = excluded.extraction_method,
                        success_count = CASE
                            WHEN fetch_routes.strategy = excluded.strategy THEN fetch_routes.success_count + 1
                            ELSE 1
                        END,
                        failure_count = 0,
                        last_success_at = excluded.last_success_at,
                        expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at
                    """,
                    (hostname, target_kind, strategy, extraction_method, timestamp, expires_at, timestamp),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"route update failed: {str(exc)[:180]}") from exc

    def record_route_failure(self, *, hostname: str, target_kind: str, strategy: str) -> None:
        """Expire only the route that failed; the full strategy chain remains available."""
        self._require_available()
        hostname = normalize_route_hostname(hostname)
        timestamp = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE fetch_routes
                    SET failure_count = failure_count + 1, last_failure_at = ?, expires_at = ?, updated_at = ?
                    WHERE hostname = ? AND target_kind = ? AND strategy = ?
                    """,
                    (timestamp, timestamp, timestamp, hostname, target_kind, strategy),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"route invalidation failed: {str(exc)[:180]}") from exc

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
