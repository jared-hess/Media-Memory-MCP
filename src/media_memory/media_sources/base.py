from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from pydantic import Field

from media_memory.core.errors import ProviderError as ProviderError
from media_memory.core.models import DomainModel, MediaItem, ProviderRef


class MediaRef(DomainModel):
    """Provider-neutral reference to a media object."""

    path: Path | None = None
    uri: str | None = None
    title: str | None = None
    kind: str = "unknown"
    provider_refs: list[ProviderRef] = Field(default_factory=list)


class MediaSource(Protocol):
    """Interface implemented by media source adapters."""

    def scan(self) -> Iterable[MediaItem | MediaRef]:
        """Return media items or media references discovered by the source."""
