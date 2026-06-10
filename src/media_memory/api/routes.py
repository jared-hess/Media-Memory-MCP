from __future__ import annotations

from pathlib import Path
from typing import Any

from media_memory.cli.main import _provider_enablement
from media_memory.core.db import SCHEMA_VERSION
from media_memory.mcp_server.tools import (
    McpServices,
    get_media_payload,
    get_scene_context_payload,
    ingest_library_payload,
    search_media_payload,
)


def health_payload() -> dict[str, object]:
    """Return a minimal liveness response without opening local data stores."""

    return {"status": "ok", "service": "media-memory", "api": "rest"}


def status_payload(services: McpServices) -> dict[str, object]:
    """Return config-safe status data matching the CLI status shape."""

    config = services.config
    job_rows = services.db.list_ingest_jobs()
    jobs_by_status: dict[str, int] = {}
    pending_jobs = 0
    failed_jobs = 0
    for row in job_rows:
        status_name = str(row["status"])
        jobs_by_status[status_name] = jobs_by_status.get(status_name, 0) + 1
        if status_name == "failed":
            failed_jobs += 1
        elif row["completed_at"] is None:
            pending_jobs += 1

    chunk_count = services.db.count_chunks()
    db_path = config.index.sqlite_path
    return {
        "db": {
            "path": str(db_path),
            "exists": Path(db_path).exists(),
            "schema_version": SCHEMA_VERSION,
        },
        "corpus": {
            "configured": config.app.corpus_id,
            "count": services.db.count_corpora(),
        },
        "jobs": {
            "total": len(job_rows),
            "pending": pending_jobs,
            "failed": failed_jobs,
            "by_status": jobs_by_status,
        },
        "index": {
            "state": "ready",
            "chunks": chunk_count,
            "fts": "ready",
            "vector_db": config.index.vector_db,
            "vector_path": str(config.index.vector_path),
        },
        "counts": {
            "media_items": services.db.count_media_items(),
            "documents": services.db.count_documents(),
            "chunks": chunk_count,
        },
        "providers": _provider_enablement(config),
    }


def rest_search_payload(services: McpServices, request: dict[str, Any]) -> dict[str, object]:
    """Return the same SearchResult-shaped payload as MCP search_media."""

    query = _required_string(request, "query")
    limit = _optional_int(request.get("limit"), "limit")
    kind = _optional_string(request.get("kind"), "kind")
    show = _optional_string(request.get("show"), "show")
    return search_media_payload(services, query=query, limit=limit, kind=kind, show=show)


def rest_ingest_payload(services: McpServices) -> dict[str, object]:
    """Run the same gated ingest path exposed by MCP when explicitly enabled."""

    return ingest_library_payload(services)


def rest_media_payload(services: McpServices, media_id: str) -> dict[str, object]:
    """Return one indexed media item using the core search service lookup."""

    return get_media_payload(services, media_id=media_id)


def rest_scene_payload(services: McpServices, media_id: str, start: str | None) -> dict[str, object]:
    """Return scene context for the chunk nearest a media timestamp in seconds."""

    if start is None:
        raise ValueError("Missing required query parameter: start")
    start_seconds = _optional_float(start, "start")
    if start_seconds is None:
        raise ValueError("Missing required query parameter: start")
    media = services.search.get_media(media_id=media_id)
    if media is None:
        return {"result": None}

    row = services.db.conn.execute(
        """
        SELECT c.id, c.legacy_id
        FROM chunks c
        WHERE c.media_item_id = ?
        ORDER BY
            CASE
                WHEN c.start_seconds <= ? AND (c.end_seconds IS NULL OR c.end_seconds >= ?) THEN 0
                WHEN c.start_seconds >= ? THEN 1
                ELSE 2
            END,
            ABS(COALESCE(c.start_seconds, 0) - ?),
            c.chunk_index
        LIMIT 1
        """,
        (str(media["id"]), start_seconds, start_seconds, start_seconds, start_seconds),
    ).fetchone()
    if row is None:
        return {"result": None}
    return get_scene_context_payload(services, chunk_id=str(row["id"]))


def _required_string(request: dict[str, Any], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string field: {name}")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Field must be a string: {name}")
    return value


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field must be an integer: {name}") from exc


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field must be a number: {name}") from exc
