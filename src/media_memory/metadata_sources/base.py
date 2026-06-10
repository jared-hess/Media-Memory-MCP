from __future__ import annotations

from typing import Protocol

from media_memory.core.models import MediaItem
from media_memory.media_sources.base import ProviderError


class MetadataSource(Protocol):
    """Interface implemented by metadata enrichment adapters."""

    def enrich(self, _item: MediaItem, /) -> MediaItem:
        """Return an enriched copy of a media item."""
        ...


class DisabledMetadataSource:
    """Base class for inert metadata placeholders."""

    provider_name = "metadata"

    def __init__(self, *, enabled: bool = False):
        self.enabled = enabled

    def enrich(self, item: MediaItem) -> MediaItem:
        if not self.enabled:
            return item
        raise ProviderError(
            f"{self.provider_name} metadata source is configured but not implemented yet."
        )
