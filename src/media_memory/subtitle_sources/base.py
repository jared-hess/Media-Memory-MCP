from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from pydantic import Field

from media_memory.core.models import DomainModel, MediaItem, ProviderCandidate


class SubtitleCandidate(DomainModel):
    """A candidate subtitle file or provider match for a media item."""

    path: Path | None = None
    uri: str | None = None
    language: str | None = None
    provider: str = "local"
    score: float | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class SubtitleSource(Protocol):
    """Interface implemented by subtitle source adapters."""

    def find(self, _item: MediaItem, /) -> Iterable[Path | SubtitleCandidate | ProviderCandidate]:
        """Return subtitle candidates for a media item."""

    def fetch(self, _candidate: Path | SubtitleCandidate | ProviderCandidate, /) -> Path:
        """Resolve a subtitle candidate to a local readable file."""
