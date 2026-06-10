from __future__ import annotations

from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.models import SearchFilters, SubtitleChunk
from media_memory.core.search import SearchService
from media_memory.mcp_server.tools import create_services, search_media_payload


def test_search_service_is_isolated_by_corpus_filter(tmp_path: Path) -> None:
    db_path = _seed_two_corpora(tmp_path)

    db = MediaMemoryDB(db_path)
    db.init_schema()
    service = SearchService(db)

    local = service.search_media(
        "shared query phrase", limit=10, filters=SearchFilters(corpus_id="local", limit=10)
    )
    remote = service.search_media(
        "shared query phrase", limit=10, filters=SearchFilters(corpus_id="remote", limit=10)
    )

    assert len(local) == 1
    assert len(remote) == 1
    assert local[0].title == "Example Local"
    assert remote[0].title == "Example Remote"

    db.close()


def test_mcp_search_payload_respects_configured_corpus_id(tmp_path: Path) -> None:
    db_path = _seed_two_corpora(tmp_path)

    local_config = _write_config(tmp_path, db_path, "local")
    remote_config = _write_config(tmp_path, db_path, "remote")

    local_services = create_services(local_config)
    remote_services = create_services(remote_config)
    try:
        local_payload = search_media_payload(local_services, query="shared query phrase", limit=10)
        remote_payload = search_media_payload(
            remote_services, query="shared query phrase", limit=10
        )
    finally:
        local_services.close()
        remote_services.close()

    local_titles = [result["title"] for result in local_payload["results"]]
    remote_titles = [result["title"] for result in remote_payload["results"]]

    assert local_titles == ["Example Local"]
    assert remote_titles == ["Example Remote"]


def _seed_two_corpora(tmp_path: Path) -> Path:
    db_path = tmp_path / "media-memory.sqlite"
    db = MediaMemoryDB(db_path)
    db.init_schema()

    _seed_media(
        db,
        corpus_id="local",
        path="/media/Example.Local.mkv",
        title="Example Local",
        text="A shared query phrase only appears in local.",
        chunk_hash="local-hash",
    )
    _seed_media(
        db,
        corpus_id="remote",
        path="/remote/Example.Remote.mkv",
        title="Example Remote",
        text="A shared query phrase only appears in remote.",
        chunk_hash="remote-hash",
    )

    db.conn.commit()
    db.close()
    return db_path


def _seed_media(
    db: MediaMemoryDB,
    *,
    corpus_id: str,
    path: str,
    title: str,
    text: str,
    chunk_hash: str,
) -> None:
    media_id = db.upsert_media_item(path=path, title=title, kind="movie", corpus_id=corpus_id)
    chunk_id = db.insert_chunk(
        media_id,
        SubtitleChunk(media_path=path, subtitle_path=f"{path}.srt", text=text),
        text_hash=chunk_hash,
    )
    assert chunk_id is not None


def _write_config(tmp_path: Path, db_path: Path, corpus_id: str) -> Path:
    config_path = tmp_path / f"config-{corpus_id}.yaml"
    config_path.write_text(
        f"""
app:
  data_dir: {tmp_path.as_posix()}
  corpus_id: {corpus_id}
embeddings:
  provider: mock
  model: mock
  dimensions: 8
index:
  sqlite_path: {db_path.as_posix()}
  vector_path: {(tmp_path / "vectors").as_posix()}
search:
  default_limit: 10
  max_limit: 20
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path
