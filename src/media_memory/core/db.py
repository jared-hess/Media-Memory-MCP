from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from media_memory.core.fts import create_fts_schema, rebuild_chunks_fts, upsert_chunk_fts
from media_memory.core.ids import chunk_id as make_chunk_id
from media_memory.core.ids import document_id as make_document_id
from media_memory.core.ids import ingest_job_id as make_ingest_job_id
from media_memory.core.ids import media_id as make_media_id
from media_memory.core.models import DEFAULT_CORPUS_ID, SubtitleChunk


SCHEMA_VERSION = 5


class MediaMemoryDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self._drop_legacy_tables_if_needed()
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS media_items (
                id TEXT PRIMARY KEY,
                legacy_id INTEGER UNIQUE,
                corpus_id TEXT NOT NULL DEFAULT 'local',
                path TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'unknown',
                season INTEGER,
                episode INTEGER,
                show_title TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                episode_title TEXT,
                year INTEGER,
                air_date TEXT,
                runtime_seconds INTEGER,
                provider_ids_json TEXT NOT NULL DEFAULT '{}',
                provider_refs_json TEXT NOT NULL DEFAULT '[]',
                checksum TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(corpus_id, path)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                corpus_id TEXT NOT NULL DEFAULT 'local',
                media_item_id TEXT,
                media_path TEXT,
                source_path TEXT,
                source_uri TEXT,
                source_kind TEXT NOT NULL DEFAULT 'subtitle',
                language TEXT,
                title TEXT,
                provider_ids_json TEXT NOT NULL DEFAULT '{}',
                provider_refs_json TEXT NOT NULL DEFAULT '[]',
                checksum TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(corpus_id, media_item_id, source_path, source_kind),
                FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                legacy_id INTEGER UNIQUE,
                corpus_id TEXT NOT NULL DEFAULT 'local',
                document_id TEXT NOT NULL,
                media_item_id TEXT NOT NULL,
                chunk_index INTEGER,
                text TEXT NOT NULL,
                normalized_text TEXT,
                start_ms INTEGER,
                end_ms INTEGER,
                start_seconds REAL,
                end_seconds REAL,
                season INTEGER,
                episode INTEGER,
                media_path TEXT,
                subtitle_path TEXT,
                source_kind TEXT NOT NULL DEFAULT 'subtitle',
                language TEXT,
                text_hash TEXT,
                embedding_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(corpus_id, document_id, chunk_index),
                UNIQUE(corpus_id, document_id, start_ms, end_ms, text_hash),
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ingest_jobs (
                id TEXT PRIMARY KEY,
                corpus_id TEXT NOT NULL DEFAULT 'local',
                media_item_id TEXT,
                document_id TEXT,
                media_path TEXT,
                source_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                state_history_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE SET NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key TEXT PRIMARY KEY,
                corpus_id TEXT NOT NULL DEFAULT 'local',
                query TEXT NOT NULL,
                filters_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        create_fts_schema(self.conn)
        self._ensure_ingest_jobs_columns()
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

    def upsert_media_item(
        self,
        *,
        path: str,
        title: str,
        kind: str,
        season: int | None = None,
        episode: int | None = None,
        show_title: str | None = None,
        season_number: int | None = None,
        episode_number: int | None = None,
        episode_title: str | None = None,
        year: int | None = None,
        runtime_seconds: int | None = None,
        provider_ids: dict[str, str] | None = None,
        provider_refs: list[dict[str, object]] | None = None,
        corpus_id: str = DEFAULT_CORPUS_ID,
    ) -> int:
        now = _utc_now_iso()
        item_id = make_media_id(path=path, title=title, kind=kind, corpus_id=corpus_id)
        legacy_row = self.conn.execute(
            "SELECT legacy_id FROM media_items WHERE corpus_id = ? AND path = ?",
            (corpus_id, path),
        ).fetchone()
        legacy_id = (
            int(legacy_row["legacy_id"]) if legacy_row else self._next_legacy_id("media_items")
        )
        self.conn.execute(
            """
            INSERT INTO media_items(
                id, legacy_id, corpus_id, path, title, kind, season, episode,
                show_title, season_number, episode_number, episode_title, year, runtime_seconds,
                provider_ids_json, provider_refs_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(corpus_id, path) DO UPDATE SET
                title = excluded.title,
                kind = excluded.kind,
                season = excluded.season,
                episode = excluded.episode,
                show_title = excluded.show_title,
                season_number = excluded.season_number,
                episode_number = excluded.episode_number,
                episode_title = excluded.episode_title,
                year = excluded.year,
                runtime_seconds = excluded.runtime_seconds,
                provider_ids_json = excluded.provider_ids_json,
                provider_refs_json = excluded.provider_refs_json,
                updated_at = excluded.updated_at
            """,
            (
                item_id,
                legacy_id,
                corpus_id,
                path,
                title,
                kind,
                season,
                episode,
                show_title,
                season_number if season_number is not None else season,
                episode_number if episode_number is not None else episode,
                episode_title,
                year,
                runtime_seconds,
                json.dumps(provider_ids or {}),
                json.dumps(provider_refs or []),
                now,
                now,
            ),
        )
        row = self.conn.execute(
            "SELECT legacy_id FROM media_items WHERE corpus_id = ? AND path = ?",
            (corpus_id, path),
        ).fetchone()
        self.conn.commit()
        return int(row["legacy_id"])

    def insert_chunk(
        self,
        media_item_id: int | str,
        chunk: SubtitleChunk,
        text_hash: str,
        *,
        document_checksum: str | None = None,
        provider_ids: dict[str, str] | None = None,
        provider_refs: list[dict[str, object]] | None = None,
    ) -> int | None:
        media = self._get_media_by_public_id(media_item_id)
        if media is None:
            raise ValueError(f"Unknown media item: {media_item_id}")

        corpus_id = str(media["corpus_id"])
        subtitle_path = chunk.subtitle_path
        doc_id = make_document_id(
            media_id=str(media["id"]),
            source_path=subtitle_path,
            corpus_id=corpus_id,
            source_kind=chunk.source_kind,
        )
        self._upsert_local_document(
            document_id=doc_id,
            corpus_id=corpus_id,
            media_id=str(media["id"]),
            media_path=chunk.media_path,
            source_path=subtitle_path,
            source_kind=chunk.source_kind,
            language=chunk.language,
            checksum=document_checksum,
            provider_ids=provider_ids,
            provider_refs=provider_refs,
        )

        row = self.conn.execute(
            """
            SELECT legacy_id FROM chunks
            WHERE corpus_id = ? AND document_id = ? AND start_ms IS ? AND end_ms IS ? AND text_hash = ?
            """,
            (corpus_id, doc_id, chunk.start_ms, chunk.end_ms, text_hash),
        ).fetchone()
        if row is not None:
            self.conn.commit()
            return None

        chunk_index = self._next_chunk_index(doc_id)
        stable_chunk_id = make_chunk_id(
            document_id=doc_id,
            text=chunk.text,
            corpus_id=corpus_id,
            start_ms=chunk.start_ms,
            end_ms=chunk.end_ms,
            chunk_index=chunk_index,
        )
        legacy_id = self._next_legacy_id("chunks")
        now = _utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO chunks(
                id, legacy_id, corpus_id, document_id, media_item_id, chunk_index,
                text, normalized_text, start_ms, end_ms, start_seconds, end_seconds,
                season, episode, media_path, subtitle_path, source_kind, language, text_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stable_chunk_id,
                legacy_id,
                corpus_id,
                doc_id,
                str(media["id"]),
                chunk_index,
                chunk.text,
                chunk.normalized_text or _normalize_text(chunk.text),
                chunk.start_ms,
                chunk.end_ms,
                _ms_to_seconds(chunk.start_ms),
                _ms_to_seconds(chunk.end_ms),
                chunk.season,
                chunk.episode,
                chunk.media_path,
                subtitle_path,
                chunk.source_kind,
                chunk.language,
                text_hash,
                now,
                now,
            ),
        )
        upsert_chunk_fts(self.conn, rowid=legacy_id, chunk_id=stable_chunk_id, text=chunk.text)
        self.conn.commit()
        return legacy_id

    def upsert_ingest_job(
        self,
        *,
        status: str,
        corpus_id: str = DEFAULT_CORPUS_ID,
        media_item_id: int | str | None = None,
        document_id: str | None = None,
        media_path: str | None = None,
        source_path: str | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> str:
        media = self._get_media_by_public_id(media_item_id) if media_item_id is not None else None
        canonical_media_id = str(media["id"]) if media is not None else None
        job_id = make_ingest_job_id(
            corpus_id=corpus_id,
            media_id=canonical_media_id,
            document_id=document_id,
            source_path=source_path or media_path,
        )
        now = _utc_now_iso()
        row = self.conn.execute(
            "SELECT state_history_json, started_at FROM ingest_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        history = _load_state_history(row["state_history_json"] if row is not None else None)
        history.append({"status": status, "at": now, "error": error})
        started_at = row["started_at"] if row is not None and row["started_at"] else now
        completed_at = now if completed else None
        self.conn.execute(
            """
            INSERT INTO ingest_jobs(
                id, corpus_id, media_item_id, document_id, media_path, source_path,
                status, error, state_history_json, created_at, updated_at, started_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                media_item_id = excluded.media_item_id,
                document_id = excluded.document_id,
                media_path = excluded.media_path,
                source_path = excluded.source_path,
                status = excluded.status,
                error = excluded.error,
                state_history_json = excluded.state_history_json,
                updated_at = excluded.updated_at,
                started_at = COALESCE(ingest_jobs.started_at, excluded.started_at),
                completed_at = excluded.completed_at
            """,
            (
                job_id,
                corpus_id,
                canonical_media_id,
                document_id,
                media_path,
                source_path,
                status,
                error,
                json.dumps(history),
                now,
                now,
                started_at,
                completed_at,
            ),
        )
        self.conn.commit()
        return job_id

    def count_media_items(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0])

    def count_documents(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def count_chunks(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def count_corpora(self) -> int:
        return int(
            self.conn.execute(
                """
                SELECT COUNT(DISTINCT corpus_id)
                FROM (
                    SELECT corpus_id FROM media_items
                    UNION ALL
                    SELECT corpus_id FROM documents
                    UNION ALL
                    SELECT corpus_id FROM chunks
                )
                """
            ).fetchone()[0]
        )

    def count_ingest_jobs(self, *, status: str | None = None) -> int:
        if status is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM ingest_jobs").fetchone()[0])
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM ingest_jobs WHERE status = ?", (status,)
            ).fetchone()[0]
        )

    def list_ingest_jobs(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM ingest_jobs ORDER BY created_at, id"))

    def lexical_search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.legacy_id as chunk_id,
                       c.id as stable_chunk_id,
                       m.path as media_path,
                       m.title as title,
                       c.text as text,
                       c.start_ms as start_ms,
                       c.end_ms as end_ms,
                       bm25(chunks_fts) * -1.0 as lexical_score
                FROM chunks_fts
                JOIN chunks c ON c.legacy_id = chunks_fts.rowid
                JOIN media_items m ON m.id = c.media_item_id
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts)
                LIMIT ?
                """,
                (query, limit),
            )
        )

    def get_chunk_by_id(self, chunk_id: int | str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT c.legacy_id as chunk_id,
                   c.id as stable_chunk_id,
                   m.path as media_path,
                   m.title as title,
                   c.text as text,
                   c.start_ms as start_ms,
                   c.end_ms as end_ms
            FROM chunks c
            JOIN media_items m ON m.id = c.media_item_id
            WHERE c.legacy_id = ? OR c.id = ?
            """,
            (_as_int_or_none(chunk_id), str(chunk_id)),
        ).fetchone()

    def get_chunk_vector_metadata(self, chunk_id: int | str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT legacy_id as chunk_id,
                   media_item_id as media_item_id,
                   document_id as document_id,
                   source_kind as source_type,
                   'local' as source_provider,
                   start_seconds as start_time_seconds,
                   end_seconds as end_time_seconds,
                   corpus_id as corpus_id
            FROM chunks
            WHERE legacy_id = ? OR id = ?
            """,
            (_as_int_or_none(chunk_id), str(chunk_id)),
        ).fetchone()

    def list_chunks_for_media(self, media_path: str, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.legacy_id as chunk_id, c.id as stable_chunk_id,
                       c.text as text, c.start_ms as start_ms, c.end_ms as end_ms
                FROM chunks c
                JOIN media_items m ON m.id = c.media_item_id
                WHERE m.path = ?
                ORDER BY CASE WHEN c.start_ms IS NULL THEN 1 ELSE 0 END, c.start_ms, c.legacy_id
                LIMIT ?
                """,
                (media_path, limit),
            )
        )

    def list_all_chunks(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.legacy_id as chunk_id,
                       c.id as stable_chunk_id,
                       c.text as text,
                       c.media_item_id as media_item_id,
                       c.document_id as document_id,
                       c.source_kind as source_type,
                       'local' as source_provider,
                       c.start_seconds as start_time_seconds,
                       c.end_seconds as end_time_seconds,
                       c.corpus_id as corpus_id
                FROM chunks c
                ORDER BY c.legacy_id
                """
            )
        )

    def rebuild_fts_index(self) -> None:
        rebuild_chunks_fts(self.conn)
        self.conn.commit()

    def _drop_legacy_tables_if_needed(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'media_items'"
        ).fetchone()
        if row is None or "id TEXT PRIMARY KEY" in str(row["sql"]):
            return
        self.conn.executescript(
            """
            DROP TABLE IF EXISTS subtitle_chunks_fts;
            DROP TABLE IF EXISTS subtitle_chunks;
            DROP TABLE IF EXISTS media_items;
            """
        )

    def _ensure_ingest_jobs_columns(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(ingest_jobs)")}
        if "state_history_json" not in columns:
            self.conn.execute(
                "ALTER TABLE ingest_jobs ADD COLUMN state_history_json TEXT NOT NULL DEFAULT '[]'"
            )

        chunk_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(chunks)")}
        if "season" not in chunk_columns:
            self.conn.execute("ALTER TABLE chunks ADD COLUMN season INTEGER")
        if "episode" not in chunk_columns:
            self.conn.execute("ALTER TABLE chunks ADD COLUMN episode INTEGER")

    def _get_media_by_public_id(self, media_item_id: int | str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM media_items
            WHERE legacy_id = ? OR id = ?
            """,
            (_as_int_or_none(media_item_id), str(media_item_id)),
        ).fetchone()

    def _upsert_local_document(
        self,
        *,
        document_id: str,
        corpus_id: str,
        media_id: str,
        media_path: str,
        source_path: str,
        source_kind: str,
        language: str | None,
        checksum: str | None = None,
        provider_ids: dict[str, str] | None = None,
        provider_refs: list[dict[str, object]] | None = None,
    ) -> None:
        now = _utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO documents(
                id, corpus_id, media_item_id, media_path, source_path, source_kind,
                language, checksum, provider_ids_json, provider_refs_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(corpus_id, media_item_id, source_path, source_kind) DO UPDATE SET
                media_path = excluded.media_path,
                language = excluded.language,
                checksum = COALESCE(excluded.checksum, documents.checksum),
                provider_ids_json = excluded.provider_ids_json,
                provider_refs_json = excluded.provider_refs_json,
                updated_at = excluded.updated_at
            """,
            (
                document_id,
                corpus_id,
                media_id,
                media_path,
                source_path,
                source_kind,
                language,
                checksum,
                json.dumps(provider_ids or {}),
                json.dumps(provider_refs or []),
                now,
                now,
            ),
        )

    def _next_chunk_index(self, document_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(chunk_index), -1) + 1 AS next_index FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["next_index"])

    def _next_legacy_id(self, table: str) -> int:
        row = self.conn.execute(
            f"SELECT COALESCE(MAX(legacy_id), 0) + 1 AS next_id FROM {table}"
        ).fetchone()
        return int(row["next_id"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _load_state_history(value: str | None) -> list[dict[str, str | None]]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    history: list[dict[str, str | None]] = []
    for item in loaded:
        if isinstance(item, dict):
            history.append(
                {str(key): None if val is None else str(val) for key, val in item.items()}
            )
    return history


def _ms_to_seconds(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 1000.0


def _as_int_or_none(value: int | str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
