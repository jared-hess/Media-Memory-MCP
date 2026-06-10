from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from media_memory.core.db import MediaMemoryDB
from media_memory.core.models import SubtitleChunk
from media_memory.mcp_server.resources import (
    get_episode_resource,
    get_ingest_status_resource,
    get_movie_resource,
    get_show_resource,
)
from media_memory.mcp_server.server import create_server
from media_memory.mcp_server.tools import create_legacy_server, create_services


def test_search_media_tool_matches_core_search_result_shape(tmp_path: Path) -> None:
    config_path, db_path = _write_config(tmp_path)
    chunk_id = _seed_episode(db_path)
    services = create_services(config_path)
    try:
        dispatcher = create_legacy_server(config_path)
        try:
            tool_payload = dispatcher.call_tool("search_media", query="winter coming", limit=5)
        finally:
            dispatcher.services.close()
        core_payload = [item.to_dict() for item in services.search.search_media("winter coming", limit=5)]

        assert tool_payload["results"] == core_payload
        assert tool_payload["results"][0]["evidences"][0]["chunk_id"] == chunk_id
        assert "confidence" in tool_payload["results"][0]
        assert "why" in tool_payload["results"][0]
    finally:
        services.close()


def test_search_dialogue_returns_timestamped_evidence(tmp_path: Path) -> None:
    config_path, db_path = _write_config(tmp_path)
    _seed_episode(db_path)
    dispatcher = create_legacy_server(config_path)
    try:
        payload = dispatcher.call_tool("search_dialogue", query="winter coming", limit=5)
    finally:
        dispatcher.services.close()

    assert payload["query"] == "winter coming"
    assert payload["results"]
    first = payload["results"][0]
    assert first["evidence"]["start_ms"] == 1000
    assert first["evidence"]["end_ms"] == 3000
    assert first["results"][0]["text"] == "Winter is coming."


def test_fastmcp_tool_registration_hides_ingest_by_default(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path)

    tool_names = asyncio.run(_tool_names(config_path))

    assert "search_media" in tool_names
    assert "get_media" in tool_names
    assert "ingest_library" not in tool_names
    dispatcher = create_legacy_server(config_path)
    try:
        with pytest.raises(ValueError, match="Unknown tool: ingest_library"):
            dispatcher.call_tool("ingest_library")
    finally:
        dispatcher.services.close()


def test_fastmcp_tool_registration_exposes_ingest_when_enabled(tmp_path: Path) -> None:
    config_path, _ = _write_config(tmp_path, allow_ingest=True)

    tool_names = asyncio.run(_tool_names(config_path))

    assert "ingest_library" in tool_names


def test_media_resources_return_read_only_shapes(tmp_path: Path) -> None:
    config_path, db_path = _write_config(tmp_path)
    _seed_episode(db_path)
    _seed_movie(db_path)
    services = create_services(config_path)
    try:
        show = get_show_resource(services, "example-show")
        episode = get_episode_resource(services, "example-show", 1, 1)
        movie = get_movie_resource(services, "example-movie", 1984)
        status = get_ingest_status_resource(services)
    finally:
        services.close()

    assert show["results"][0]["title"] == "Example Show S01E01"
    assert episode["result"]["season_number"] == 1
    assert movie["result"]["year"] == 1984
    assert status["counts"]["media_items"] == 2
    assert status["allow_ingest_tools"] is False


async def _tool_names(config_path: Path) -> set[str]:
    app = create_server(config_path)
    tools = await app.list_tools()
    return {tool.name for tool in tools}


def _write_config(tmp_path: Path, *, allow_ingest: bool = False) -> tuple[Path, Path]:
    db_path = tmp_path / "media-memory.sqlite"
    media_root = tmp_path / "media"
    media_root.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  data_dir: {tmp_path.as_posix()}
  corpus_id: local
mcp:
  allow_ingest_tools: {str(allow_ingest).lower()}
embeddings:
  provider: mock
  model: mock
  dimensions: 8
index:
  sqlite_path: {db_path.as_posix()}
  vector_path: {(tmp_path / 'vectors').as_posix()}
media_sources:
  - type: filesystem
    enabled: true
    name: test-media
    roots:
      - {media_root.as_posix()}
    read_only: true
    extensions:
      - .mkv
  - type: plex
    enabled: false
subtitle_sources:
  opensubtitles:
    enabled: false
  bazarr:
    enabled: false
search:
  default_limit: 5
  max_limit: 20
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path, db_path


def _seed_episode(db_path: Path) -> int:
    db = MediaMemoryDB(db_path)
    db.init_schema()
    media_id = db.upsert_media_item(
        path="/media/Example.Show.S01E01.mkv",
        title="Example Show S01E01",
        kind="episode",
        season=1,
        episode=1,
    )
    db.conn.execute(
        "UPDATE media_items SET show_title = ?, episode_title = ? WHERE legacy_id = ?",
        ("Example Show", "Pilot", media_id),
    )
    chunk_id = db.insert_chunk(
        media_id,
        SubtitleChunk(
            media_path="/media/Example.Show.S01E01.mkv",
            subtitle_path="/media/Example.Show.S01E01.srt",
            text="Winter is coming.",
            start_ms=1000,
            end_ms=3000,
        ),
        text_hash="episode-hash",
    )
    db.conn.commit()
    db.close()
    assert chunk_id is not None
    return int(chunk_id)


def _seed_movie(db_path: Path) -> None:
    db = MediaMemoryDB(db_path)
    db.init_schema()
    media_id = db.upsert_media_item(
        path="/media/Example.Movie.1984.mkv",
        title="Example Movie",
        kind="movie",
    )
    db.conn.execute("UPDATE media_items SET year = ? WHERE legacy_id = ?", (1984, media_id))
    db.conn.commit()
    db.close()
