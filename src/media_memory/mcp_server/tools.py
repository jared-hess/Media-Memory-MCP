from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from media_memory.config import MediaMemoryConfig, load_config
from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider, EmbeddingProviderConfigError, MockEmbeddingProvider, OpenAIEmbeddingProvider
from media_memory.core.models import SearchFilters
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceVectorStore, VectorStore
from media_memory.ingest.indexer import IngestService
from media_memory.media_sources.filesystem import FilesystemMediaSource, MEDIA_EXTENSIONS


DEFAULT_CONFIG_PATH = Path("config.example.yaml")


@dataclass
class McpServices:
    config: MediaMemoryConfig
    db: MediaMemoryDB
    search: SearchService
    ingest: IngestService

    def close(self) -> None:
        self.db.close()


class LocalToolDispatcher:
    """Backward-compatible local tool caller used by hidden ``mcp-call``."""

    def __init__(self, services: McpServices):
        self.services = services

    def search_media(
        self,
        query: str,
        limit: int | None = None,
        kind: str | None = None,
        show: str | None = None,
    ) -> dict[str, object]:
        return search_media_payload(self.services, query=query, limit=limit, kind=kind, show=show)

    def find_episode(
        self,
        query: str,
        season: int | None = None,
        episode: int | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return find_episode_payload(
            self.services,
            query=query,
            season=season,
            episode=episode,
            limit=limit,
        )

    def find_scene(
        self,
        query: str,
        media_path: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return find_scene_payload(self.services, query=query, media_path=media_path, limit=limit)

    def search_dialogue(self, query: str, limit: int | None = None) -> dict[str, object]:
        return search_dialogue_payload(self.services, query=query, limit=limit)

    def get_media(
        self,
        media_id: int | str | None = None,
        media_path: str | None = None,
    ) -> dict[str, object]:
        return get_media_payload(self.services, media_id=media_id, media_path=media_path)

    def get_scene_context(self, chunk_id: int | str, window: int = 2) -> dict[str, object]:
        return get_scene_context_payload(self.services, chunk_id=chunk_id, window=window)

    def ingest_library(self) -> dict[str, object]:
        return ingest_library_payload(self.services)

    def call_tool(self, tool_name: str, **kwargs: object) -> dict[str, object]:
        dispatch = {
            "search_media": self.search_media,
            "find_episode": self.find_episode,
            "find_scene": self.find_scene,
            "search_dialogue": self.search_dialogue,
            "get_media": self.get_media,
            "get_scene_context": self.get_scene_context,
        }
        if self.services.config.mcp.allow_ingest_tools:
            dispatch["ingest_library"] = self.ingest_library
        if tool_name not in dispatch:
            raise ValueError(f"Unknown tool: {tool_name}. Available tools: {', '.join(sorted(dispatch))}")
        return dispatch[tool_name](**kwargs)


def create_services(
    config_path: Path | str | None = None,
    *,
    config: MediaMemoryConfig | None = None,
) -> McpServices:
    """Build MCP services from the same local config primitives as the CLI."""

    loaded_config = config or _load_config(config_path)
    db = MediaMemoryDB(loaded_config.index.sqlite_path)
    db.init_schema()
    embeddings = _build_embeddings(loaded_config)
    vectors = _build_vectors(db, embeddings, loaded_config)
    return McpServices(
        config=loaded_config,
        db=db,
        search=SearchService(db, embeddings, vectors, use_cache=loaded_config.search.cache_results),
        ingest=IngestService(db, embeddings, vectors),
    )


def create_legacy_server(
    config_path: Path | str | None = None,
    *,
    config: MediaMemoryConfig | None = None,
) -> LocalToolDispatcher:
    return LocalToolDispatcher(create_services(config_path, config=config))


def register_tools(app: Any, services: McpServices) -> None:
    """Register Media Memory tools on a FastMCP app."""

    @app.tool()
    def search_media(
        query: str,
        limit: int | None = None,
        kind: str | None = None,
        show: str | None = None,
    ) -> dict[str, object]:
        """Search indexed media and return SearchResult-shaped dictionaries."""

        return search_media_payload(services, query=query, limit=limit, kind=kind, show=show)

    @app.tool()
    def find_episode(
        query: str,
        season: int | None = None,
        episode: int | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        """Find episode media, optionally constrained by season/episode numbers."""

        return find_episode_payload(
            services,
            query=query,
            season=season,
            episode=episode,
            limit=limit,
        )

    @app.tool()
    def find_scene(
        query: str,
        media_path: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        """Find timestamped scenes for a text query."""

        return find_scene_payload(services, query=query, media_path=media_path, limit=limit)

    @app.tool()
    def search_dialogue(query: str, limit: int | None = None) -> dict[str, object]:
        """Search subtitle dialogue with timestamped evidence."""

        return search_dialogue_payload(services, query=query, limit=limit)

    @app.tool()
    def get_media(media_id: int | str | None = None, media_path: str | None = None) -> dict[str, object]:
        """Return one indexed media item by ID or path."""

        return get_media_payload(services, media_id=media_id, media_path=media_path)

    @app.tool()
    def get_scene_context(chunk_id: int | str, window: int = 2) -> dict[str, object]:
        """Return before/current/after context for a subtitle chunk."""

        return get_scene_context_payload(services, chunk_id=chunk_id, window=window)

    if not services.config.mcp.allow_ingest_tools:
        return

    @app.tool()
    def ingest_library() -> dict[str, object]:
        """Index all enabled local filesystem roots from config."""

        return ingest_library_payload(services)


def search_media_payload(
    services: McpServices,
    *,
    query: str,
    limit: int | None = None,
    kind: str | None = None,
    show: str | None = None,
) -> dict[str, object]:
    result_limit = _safe_limit(services.config, limit)
    filters = SearchFilters(corpus_id=services.config.app.corpus_id, kind=kind, show=show, show_title=show, limit=result_limit)
    results = services.search.search_media(query, limit=result_limit, filters=filters)
    return {"query": query, "results": [item.to_dict() for item in results]}


def find_episode_payload(
    services: McpServices,
    *,
    query: str,
    season: int | None = None,
    episode: int | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    result_limit = _safe_limit(services.config, limit)
    filters = SearchFilters(corpus_id=services.config.app.corpus_id)
    results = services.search.find_episode(query, season=season, episode=episode, limit=result_limit, filters=filters)
    return {"query": query, "results": [item.to_dict() for item in results]}


def find_scene_payload(
    services: McpServices,
    *,
    query: str,
    media_path: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    result_limit = _safe_limit(services.config, limit)
    filters = SearchFilters(corpus_id=services.config.app.corpus_id, media_path=media_path)
    return {
        "query": query,
        "results": services.search.find_scene(query, filters=filters, limit=result_limit),
    }


def search_dialogue_payload(
    services: McpServices,
    *,
    query: str,
    limit: int | None = None,
) -> dict[str, object]:
    result_limit = _safe_limit(services.config, limit)
    filters = SearchFilters(corpus_id=services.config.app.corpus_id)
    return {
        "query": query,
        "results": services.search.search_dialogue(query, limit=result_limit, filters=filters),
    }


def get_media_payload(
    services: McpServices,
    *,
    media_id: int | str | None = None,
    media_path: str | None = None,
) -> dict[str, object]:
    return {
        "result": services.search.get_media(
            media_id=media_id,
            media_path=media_path,
            corpus_id=services.config.app.corpus_id,
        )
    }


def get_scene_context_payload(
    services: McpServices,
    *,
    chunk_id: int | str,
    window: int = 2,
) -> dict[str, object]:
    return {"result": services.search.get_scene_context(chunk_id=chunk_id, window=window)}


def ingest_library_payload(services: McpServices) -> dict[str, object]:
    if not services.config.mcp.allow_ingest_tools:
        raise PermissionError("ingest_library is disabled unless mcp.allow_ingest_tools=true")
    items = []
    for source in services.config.media_sources:
        if source.type != "filesystem" or not source.enabled:
            continue
        extensions = source.extensions or sorted(MEDIA_EXTENSIONS)
        items.extend(FilesystemMediaSource(roots=source.roots, extensions=extensions).scan())
    stats = services.ingest.ingest_media_items(items)
    return {"scanned": len(items), "stats": stats}


def _load_config(config_path: Path | str | None) -> MediaMemoryConfig:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if path.exists():
        return load_config(path)
    if path != DEFAULT_CONFIG_PATH and path != DEFAULT_CONFIG_PATH.resolve():
        raise typer.BadParameter(f"Config file does not exist: {path}")
    return MediaMemoryConfig()


def _build_embeddings(config: MediaMemoryConfig) -> EmbeddingProvider:
    if config.embeddings.provider == "mock":
        return MockEmbeddingProvider(dims=config.embeddings.dimensions)
    try:
        return OpenAIEmbeddingProvider(config.embeddings.api_key, dimensions=config.embeddings.dimensions)
    except EmbeddingProviderConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _build_vectors(db: MediaMemoryDB, embeddings: EmbeddingProvider, config: MediaMemoryConfig) -> VectorStore:
    vectors = LanceVectorStore(config.index.vector_path)
    vectors.rebuild_from_chunks(db, embeddings)
    return vectors


def _safe_limit(config: MediaMemoryConfig, limit: int | None) -> int:
    requested = limit or config.search.default_limit
    return max(1, min(int(requested), config.search.max_limit))


__all__ = [
    "LocalToolDispatcher",
    "McpServices",
    "create_legacy_server",
    "create_services",
    "register_tools",
]
