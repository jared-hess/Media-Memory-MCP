from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from media_memory.cli import app


runner = CliRunner()


def _write_config(path: Path, db_path: Path, media_root: Path) -> None:
    path.write_text(
        f"""
app:
  data_dir: {db_path.parent.as_posix()}
  corpus_id: local
embeddings:
  provider: mock
  model: mock
  dimensions: 8
index:
  sqlite_path: {db_path.as_posix()}
  vector_path: {(db_path.parent / "vectors").as_posix()}
media_sources:
  - type: filesystem
    enabled: true
    name: test-media
    roots:
      - {media_root.as_posix()}
    read_only: true
    extensions:
      - .mkv
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


def _write_media_fixture(media_root: Path) -> None:
    media_root.mkdir(parents=True)
    (media_root / "Example.S01E01.mkv").write_text("placeholder", encoding="utf-8")
    (media_root / "Example.S01E01.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nWinter is coming.\n",
        encoding="utf-8",
    )


def test_help_lists_required_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["init", "scan", "ingest", "reindex", "status", "search", "mcp"]:
        assert command in result.output


def test_scan_json_returns_discovered_refs(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    config_path = tmp_path / "config.yaml"
    _write_media_fixture(media_root)
    _write_config(config_path, tmp_path / "media-memory.sqlite", media_root)

    result = runner.invoke(app, ["scan", str(media_root), "--config", str(config_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["title"] == "Example.S01E01"
    assert payload[0]["kind"] == "episode"


def test_status_json_returns_db_job_and_index_status(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    config_path = tmp_path / "config.yaml"
    _write_media_fixture(media_root)
    _write_config(config_path, tmp_path / "media-memory.sqlite", media_root)

    result = runner.invoke(app, ["status", "--config", str(config_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["db"]["exists"] is True
    assert payload["db"]["path"] == (tmp_path / "media-memory.sqlite").as_posix()
    assert payload["corpus"] == {"configured": "local", "count": 0}
    assert payload["jobs"] == {"total": 0, "pending": 0, "failed": 0, "by_status": {}}
    assert payload["index"]["state"] == "ready"
    assert payload["index"]["fts"] == "ready"
    assert payload["counts"] == {"media_items": 0, "documents": 0, "chunks": 0}
    assert payload["providers"] == {
        "media_sources": {"filesystem": True, "plex": False},
        "subtitle_sources": {
            "local": True,
            "embedded": False,
            "opensubtitles": False,
            "bazarr": False,
        },
        "metadata": {
            "fetch_external": False,
            "preferred": ["plex", "filename", "tmdb", "tvmaze"],
        },
        "embeddings": {"provider": "mock", "model": "mock"},
        "mcp": {
            "transport": "stdio",
            "allow_ingest_tools": False,
            "read_only_resources": True,
        },
    }


def test_init_ingest_and_search_flow(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    config_path = tmp_path / "config.yaml"
    _write_media_fixture(media_root)
    _write_config(config_path, tmp_path / "media-memory.sqlite", media_root)

    init_path = tmp_path / "generated.yaml"
    init_result = runner.invoke(app, ["init", "--config", str(init_path), "--json"])
    assert init_result.exit_code == 0
    assert json.loads(init_result.output)["created"] is True
    assert init_path.exists()

    ingest_result = runner.invoke(
        app,
        ["ingest", str(media_root), "--config", str(config_path), "--json"],
    )
    assert ingest_result.exit_code == 0
    ingest_payload = json.loads(ingest_result.output)
    assert ingest_payload["scanned"] == 1
    assert ingest_payload["stats"]["media_items"] == 1
    assert ingest_payload["stats"]["new_chunks"] >= 1

    search_result = runner.invoke(
        app,
        ["search", "winter", "--config", str(config_path), "--limit", "5", "--json"],
    )
    assert search_result.exit_code == 0
    search_payload = json.loads(search_result.output)
    assert search_payload
    assert search_payload[0]["title"] == "Example.S01E01"
