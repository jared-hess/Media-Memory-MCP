from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SUPPORTED_VECTOR_DB = "lancedb"
_SUPPORTED_SEARCH_WEIGHTS = {
    "search.lexical_weight": 0.45,
    "search.vector_weight": 0.45,
    "search.metadata_boost_weight": 0.10,
}


class AppConfig(BaseModel):
    name: str = "media-memory-mcp"
    environment: str = "local"
    data_dir: Path = Path("/data")
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    corpus_id: str = "local"


class McpConfig(BaseModel):
    transport: Literal["stdio"] = "stdio"
    allow_ingest_tools: bool = False
    read_only_resources: bool = True


class ApiConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765


class DiscordConfig(BaseModel):
    enabled: bool = False
    token: str | None = None
    api_base_url: str = "http://127.0.0.1:8765"
    default_limit: int = 3


class MediaSourceConfig(BaseModel):
    type: Literal["filesystem", "plex"]
    enabled: bool = False
    name: str | None = None
    roots: list[Path] = Field(default_factory=list)
    read_only: bool = True
    extensions: list[str] = Field(default_factory=list)
    url: str | None = None
    token: str | None = None
    libraries: list[str] = Field(default_factory=list)


class LocalSubtitleSourceConfig(BaseModel):
    enabled: bool = True
    roots: list[Path] = Field(default_factory=lambda: [Path("/media")])
    sidecar_extensions: list[str] = Field(default_factory=lambda: [".srt", ".vtt", ".ass", ".ssa"])
    read_only: bool = True


class EmbeddedSubtitleSourceConfig(BaseModel):
    enabled: bool = False
    extract_with_ffmpeg: bool = False
    extract_to: Path = Path("/data/subtitles/embedded")
    languages: list[str] = Field(default_factory=lambda: ["eng", "en"])


class OpenSubtitlesSourceConfig(BaseModel):
    enabled: bool = False
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["eng", "en"])
    hearing_impaired: bool = False
    daily_download_budget: int = 900
    min_match_confidence: float = 0.85
    cache_dir: Path = Path("/data/subtitles/opensubtitles")


class BazarrSourceConfig(BaseModel):
    enabled: bool = False
    url: str | None = None
    api_key: str | None = None
    api_enabled: bool = False
    roots: list[Path] = Field(default_factory=lambda: [Path("/bazarr")])
    sidecar_extensions: list[str] = Field(default_factory=lambda: [".srt", ".vtt", ".ass", ".ssa"])


class SubtitleSourcesConfig(BaseModel):
    local: LocalSubtitleSourceConfig = Field(default_factory=LocalSubtitleSourceConfig)
    embedded: EmbeddedSubtitleSourceConfig = Field(default_factory=EmbeddedSubtitleSourceConfig)
    opensubtitles: OpenSubtitlesSourceConfig = Field(default_factory=OpenSubtitlesSourceConfig)
    bazarr: BazarrSourceConfig = Field(default_factory=BazarrSourceConfig)


class MetadataConfig(BaseModel):
    prefer: list[Literal["plex", "filename", "tmdb", "tvmaze"]] = Field(
        default_factory=lambda: ["plex", "filename", "tmdb", "tvmaze"]
    )
    fetch_external: bool = False


class EmbeddingsConfig(BaseModel):
    provider: Literal["mock", "openai"] = "mock"
    model: str = "mock"
    batch_size: int = 128
    api_key: str | None = None
    dimensions: int = 16


class IndexConfig(BaseModel):
    metadata_db: Literal["sqlite"] = "sqlite"
    sqlite_path: Path = Path("/data/media-memory.sqlite")
    vector_db: Literal["memory", "lancedb", "disabled"] = "lancedb"
    vector_path: Path = Path("/data/vectors")


class SearchConfig(BaseModel):
    default_limit: int = 5
    max_limit: int = 50
    lexical_weight: float = 0.45
    vector_weight: float = 0.45
    metadata_boost_weight: float = 0.10
    cache_results: bool = True


class MediaMemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIA_MEMORY_", extra="forbid")

    app: AppConfig = Field(default_factory=AppConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    media_sources: list[MediaSourceConfig] = Field(
        default_factory=lambda: [
            MediaSourceConfig(
                type="filesystem",
                enabled=True,
                name="local-filesystem",
                roots=[Path("/media")],
                read_only=True,
                extensions=[".mkv", ".mp4", ".avi", ".mov"],
            ),
            MediaSourceConfig(type="plex", enabled=False),
        ]
    )
    subtitle_sources: SubtitleSourcesConfig = Field(default_factory=SubtitleSourcesConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


def _expand_env_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    return value


def load_config(path: str | Path) -> MediaMemoryConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}
    expanded_config = _expand_env_placeholders(raw_config)
    config = MediaMemoryConfig.model_validate(expanded_config)
    validate_supported_runtime_config(config)
    return config


def validate_supported_runtime_config(config: MediaMemoryConfig) -> None:
    """Fail fast for config fields that are not wired to runtime behavior yet."""

    if config.index.vector_db != _SUPPORTED_VECTOR_DB:
        raise ValueError(
            f"Unsupported index.vector_db value {config.index.vector_db!r}; "
            f"only {_SUPPORTED_VECTOR_DB!r} is currently implemented."
        )

    search_values = {
        "search.lexical_weight": config.search.lexical_weight,
        "search.vector_weight": config.search.vector_weight,
        "search.metadata_boost_weight": config.search.metadata_boost_weight,
    }
    for field_name, expected_value in _SUPPORTED_SEARCH_WEIGHTS.items():
        configured_value = search_values[field_name]
        if configured_value != expected_value:
            raise ValueError(
                f"Unsupported {field_name} value {configured_value!r}; "
                f"only {expected_value!r} is currently implemented."
            )

    if config.metadata.fetch_external:
        raise ValueError(
            "Unsupported metadata.fetch_external value True; external metadata fetching "
            "requires an implemented source selection path."
        )


__all__ = ["MediaMemoryConfig", "load_config", "validate_supported_runtime_config"]
