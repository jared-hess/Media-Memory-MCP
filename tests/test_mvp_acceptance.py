from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from typer.testing import CliRunner

from media_memory.cli import app
from media_memory.config import load_config
from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.models import SearchResult
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceDBVectorStore


FIXTURE_MEDIA_ROOT = Path("tests/fixtures/media")
FIXTURE_CONFIG = Path("tests/fixtures/config.test.yaml")
GOLDEN_QUERIES = (
    {
        "query": "George gets engaged",
        "expected_path": "Seinfeld.S07E01.The.Engagement.mkv",
        "show_title": "Seinfeld",
        "season": 7,
        "episode": 1,
        "source_kind": "summary",
    },
    {
        "query": "marine biologist",
        "expected_path": "Seinfeld.S05E14.The.Marine.Biologist.mkv",
        "show_title": "Seinfeld",
        "season": 5,
        "episode": 14,
        "source_kind": "subtitle",
    },
    {
        "query": "four lights",
        "expected_path": "Star.Trek.The.Next.Generation.S06E10.Chain.Of.Command.Part.II.mkv",
        "show_title": "Star Trek The Next Generation",
        "season": 6,
        "episode": 10,
        "source_kind": "subtitle",
    },
    {
        "query": "red pill",
        "expected_path": "The.Matrix.1999.mkv",
        "year": 1999,
        "source_kind": "subtitle",
    },
    {
        "query": "root beer is vile",
        "expected_path": "Star.Trek.Deep.Space.Nine.S04E26.Broken.Link.mkv",
        "show_title": "Star Trek Deep Space Nine",
        "season": 4,
        "episode": 26,
        "source_kind": "subtitle",
    },
)


@dataclass(frozen=True)
class IndexedFixture:
    config_path: Path
    db_path: Path
    vector_path: Path


def test_fixture_config_uses_safe_local_defaults() -> None:
    config = load_config(FIXTURE_CONFIG)

    assert config.app.corpus_id == "local"
    assert config.embeddings.provider == "mock"
    assert config.embeddings.model == "mock"
    assert not config.subtitle_sources.opensubtitles.enabled
    assert not config.subtitle_sources.bazarr.enabled
    assert any(source.type == "filesystem" and source.read_only for source in config.media_sources)


def test_golden_queries_top_result_accuracy(tmp_path: Path) -> None:
    fixture = _index_fixture(tmp_path)
    search = _search_service(fixture)

    correct = 0
    for golden in GOLDEN_QUERIES:
        results = search.search_media(str(golden["query"]), limit=3)
        assert results, golden["query"]
        top = results[0]
        _assert_result_has_evidence(top, expected_source_kind=str(golden["source_kind"]))
        if _matches_expected_media(top, golden):
            correct += 1

    assert correct >= 4


def test_golden_query_results_include_evidence_and_subtitle_timestamps(tmp_path: Path) -> None:
    fixture = _index_fixture(tmp_path)
    search = _search_service(fixture)

    for golden in GOLDEN_QUERIES:
        results = search.search_media(str(golden["query"]), limit=3)
        assert results, golden["query"]
        matching_results = [result for result in results if _matches_expected_media(result, golden)]
        assert matching_results, golden["query"]
        _assert_result_has_evidence(
            matching_results[0], expected_source_kind=str(golden["source_kind"])
        )


def test_fixture_ingest_rerun_creates_no_duplicate_chunks(tmp_path: Path) -> None:
    fixture = _index_fixture(tmp_path)
    db = MediaMemoryDB(fixture.db_path)
    try:
        first_counts = (db.count_media_items(), db.count_documents(), db.count_chunks())
    finally:
        db.close()

    second = _run_cli(
        [
            "ingest",
            str(FIXTURE_MEDIA_ROOT),
            "--config",
            str(fixture.config_path),
            "--json",
        ]
    )
    db = MediaMemoryDB(fixture.db_path)
    try:
        second_counts = (db.count_media_items(), db.count_documents(), db.count_chunks())
    finally:
        db.close()

    second_stats = second["stats"]
    assert isinstance(second_stats, dict)
    assert second_stats["failed_jobs"] == 0
    assert second_stats["new_chunks"] == 0
    assert second_counts == first_counts


def test_fixture_query_median_latency_under_500_ms_after_indexing(tmp_path: Path) -> None:
    fixture = _index_fixture(tmp_path)
    search = _search_service(fixture)

    for golden in GOLDEN_QUERIES:
        assert search.search_media(str(golden["query"]), limit=3)

    timings_ms: list[float] = []
    for golden in GOLDEN_QUERIES * 3:
        start = time.perf_counter()
        results = search.search_media(str(golden["query"]), limit=3)
        timings_ms.append((time.perf_counter() - start) * 1000)
        assert results, golden["query"]

    assert statistics.median(timings_ms) < 500


def _index_fixture(tmp_path: Path) -> IndexedFixture:
    config_path = _write_temp_config(tmp_path)
    payload = _run_cli(["ingest", str(FIXTURE_MEDIA_ROOT), "--config", str(config_path), "--json"])
    stats = payload["stats"]
    scanned = payload["scanned"]
    assert isinstance(stats, dict)
    assert isinstance(scanned, int)
    assert scanned >= len(GOLDEN_QUERIES)
    assert stats["failed_jobs"] == 0
    assert stats["new_chunks"] > 0
    return IndexedFixture(
        config_path=config_path,
        db_path=tmp_path / "media-memory.sqlite",
        vector_path=tmp_path / "vectors",
    )


def _write_temp_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.test.yaml"
    config_path.write_text(
        f"""
app:
  data_dir: {tmp_path.as_posix()}
  corpus_id: local
embeddings:
  provider: mock
  model: mock
  dimensions: 8
index:
  sqlite_path: {(tmp_path / "media-memory.sqlite").as_posix()}
  vector_path: {(tmp_path / "vectors").as_posix()}
media_sources:
  - type: filesystem
    enabled: true
    name: fixture-media
    roots:
      - {FIXTURE_MEDIA_ROOT.as_posix()}
    read_only: true
    extensions:
      - .mkv
      - .mp4
  - type: plex
    enabled: false
subtitle_sources:
  opensubtitles:
    enabled: false
  bazarr:
    enabled: false
search:
  default_limit: 5
  max_limit: 25
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _run_cli(args: list[str]) -> dict[str, object]:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    payload = result.output.strip()
    assert payload
    import json

    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    return parsed


def _search_service(fixture: IndexedFixture) -> SearchService:
    db = MediaMemoryDB(fixture.db_path)
    db.init_schema()
    embeddings = MockEmbeddingProvider(dims=8)
    vectors = LanceDBVectorStore(fixture.vector_path)
    vectors.rebuild_from_chunks(db, embeddings)
    return SearchService(db, embeddings, vectors, use_cache=True)


def _matches_expected_media(result: SearchResult, golden: dict[str, object]) -> bool:
    if not result.media_path.endswith(str(golden["expected_path"])):
        return False
    for field in ("show_title", "season", "episode", "title", "year"):
        if field in golden and getattr(result, field) != golden[field]:
            return False
    return True


def _assert_result_has_evidence(result: SearchResult, *, expected_source_kind: str) -> None:
    assert result.evidences
    assert any(evidence.text.strip() for evidence in result.evidences)
    if expected_source_kind == "subtitle":
        assert any(
            evidence.start_ms is not None and evidence.end_ms is not None
            for evidence in result.evidences
        )
    else:
        assert any(
            evidence.start_ms is None and evidence.end_ms is None for evidence in result.evidences
        )
