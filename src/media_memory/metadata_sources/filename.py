from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from media_memory.core.models import MediaItem


@dataclass(frozen=True)
class MetadataDocument:
    """Local metadata text that should be indexed as its own source document."""

    text: str
    source_path: str
    source_kind: str
    provider: str
    provider_ids: dict[str, str] | None = None
    provider_refs: list[dict[str, object]] | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        if self.provider_ids is None:
            object.__setattr__(self, "provider_ids", {"source_provider": self.provider})
        if self.provider_refs is None:
            object.__setattr__(
                self,
                "provider_refs",
                [{"provider": self.provider, "id": self.source_path, "namespace": "local-file"}],
            )


class FilenameMetadataSource:
    """Local sidecar metadata reader with no network calls."""

    provider_name = "filename"

    text_suffixes = ("summary.txt", "summary.md", "metadata.txt", "plex-overview.txt")
    json_suffixes = ("metadata.json", "summary.json")

    def __init__(self, *, enabled: bool = False):
        self.enabled = enabled

    def enrich(self, item: MediaItem) -> MediaItem:
        return item

    def find_documents(self, item: MediaItem) -> list[MetadataDocument]:
        documents: list[MetadataDocument] = []
        stem = item.path.stem
        for path in sorted(item.path.parent.iterdir()):
            if not path.is_file() or not path.name.startswith(f"{stem}."):
                continue
            suffix = path.name.removeprefix(f"{stem}.").casefold()
            if suffix in self.text_suffixes:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    documents.append(
                        MetadataDocument(
                            text=text,
                            source_path=str(path),
                            source_kind="metadata" if suffix.startswith("metadata") else "summary",
                            provider="plex-placeholder" if suffix.startswith("plex-overview") else self.provider_name,
                        )
                    )
            elif suffix in self.json_suffixes:
                document = self._document_from_json(path)
                if document is not None:
                    documents.append(document)
        return documents

    def _document_from_json(self, path: Path) -> MetadataDocument | None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        text = str(payload.get("summary") or payload.get("overview") or payload.get("plot") or payload.get("text") or "").strip()
        if not text:
            return None
        provider = str(payload.get("provider") or "manual")
        source_kind = str(payload.get("source_type") or payload.get("source_kind") or "metadata")
        return MetadataDocument(text=text, source_path=str(path), source_kind=source_kind, provider=provider)
