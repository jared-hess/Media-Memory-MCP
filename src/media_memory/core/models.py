from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MediaItem:
    title: str
    path: Path
    kind: str = "unknown"
    season: int | None = None
    episode: int | None = None


@dataclass(frozen=True)
class SubtitleChunk:
    media_path: str
    subtitle_path: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    season: int | None = None
    episode: int | None = None


@dataclass(frozen=True)
class SearchEvidence:
    chunk_id: int
    text: str
    score: float
    start_ms: int | None
    end_ms: int | None


@dataclass(frozen=True)
class SearchResult:
    media_path: str
    title: str
    combined_score: float
    lexical_score: float
    vector_score: float
    evidences: list[SearchEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_path": self.media_path,
            "title": self.title,
            "combined_score": self.combined_score,
            "lexical_score": self.lexical_score,
            "vector_score": self.vector_score,
            "evidences": [e.__dict__ for e in self.evidences],
        }
