from __future__ import annotations

from media_memory.metadata_sources.base import DisabledMetadataSource


class TmdbMetadataSource(DisabledMetadataSource):
    """Inert placeholder for future TMDb metadata enrichment."""

    provider_name = "tmdb"
    def __init__(self, *, enabled: bool = False, api_key: str | None = None):
        super().__init__(enabled=enabled)
        self.api_key = api_key
