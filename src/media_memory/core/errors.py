from __future__ import annotations


class MediaMemoryError(Exception):
    """Base class for typed Media Memory failures."""


class ConfigurationError(MediaMemoryError):
    """Raised when configuration is missing or invalid."""


class IngestError(MediaMemoryError):
    """Raised when media or subtitle ingest fails."""


class SearchError(MediaMemoryError):
    """Raised when search cannot be completed."""


class ProviderError(MediaMemoryError):
    """Raised when an external or local provider operation fails."""
