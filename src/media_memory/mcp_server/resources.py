from __future__ import annotations

import json
import re
from typing import Any

from media_memory.mcp_server.tools import McpServices


def register_resources(app: Any, services: McpServices) -> None:
    """Register read-only Media Memory resources on a FastMCP app."""

    @app.resource("media://show/{show_slug}")
    def show_resource(show_slug: str) -> dict[str, object]:
        """Return indexed episodes for a show slug."""

        return get_show_resource(services, show_slug)

    @app.resource("media://episode/{show_slug}/s{season}e{episode}")
    def episode_resource(show_slug: str, season: str, episode: str) -> dict[str, object]:
        """Return one indexed episode by show slug and season/episode."""

        return get_episode_resource(services, show_slug, season, episode)

    @app.resource("media://movie/{movie_slug}-{year}")
    def movie_resource(movie_slug: str, year: str) -> dict[str, object]:
        """Return one indexed movie by slug and year."""

        return get_movie_resource(services, movie_slug, year)

    @app.resource("media://ingest/status")
    def ingest_status_resource() -> dict[str, object]:
        """Return database and ingest-job status without mutating local data."""

        return get_ingest_status_resource(services)


def get_show_resource(services: McpServices, show_slug: str) -> dict[str, object]:
    rows = services.db.conn.execute(
        """
        SELECT *
        FROM media_items
        WHERE corpus_id = ? AND kind = 'episode'
        ORDER BY season_number, season, episode_number, episode, title
        """,
        (services.config.app.corpus_id,),
    ).fetchall()
    matches = [
        row_to_media(row)
        for row in rows
        if _matches_slug(row["show_title"] or row["title"], show_slug)
    ]
    return {"show_slug": show_slug, "results": matches}


def get_episode_resource(
    services: McpServices,
    show_slug: str,
    season: str | int,
    episode: str | int,
) -> dict[str, object]:
    season_number = int(season)
    episode_number = int(episode)
    rows = services.db.conn.execute(
        """
        SELECT *
        FROM media_items
        WHERE corpus_id = ?
          AND kind = 'episode'
          AND COALESCE(season_number, season) = ?
          AND COALESCE(episode_number, episode) = ?
        ORDER BY title
        """,
        (services.config.app.corpus_id, season_number, episode_number),
    ).fetchall()
    matches = [
        row_to_media(row)
        for row in rows
        if _matches_slug(row["show_title"] or row["title"], show_slug)
    ]
    return {
        "show_slug": show_slug,
        "season": season_number,
        "episode": episode_number,
        "result": matches[0] if matches else None,
    }


def get_movie_resource(
    services: McpServices, movie_slug: str, year: str | int
) -> dict[str, object]:
    movie_year = int(year)
    rows = services.db.conn.execute(
        """
        SELECT *
        FROM media_items
        WHERE corpus_id = ? AND kind = 'movie' AND year = ?
        ORDER BY title
        """,
        (services.config.app.corpus_id, movie_year),
    ).fetchall()
    matches = [row_to_media(row) for row in rows if _matches_slug(row["title"], movie_slug)]
    return {"movie_slug": movie_slug, "year": movie_year, "result": matches[0] if matches else None}


def get_ingest_status_resource(services: McpServices) -> dict[str, object]:
    job_rows = services.db.list_ingest_jobs()
    jobs_by_status: dict[str, int] = {}
    for row in job_rows:
        status = str(row["status"])
        jobs_by_status[status] = jobs_by_status.get(status, 0) + 1
    return {
        "db": {
            "path": str(services.config.index.sqlite_path),
            "exists": services.config.index.sqlite_path.exists(),
        },
        "jobs": {"total": len(job_rows), "by_status": jobs_by_status},
        "index": {"chunks": services.db.count_chunks(), "fts": "ready"},
        "counts": {
            "media_items": services.db.count_media_items(),
            "documents": services.db.count_documents(),
            "chunks": services.db.count_chunks(),
        },
        "allow_ingest_tools": services.config.mcp.allow_ingest_tools,
    }


def row_to_media(row: Any) -> dict[str, object]:
    return {
        "id": row["id"],
        "legacy_id": row["legacy_id"],
        "corpus_id": row["corpus_id"],
        "media_path": row["path"],
        "title": row["title"],
        "kind": row["kind"],
        "season": row["season"],
        "episode": row["episode"],
        "show_title": row["show_title"],
        "season_number": row["season_number"],
        "episode_number": row["episode_number"],
        "episode_title": row["episode_title"],
        "year": row["year"],
        "air_date": row["air_date"],
        "runtime_seconds": row["runtime_seconds"],
        "provider_ids": _json_dict(row["provider_ids_json"]),
        "provider_refs": _json_list(row["provider_refs_json"]),
        "checksum": row["checksum"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _matches_slug(value: object, slug: str) -> bool:
    return _slugify(str(value or "")) == slug


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def _json_dict(value: object) -> dict[str, object]:
    if not value:
        return {}
    loaded = json.loads(str(value))
    return loaded if isinstance(loaded, dict) else {}


def _json_list(value: object) -> list[object]:
    if not value:
        return []
    loaded = json.loads(str(value))
    return loaded if isinstance(loaded, list) else []


__all__ = [
    "get_episode_resource",
    "get_ingest_status_resource",
    "get_movie_resource",
    "get_show_resource",
    "register_resources",
]
