from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from media_memory.core.models import MediaItem, ProviderCandidate
from media_memory.media_sources.base import ProviderError
from media_memory.subtitle_sources.base import SubtitleCandidate

PROVIDER_NAME = "embedded"


class CommandResult(Protocol):
    """Minimal subprocess result shape used by the embedded extractor."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str]], CommandResult]


@dataclass(frozen=True)
class EmbeddedSubtitleMetadata:
    """Provenance recorded for an extracted embedded subtitle stream."""

    provider: str
    media_path: str
    stream_index: int
    language: str | None
    title: str | None
    checksum: str
    path: str


class EmbeddedSubtitleSource:
    """Opt-in embedded subtitle extractor backed by ffprobe and ffmpeg."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        extract_with_ffmpeg: bool = False,
        extract_to: Path | str = Path("/data/subtitles/embedded"),
        languages: list[str] | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.enabled = enabled
        self.extract_with_ffmpeg = extract_with_ffmpeg
        self.extract_to = Path(extract_to)
        self.languages = languages or ["eng", "en"]
        self.runner = runner or _run_command

    def find(self, item: MediaItem) -> list[SubtitleCandidate]:
        return self.find_for_media(item)

    def find_for_media(self, item: MediaItem) -> list[SubtitleCandidate]:
        if not self.enabled or not self.extract_with_ffmpeg:
            return []
        result = self.runner(_ffprobe_command(item.path))
        if result.returncode != 0:
            raise ProviderError(f"ffprobe failed for embedded subtitles: {result.stderr.strip() or result.returncode}")
        streams = _subtitle_streams(result.stdout)
        candidates = [self._candidate_from_stream(item, stream) for stream in streams]
        return [candidate for candidate in candidates if candidate.language in self.languages or candidate.language is None]

    def fetch(self, candidate: Path | SubtitleCandidate | ProviderCandidate) -> Path:
        if isinstance(candidate, Path):
            return candidate
        if isinstance(candidate, SubtitleCandidate) and candidate.provider != PROVIDER_NAME:
            if candidate.path is None:
                raise ProviderError("Non-embedded candidate does not include a local path.")
            return candidate.path
        if not self.enabled or not self.extract_with_ffmpeg:
            raise ProviderError("Embedded subtitle extraction requested while provider is disabled.")
        provider_data = candidate.raw.get(PROVIDER_NAME) if isinstance(candidate, (SubtitleCandidate, ProviderCandidate)) else None
        if not isinstance(provider_data, Mapping):
            raise ProviderError("Embedded subtitle candidate is missing provider metadata.")
        media_path = Path(_required_string(provider_data, "media_path"))
        stream_index = int(provider_data.get("stream_index", -1))
        if stream_index < 0:
            raise ProviderError("Embedded subtitle candidate is missing a stream index.")
        target_path = Path(_required_string(provider_data, "path"))
        _ensure_under_directory(target_path, self.extract_to)
        if target_path.exists():
            return target_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner(_ffmpeg_command(media_path, stream_index, target_path))
        if result.returncode != 0:
            raise ProviderError(f"ffmpeg failed for embedded subtitles: {result.stderr.strip() or result.returncode}")
        if not target_path.exists():
            raise ProviderError("ffmpeg completed but did not create an extracted subtitle file.")
        checksum = hashlib.sha256(target_path.read_bytes()).hexdigest()
        metadata = EmbeddedSubtitleMetadata(
            provider=PROVIDER_NAME,
            media_path=str(media_path),
            stream_index=stream_index,
            language=_optional_string(provider_data.get("language")),
            title=_optional_string(provider_data.get("title")),
            checksum=checksum,
            path=str(target_path),
        )
        self._metadata_path(target_path).write_text(json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target_path

    def metadata_for(self, subtitle_path: Path | str) -> EmbeddedSubtitleMetadata | None:
        """Return extraction provenance for a cached embedded subtitle, if present."""

        metadata_path = self._metadata_path(Path(subtitle_path))
        if not metadata_path.exists():
            return None
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        return EmbeddedSubtitleMetadata(**data)

    def _candidate_from_stream(self, item: MediaItem, stream: Mapping[str, Any]) -> SubtitleCandidate:
        stream_index = int(stream.get("index", -1))
        if stream_index < 0:
            raise ProviderError("ffprobe returned a subtitle stream without an index.")
        tags = stream.get("tags") if isinstance(stream.get("tags"), Mapping) else {}
        language = _optional_string(tags.get("language"))
        title = _optional_string(tags.get("title"))
        target_path = self._cache_path(item.path, stream_index, language)
        raw = {
            PROVIDER_NAME: {
                "media_path": str(item.path),
                "stream_index": stream_index,
                "language": language,
                "title": title,
                "path": str(target_path),
                "cached": target_path.exists(),
                "provenance": "ffmpeg-extracted-embedded-subtitle",
            }
        }
        return SubtitleCandidate(
            path=target_path if target_path.exists() else None,
            uri=f"embedded://{_media_key(item.path)}/{stream_index}",
            language=language,
            provider=PROVIDER_NAME,
            score=1.0 if language in self.languages else 0.5,
            raw=raw,
        )

    def _cache_path(self, media_path: Path, stream_index: int, language: str | None) -> Path:
        language_part = _safe_part(language or "und")
        filename = f"{_safe_part(media_path.stem)}.{_media_key(media_path)[:12]}.stream-{stream_index}.{language_part}.srt"
        target = self.extract_to / filename
        _ensure_under_directory(target, self.extract_to)
        return target

    def _metadata_path(self, subtitle_path: Path) -> Path:
        return subtitle_path.with_suffix(f"{subtitle_path.suffix}.metadata.json")


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603 - opt-in local ffmpeg execution.


def _ffprobe_command(media_path: Path) -> list[str]:
    return [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index:stream_tags=language,title",
        "-of",
        "json",
        str(media_path),
    ]


def _ffmpeg_command(media_path: Path, stream_index: int, target_path: Path) -> list[str]:
    return ["ffmpeg", "-y", "-i", str(media_path), "-map", f"0:{stream_index}", "-c:s", "srt", str(target_path)]


def _subtitle_streams(ffprobe_stdout: str) -> list[Mapping[str, Any]]:
    try:
        data = json.loads(ffprobe_stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderError("ffprobe returned invalid JSON for embedded subtitles.") from exc
    streams = data.get("streams", []) if isinstance(data, Mapping) else []
    if not isinstance(streams, list):
        raise ProviderError("ffprobe returned an invalid streams payload for embedded subtitles.")
    return [stream for stream in streams if isinstance(stream, Mapping)]


def _media_key(media_path: Path) -> str:
    return hashlib.sha256(str(media_path.resolve()).encode("utf-8")).hexdigest()


def _safe_part(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value.strip())
    return safe.strip("-_") or "subtitle"


def _ensure_under_directory(path: Path, directory: Path) -> None:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise ProviderError("Embedded subtitle extraction target must stay under the configured cache directory.") from exc


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderError(f"Embedded subtitle candidate is missing {key}.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
