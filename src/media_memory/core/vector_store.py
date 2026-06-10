from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider


VECTOR_TABLE_NAME = "chunks"
SCHEMA_SEED_CHUNK_ID = -1


class VectorRecord(dict[str, Any]):
    """Dictionary-shaped vector row accepted by LanceDB."""


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, chunk_id: int, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, vector: list[float], limit: int = 20) -> list[tuple[int, float]]:
        raise NotImplementedError


class LanceVectorStore(VectorStore):
    """Local LanceDB-backed derived vector index for subtitle chunks."""

    def __init__(self, path: str | Path | None = None, *, table_name: str = VECTOR_TABLE_NAME) -> None:
        self._temporary_directory: TemporaryDirectory[str] | None = None
        if path is None:
            self._temporary_directory = TemporaryDirectory(prefix="media-memory-vectors-")
            self.path = Path(self._temporary_directory.name)
        else:
            self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.table_name = table_name
        import lancedb

        self._db = lancedb.connect(str(self.path))

    def close(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def __del__(self) -> None:
        self.close()

    def upsert(self, chunk_id: int, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        record = self._record(chunk_id, vector, metadata or {})
        table = self._table_or_none()
        if table is None:
            table = self._db.create_table(self.table_name, data=[_schema_seed(record), record])
            table.delete(f"chunk_id = {SCHEMA_SEED_CHUNK_ID}")
            return
        table.delete(f"chunk_id = {int(chunk_id)}")
        table.add([record])

    def search(self, vector: list[float], limit: int = 20) -> list[tuple[int, float]]:
        table = self._table_or_none()
        if table is None:
            return []
        rows = table.search(vector).limit(limit).to_list()
        results: list[tuple[int, float]] = []
        for row in rows:
            distance = float(row.get("_distance", 0.0))
            results.append((int(row["chunk_id"]), 1.0 / (1.0 + distance)))
        return results

    def rebuild_from_chunks(self, db: MediaMemoryDB, embeddings: EmbeddingProvider) -> int:
        """Recreate the derived LanceDB table from canonical SQLite chunks."""

        self.delete_index()
        rows = db.list_all_chunks()
        if not rows:
            return 0
        vectors = embeddings.embed_texts([str(row["text"]) for row in rows])
        records = [self._record(int(row["chunk_id"]), vector, _metadata_from_chunk_row(row)) for row, vector in zip(rows, vectors)]
        table = self._db.create_table(self.table_name, data=[_schema_seed(records[0]), *records], mode="overwrite")
        table.delete(f"chunk_id = {SCHEMA_SEED_CHUNK_ID}")
        return len(records)

    def delete_index(self) -> None:
        table_names = self._table_names()
        if self.table_name in table_names:
            self._db.drop_table(self.table_name)
        table_path = self.path / f"{self.table_name}.lance"
        if table_path.exists():
            shutil.rmtree(table_path)

    def _table_or_none(self) -> Any | None:
        if self.table_name not in self._table_names():
            return None
        return self._db.open_table(self.table_name)

    def _table_names(self) -> set[str]:
        if hasattr(self._db, "list_tables"):
            response = self._db.list_tables()
            names = getattr(response, "tables", response)
            return {str(name) for name in names}
        return {str(name) for name in self._db.table_names()}

    def _record(self, chunk_id: int, vector: list[float], metadata: dict[str, Any]) -> VectorRecord:
        return VectorRecord(
            chunk_id=int(chunk_id),
            vector=[float(value) for value in vector],
            media_item_id=str(metadata.get("media_item_id") or ""),
            document_id=str(metadata.get("document_id") or ""),
            source_type=str(metadata.get("source_type") or ""),
            source_provider=str(metadata.get("source_provider") or ""),
            start_time_seconds=_optional_float(metadata.get("start_time_seconds")),
            end_time_seconds=_optional_float(metadata.get("end_time_seconds")),
            corpus_id=str(metadata.get("corpus_id") or "local"),
        )


class LanceDBVectorStore(LanceVectorStore):
    """Backward-compatible name retained for existing imports/tests."""


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _schema_seed(record: VectorRecord) -> VectorRecord:
    seed = VectorRecord(record)
    seed["chunk_id"] = SCHEMA_SEED_CHUNK_ID
    seed["media_item_id"] = "schema-seed"
    seed["document_id"] = "schema-seed"
    seed["source_type"] = "schema-seed"
    seed["source_provider"] = "schema-seed"
    seed["start_time_seconds"] = 0.0
    seed["end_time_seconds"] = 0.0
    seed["corpus_id"] = "schema-seed"
    return seed


def _metadata_from_chunk_row(row: Any) -> dict[str, Any]:
    return {
        "chunk_id": int(row["chunk_id"]),
        "media_item_id": str(row["media_item_id"]),
        "document_id": str(row["document_id"]),
        "source_type": str(row["source_type"]),
        "source_provider": str(row["source_provider"]),
        "start_time_seconds": row["start_time_seconds"],
        "end_time_seconds": row["end_time_seconds"],
        "corpus_id": str(row["corpus_id"]),
    }
