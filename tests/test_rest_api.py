from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from media_memory.api import create_app
from media_memory.core.db import MediaMemoryDB
from media_memory.core.models import SubtitleChunk
from media_memory.mcp_server.tools import create_services, search_media_payload


def test_health_and_status_are_config_safe(tmp_path: Path) -> None:
    config_path, db_path, _ = _write_config(tmp_path)
    _seed_episode(db_path)
    app = create_app(config_path)

    health_status, health = _request(app, "GET", "/health")
    status_code, payload = _request(app, "GET", "/status")

    assert health_status == 200
    assert health == {"status": "ok", "service": "media-memory", "api": "rest"}
    assert status_code == 200
    assert payload["db"]["exists"] is True
    assert payload["counts"]["media_items"] == 1
    assert payload["providers"]["mcp"]["allow_ingest_tools"] is False
    assert "api_key" not in json.dumps(payload).lower()
    assert "token" not in json.dumps(payload).lower()


def test_search_shape_matches_core(tmp_path: Path) -> None:
    config_path, db_path, _ = _write_config(tmp_path)
    chunk_id = _seed_episode(db_path)
    app = create_app(config_path)
    services = create_services(config_path)
    try:
        expected = search_media_payload(services, query="winter coming", limit=5)
    finally:
        services.close()

    status_code, payload = _request(app, "POST", "/search", {"query": "winter coming", "limit": 5})

    assert status_code == 200
    assert payload == expected
    assert payload["results"][0]["evidences"][0]["chunk_id"] == chunk_id
    assert "confidence" in payload["results"][0]
    assert "why" in payload["results"][0]


def test_media_and_scene_endpoints_use_core_shapes(tmp_path: Path) -> None:
    config_path, db_path, _ = _write_config(tmp_path)
    chunk_id = _seed_episode(db_path)
    app = create_app(config_path)

    media_status, media_payload = _request(app, "GET", "/media/1")
    scene_status, scene_payload = _request(app, "GET", "/media/1/scene", query_string="start=1.2")

    assert media_status == 200
    assert media_payload["result"]["title"] == "Example Show S01E01"
    assert scene_status == 200
    assert scene_payload["result"]["chunk_id"] == chunk_id
    assert scene_payload["result"]["current"]["text"] == "Winter is coming."


def test_ingest_endpoint_requires_enabled_config(tmp_path: Path) -> None:
    config_path, _, _ = _write_config(tmp_path)
    app = create_app(config_path)

    status_code, payload = _request(app, "POST", "/ingest")

    assert status_code == 403
    assert "disabled" in payload["error"]


def test_ingest_endpoint_uses_same_enabled_gate(tmp_path: Path) -> None:
    config_path, _, media_root = _write_config(tmp_path, allow_ingest=True)
    (media_root / "Example.S01E02.mkv").write_text("placeholder", encoding="utf-8")
    (media_root / "Example.S01E02.srt").write_text(
        "1\n00:00:02,000 --> 00:00:04,000\nThe north remembers.\n",
        encoding="utf-8",
    )
    app = create_app(config_path)

    status_code, payload = _request(app, "POST", "/ingest")

    assert status_code == 200
    assert payload["scanned"] == 1
    assert payload["stats"]["new_chunks"] == 1


def _request(
    app: Any,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
    *,
    query_string: str = "",
) -> tuple[int, dict[str, Any]]:
    return asyncio.run(_asgi_request(app, method, path, body, query_string=query_string))


async def _asgi_request(
    app: Any,
    method: str,
    path: str,
    body: dict[str, object] | None,
    *,
    query_string: str,
) -> tuple[int, dict[str, Any]]:
    body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
    sent: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string.encode("utf-8"),
            "headers": [],
        },
        receive,
        send,
    )
    start = next(message for message in sent if message["type"] == "http.response.start")
    response = next(message for message in sent if message["type"] == "http.response.body")
    return int(start["status"]), json.loads(response["body"].decode("utf-8"))


def _write_config(tmp_path: Path, *, allow_ingest: bool = False) -> tuple[Path, Path, Path]:
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
    return config_path, db_path, media_root


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
