from __future__ import annotations

import sqlite3
from pathlib import Path

from media_memory.core.models import SubtitleChunk


class MediaMemoryDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS media_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                kind TEXT,
                season INTEGER,
                episode INTEGER
            );

            CREATE TABLE IF NOT EXISTS subtitle_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_item_id INTEGER NOT NULL,
                subtitle_path TEXT NOT NULL,
                text TEXT NOT NULL,
                start_ms INTEGER,
                end_ms INTEGER,
                text_hash TEXT NOT NULL,
                UNIQUE(media_item_id, subtitle_path, start_ms, end_ms, text_hash),
                FOREIGN KEY (media_item_id) REFERENCES media_items(id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS subtitle_chunks_fts USING fts5(
                text,
                content='subtitle_chunks',
                content_rowid='id'
            );
            """
        )
        self.conn.commit()

    def upsert_media_item(
        self,
        *,
        path: str,
        title: str,
        kind: str,
        season: int | None = None,
        episode: int | None = None,
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO media_items(path, title, kind, season, episode)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title = excluded.title,
                kind = excluded.kind,
                season = excluded.season,
                episode = excluded.episode
            """,
            (path, title, kind, season, episode),
        )
        row = self.conn.execute("SELECT id FROM media_items WHERE path = ?", (path,)).fetchone()
        self.conn.commit()
        return int(row["id"])

    def insert_chunk(self, media_item_id: int, chunk: SubtitleChunk, text_hash: str) -> int | None:
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO subtitle_chunks(media_item_id, subtitle_path, text, start_ms, end_ms, text_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (media_item_id, chunk.subtitle_path, chunk.text, chunk.start_ms, chunk.end_ms, text_hash),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        chunk_id = int(cur.lastrowid)
        self.conn.execute(
            "INSERT INTO subtitle_chunks_fts(rowid, text) VALUES (?, ?)",
            (chunk_id, chunk.text),
        )
        self.conn.commit()
        return chunk_id

    def lexical_search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.id as chunk_id,
                       m.path as media_path,
                       m.title as title,
                       c.text as text,
                       c.start_ms as start_ms,
                       c.end_ms as end_ms,
                       bm25(subtitle_chunks_fts) * -1.0 as lexical_score
                FROM subtitle_chunks_fts
                JOIN subtitle_chunks c ON c.id = subtitle_chunks_fts.rowid
                JOIN media_items m ON m.id = c.media_item_id
                WHERE subtitle_chunks_fts MATCH ?
                ORDER BY bm25(subtitle_chunks_fts)
                LIMIT ?
                """,
                (query, limit),
            )
        )

    def get_chunk_by_id(self, chunk_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT c.id as chunk_id,
                   m.path as media_path,
                   m.title as title,
                   c.text as text,
                   c.start_ms as start_ms,
                   c.end_ms as end_ms
            FROM subtitle_chunks c
            JOIN media_items m ON m.id = c.media_item_id
            WHERE c.id = ?
            """,
            (chunk_id,),
        ).fetchone()

    def list_chunks_for_media(self, media_path: str, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.id as chunk_id, c.text as text, c.start_ms as start_ms, c.end_ms as end_ms
                FROM subtitle_chunks c
                JOIN media_items m ON m.id = c.media_item_id
                WHERE m.path = ?
                ORDER BY CASE WHEN c.start_ms IS NULL THEN 1 ELSE 0 END, c.start_ms, c.id
                LIMIT ?
                """,
                (media_path, limit),
            )
        )

    def list_all_chunks(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT id as chunk_id, text
                FROM subtitle_chunks
                ORDER BY id
                """
            )
        )
