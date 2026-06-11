from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_CORPUS_ID = "local"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    """Base class for JSON-friendly immutable domain models."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary for CLI/MCP responses."""

        return self.model_dump(mode="json")


class ProviderRef(DomainModel):
    """External provider identifier attached to a media or document record."""

    provider: str
    id: str
    namespace: str | None = None
    url: str | None = None
    confidence: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ProviderCandidate(DomainModel):
    """Candidate match returned by future metadata/subtitle providers."""

    provider: str
    external_id: str | None = None
    title: str | None = None
    kind: str | None = None
    year: int | None = None
    score: float | None = None
    refs: list[ProviderRef] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class MediaItem(DomainModel):
    """Corpus-aware media item while preserving scanner-era fields."""

    title: str
    path: Path
    kind: str = "unknown"
    season: int | None = None
    episode: int | None = None
    id: str | None = None
    corpus_id: str = DEFAULT_CORPUS_ID
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    year: int | None = None
    air_date: date | None = None
    runtime_seconds: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    provider_refs: list[ProviderRef] = Field(default_factory=list)
    checksum: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Document(DomainModel):
    """A searchable source document such as a sidecar subtitle file."""

    id: str | None = None
    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    media_path: str | None = None
    source_path: str | None = None
    source_uri: str | None = None
    source_kind: str = "subtitle"
    language: str | None = None
    title: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    provider_refs: list[ProviderRef] = Field(default_factory=list)
    checksum: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Chunk(DomainModel):
    """Searchable text span, compatible with the legacy SubtitleChunk shape."""

    media_path: str
    subtitle_path: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    season: int | None = None
    episode: int | None = None
    id: str | None = None
    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    document_id: str | None = None
    chunk_index: int | None = None
    normalized_text: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    source_kind: str = "subtitle"
    language: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SubtitleChunk(Chunk):
    """Backward-compatible import name for subtitle chunks."""


class SearchFilters(DomainModel):
    """Structured filters for future search APIs."""

    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    media_path: str | None = None
    kind: str | None = None
    title: str | None = None
    show: str | None = None
    show_title: str | None = None
    season: int | None = None
    episode: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    year: int | None = None
    language: str | None = None
    source_kind: str | None = None
    source_type: str | None = None
    source_provider: str | None = None
    limit: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)


class SearchEvidence(DomainModel):
    chunk_id: int | str
    text: str
    score: float
    start_ms: int | None
    end_ms: int | None
    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    document_id: str | None = None
    media_path: str | None = None
    subtitle_path: str | None = None
    normalized_text: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    source_kind: str | None = None
    source_provider: str | None = None
    source_path: str | None = None
    source_uri: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    checksum: str | None = None


class SearchResult(DomainModel):
    media_path: str
    title: str
    combined_score: float
    lexical_score: float
    vector_score: float
    evidences: list[SearchEvidence]
    id: str | None = None
    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    kind: str | None = None
    show_title: str | None = None
    season: int | None = None
    episode: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    year: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    confidence: float | None = None
    why: list[str] = Field(default_factory=list)

    def __init__(self, *args: Any, **data: Any) -> None:
        """Accept the legacy positional constructor shape plus keyword use."""

        legacy_fields = (
            "media_path",
            "title",
            "combined_score",
            "lexical_score",
            "vector_score",
            "evidences",
        )
        if args:
            if len(args) > len(legacy_fields):
                raise TypeError(
                    f"SearchResult expected at most {len(legacy_fields)} positional arguments"
                )
            for field_name, value in zip(legacy_fields, args, strict=False):
                if field_name in data:
                    raise TypeError(f"SearchResult got multiple values for argument '{field_name}'")
                data[field_name] = value
        super().__init__(**data)


class IngestJob(DomainModel):
    """Durable ingest job descriptor for future pipeline work."""

    id: str | None = None
    corpus_id: str = DEFAULT_CORPUS_ID
    media_id: str | None = None
    media_path: str | None = None
    document_id: str | None = None
    source_path: str | None = None
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    error: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None
    stats: dict[str, int] = Field(default_factory=dict)
