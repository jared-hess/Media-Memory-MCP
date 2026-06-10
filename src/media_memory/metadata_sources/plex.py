from __future__ import annotations

import hashlib

from media_memory.core.models import MediaItem
from media_memory.metadata_sources.filename import MetadataDocument


class PlexMetadataSource:
    """Produce searchable metadata documents from Plex data already on a media item."""

    provider_name = "plex"

    def __init__(self, *, enabled: bool = False, url: str | None = None, token: str | None = None) -> None:
        self.enabled = enabled
        self.url = url
        self.token = token

    def enrich(self, item: MediaItem) -> MediaItem:
        return item

    def find_documents(self, item: MediaItem) -> list[MetadataDocument]:
        if not self.enabled:
            return []
        rating_key, raw = _plex_payload(item)
        if not rating_key or raw is None:
            return []
        overview = str(raw.get("summary") or raw.get("overview") or "").strip()
        if not overview:
            return []
        text = _document_text(item, raw, overview)
        source_path = f"plex://metadata/{rating_key}"
        return [
            MetadataDocument(
                text=text,
                source_path=source_path,
                source_kind="metadata",
                provider=self.provider_name,
                provider_ids={"source_provider": self.provider_name, "plex_rating_key": rating_key},
                provider_refs=[{"provider": self.provider_name, "id": rating_key, "namespace": "rating-key", "raw": raw}],
                checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        ]


def _plex_payload(item: MediaItem) -> tuple[str | None, dict[str, object] | None]:
    rating_key = item.provider_ids.get("plex_rating_key")
    for ref in item.provider_refs:
        if ref.provider != "plex" or ref.namespace != "rating-key":
            continue
        rating_key = rating_key or ref.id
        return rating_key, ref.raw
    return rating_key, None


def _document_text(item: MediaItem, raw: dict[str, object], overview: str) -> str:
    facts = [f"Title: {item.title}"]
    if item.show_title:
        facts.append(f"Show: {item.show_title}")
    if item.season_number is not None:
        facts.append(f"Season: {item.season_number}")
    if item.episode_number is not None:
        facts.append(f"Episode: {item.episode_number}")
    if item.year is not None:
        facts.append(f"Year: {item.year}")
    if item.runtime_seconds is not None:
        facts.append(f"Runtime seconds: {item.runtime_seconds}")
    rating = raw.get("rating") or raw.get("audienceRating") or raw.get("contentRating")
    if rating:
        facts.append(f"Rating: {rating}")
    facts.append(f"Overview: {overview}")
    return "\n".join(facts)
