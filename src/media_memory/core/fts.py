from __future__ import annotations

import sqlite3


def create_fts_schema(conn: sqlite3.Connection) -> None:
    """Create the derived FTS5 index for canonical chunks."""

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED,
            text,
            tokenize='porter unicode61'
        )
        """
    )


def upsert_chunk_fts(conn: sqlite3.Connection, *, rowid: int, chunk_id: str, text: str) -> None:
    """Replace one derived FTS row for a canonical chunk."""

    delete_chunk_fts(conn, rowid=rowid)
    conn.execute(
        "INSERT INTO chunks_fts(rowid, chunk_id, text) VALUES (?, ?, ?)",
        (rowid, chunk_id, text),
    )


def delete_chunk_fts(conn: sqlite3.Connection, *, rowid: int) -> None:
    """Delete one derived FTS row if it exists."""

    conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (rowid,))


def rebuild_chunks_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the derived FTS index from canonical chunk text."""

    conn.execute("DELETE FROM chunks_fts")
    conn.execute(
        """
        INSERT INTO chunks_fts(rowid, chunk_id, text)
        SELECT legacy_id, id, text
        FROM chunks
        ORDER BY legacy_id
        """
    )
