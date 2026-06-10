from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable


ID_VERSION = "v1"
DEFAULT_CORPUS_ID = "local"


def media_id(
    *,
    path: str | Path | None = None,
    corpus_id: str = DEFAULT_CORPUS_ID,
    external_ids: dict[str, str] | None = None,
    checksum: str | None = None,
    title: str | None = None,
    kind: str | None = None,
) -> str:
    """Return a deterministic media ID scoped to a corpus.

    Prefer stable external IDs or checksums when available. If neither is
    supplied, the ID is derived from the normalized path and may change when a
    file is moved or renamed.
    """

    if external_ids:
        basis = _join_pairs("external", external_ids.items())
        hint = _hint(next(iter(sorted(external_ids.items())))[1])
    elif checksum:
        basis = f"checksum:{_normalize(checksum)}"
        hint = _hint(checksum)
    elif path is not None:
        basis = f"path:{_normalize_path(path)}"
        hint = _hint(Path(path).stem)
    else:
        basis = f"metadata:{_normalize(kind)}:{_normalize(title)}"
        hint = _hint(title or kind)
    return _format_id("media", corpus_id, hint, basis)


def document_id(
    *,
    media_id: str,
    source_path: str | Path | None = None,
    corpus_id: str = DEFAULT_CORPUS_ID,
    source_kind: str = "subtitle",
    checksum: str | None = None,
    external_ids: dict[str, str] | None = None,
) -> str:
    """Return a deterministic source-document ID.

    Prefer external IDs/checksums for documents that may move. Path-derived
    document IDs are intentionally deterministic but may change on move/rename.
    """

    if external_ids:
        source_basis = _join_pairs("external", external_ids.items())
    elif checksum:
        source_basis = f"checksum:{_normalize(checksum)}"
    else:
        source_basis = f"path:{_normalize_path(source_path) if source_path is not None else ''}"
    basis = "|".join([_normalize(media_id), _normalize(source_kind), source_basis])
    return _format_id("doc", corpus_id, _hint(source_path or source_kind), basis)


def chunk_id(
    *,
    document_id: str,
    text: str,
    corpus_id: str = DEFAULT_CORPUS_ID,
    start_ms: int | None = None,
    end_ms: int | None = None,
    chunk_index: int | None = None,
) -> str:
    """Return a deterministic chunk ID for a document/time/text span."""

    basis = "|".join(
        [
            _normalize(document_id),
            _normalize(chunk_index),
            _normalize(start_ms),
            _normalize(end_ms),
            _normalize(text),
        ]
    )
    hint = f"{chunk_index}" if chunk_index is not None else start_ms
    return _format_id("chunk", corpus_id, _hint(hint), basis)


def ingest_job_id(
    *,
    corpus_id: str = DEFAULT_CORPUS_ID,
    media_id: str | None = None,
    document_id: str | None = None,
    source_path: str | Path | None = None,
    requested_at: str | None = None,
) -> str:
    """Return a deterministic ingest job ID for a requested ingest target."""

    basis = "|".join(
        [
            _normalize(media_id),
            _normalize(document_id),
            _normalize_path(source_path) if source_path is not None else "",
            _normalize(requested_at),
        ]
    )
    return _format_id("ingest", corpus_id, _hint(source_path or media_id or document_id), basis)


def embedding_id(
    *,
    chunk_id: str,
    provider: str,
    model: str,
    corpus_id: str = DEFAULT_CORPUS_ID,
    dimensions: int | None = None,
) -> str:
    """Return a deterministic embedding ID for a chunk/provider/model tuple."""

    basis = "|".join([_normalize(chunk_id), _normalize(provider), _normalize(model), _normalize(dimensions)])
    return _format_id("emb", corpus_id, _hint(model), basis)


def _format_id(kind: str, corpus_id: str, hint: str, basis: str) -> str:
    digest = hashlib.sha256(f"{ID_VERSION}|{kind}|{_normalize(corpus_id)}|{basis}".encode("utf-8")).hexdigest()[:16]
    parts = [ID_VERSION, kind, _slug(corpus_id)]
    if hint:
        parts.append(hint)
    parts.append(digest)
    return ":".join(parts)


def _join_pairs(prefix: str, pairs: Iterable[tuple[str, str]]) -> str:
    values = [f"{_normalize(key)}={_normalize(value)}" for key, value in sorted(pairs)]
    return f"{prefix}:" + ",".join(values)


def _normalize(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())


def _normalize_path(value: str | Path) -> str:
    return Path(value).as_posix().strip().casefold()


def _hint(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        value = value.stem
    return _slug(str(value))


def _slug(value: object | None) -> str:
    text = _normalize(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:32] or "unknown"
