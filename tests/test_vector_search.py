from __future__ import annotations

import hashlib
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import (
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    EmbeddingProviderConfigError,
)
from media_memory.core.models import SubtitleChunk
from media_memory.core.vector_store import LanceDBVectorStore, LanceVectorStore


def test_mock_vectors_index_and_search_locally(tmp_path: Path) -> None:
    embeddings = MockEmbeddingProvider(dims=8)
    store = LanceVectorStore(tmp_path / "vectors")

    target = "winter is coming"
    store.upsert(
        101,
        embeddings.embed(target),
        {
            "media_item_id": "media-1",
            "document_id": "doc-1",
            "source_type": "subtitle",
            "source_provider": "local",
            "start_time_seconds": 1.0,
            "end_time_seconds": 3.0,
            "corpus_id": "local",
        },
    )
    store.upsert(
        202,
        embeddings.embed("a completely unrelated line"),
        {
            "media_item_id": "media-2",
            "document_id": "doc-2",
            "source_type": "subtitle",
            "source_provider": "local",
            "start_time_seconds": 4.0,
            "end_time_seconds": 6.0,
            "corpus_id": "local",
        },
    )

    results = store.search(embeddings.embed(target), limit=1)

    assert results[0][0] == 101
    assert results[0][1] > 0


def test_vector_index_can_be_deleted_and_rebuilt_from_sqlite_chunks(tmp_path: Path) -> None:
    db = _db_with_chunks(tmp_path)
    embeddings = MockEmbeddingProvider(dims=8)
    store = LanceVectorStore(tmp_path / "vectors")

    indexed_count = store.rebuild_from_chunks(db, embeddings)
    first_ids = [
        chunk_id for chunk_id, _score in store.search(embeddings.embed("hold the door"), limit=5)
    ]

    store.delete_index()
    assert store.search(embeddings.embed("hold the door"), limit=5) == []

    rebuilt_count = store.rebuild_from_chunks(db, embeddings)
    rebuilt_ids = [
        chunk_id for chunk_id, _score in store.search(embeddings.embed("hold the door"), limit=5)
    ]

    assert indexed_count == 2
    assert rebuilt_count == 2
    assert set(first_ids) == set(rebuilt_ids)
    assert set(rebuilt_ids) == {1, 2}


def test_legacy_lancedb_vector_store_alias_still_works(tmp_path: Path) -> None:
    embeddings = MockEmbeddingProvider(dims=8)
    store = LanceDBVectorStore(tmp_path / "legacy-vectors")
    store.upsert(1, embeddings.embed("legacy import"))

    assert store.search(embeddings.embed("legacy import"), limit=1)[0][0] == 1


def test_openai_provider_requires_key_only_when_configured() -> None:
    try:
        OpenAIEmbeddingProvider(None)
    except EmbeddingProviderConfigError as exc:
        assert "api_key" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("OpenAI provider should require an API key when explicitly configured")


def test_openai_provider_uses_configured_model_and_dimensions(monkeypatch) -> None:
    observed_calls: list[dict[str, object]] = []

    class FakeOpenAIClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.embeddings = _FakeOpenAIEmbeddings()

    class _FakeOpenAIEmbeddings:
        def create(self, **kwargs: object) -> SimpleNamespace:
            observed_calls.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[0.1, 0.2, 0.3]),
                    SimpleNamespace(embedding=[0.4, 0.5, 0.6]),
                ]
            )

    fake_openai_module = ModuleType("openai")
    setattr(fake_openai_module, "OpenAI", FakeOpenAIClient)
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

    model = "sentinel-openai-model"
    dimensions = 3
    input_texts = ["hello", "world"]

    provider = OpenAIEmbeddingProvider("test-key", model=model, dimensions=dimensions)
    vectors = provider.embed_texts(input_texts)

    assert len(observed_calls) == 1
    call_kwargs = observed_calls[0]
    assert call_kwargs["input"] == input_texts
    assert call_kwargs["model"] == model
    assert call_kwargs["encoding_format"] == "float"
    assert call_kwargs["dimensions"] == dimensions
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def _db_with_chunks(tmp_path: Path) -> MediaMemoryDB:
    db = MediaMemoryDB(tmp_path / "media-memory.sqlite")
    db.init_schema()
    media_id = db.upsert_media_item(path="/media/example.mkv", title="Example", kind="movie")
    chunks = [
        SubtitleChunk(
            media_path="/media/example.mkv",
            subtitle_path="/media/example.srt",
            text="hold the door",
            start_ms=1000,
            end_ms=3000,
        ),
        SubtitleChunk(
            media_path="/media/example.mkv",
            subtitle_path="/media/example.srt",
            text="winter is coming",
            start_ms=4000,
            end_ms=6000,
        ),
    ]
    for chunk in chunks:
        db.insert_chunk(media_id, chunk, hashlib.sha256(chunk.text.encode("utf-8")).hexdigest())
    return db
