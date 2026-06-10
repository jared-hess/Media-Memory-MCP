from __future__ import annotations

from enum import StrEnum


class IngestJobState(StrEnum):
    """Recorded states for local ingest work."""

    DISCOVERED = "discovered"
    IDENTIFIED = "identified"
    METADATA_ENRICHED = "metadata_enriched"
    SUBTITLE_FOUND = "subtitle_found"
    SUBTITLE_DOWNLOADED = "subtitle_downloaded"
    SUBTITLE_PARSED = "subtitle_parsed"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    FAILED = "failed"


INGEST_JOB_STATES = tuple(state.value for state in IngestJobState)
