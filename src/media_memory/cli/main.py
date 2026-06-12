from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Generator

import typer

from media_memory.config import (
    EmbeddingsConfig,
    MediaMemoryConfig,
    load_config,
    validate_supported_runtime_config,
)
from media_memory.core.db import MediaMemoryDB, SCHEMA_VERSION
from media_memory.core.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderConfigError,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from media_memory.core.models import MediaItem, SearchFilters
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceVectorStore, VectorStore
from media_memory.ingest.indexer import IngestService
from media_memory.ingest.scanner import scan_media
from media_memory.media_sources.filesystem import FilesystemMediaSource, MEDIA_EXTENSIONS
from media_memory.mcp_server.server import run_server
from media_memory.mcp_server.tools import create_legacy_server

app = typer.Typer(
    name="media-memory",
    help="Local-first media indexing and search CLI.",
    no_args_is_help=True,
)

ConfigOption = Annotated[
    Path,
    typer.Option(
        "--config",
        help="Path to the media-memory YAML config file.",
        exists=False,
        dir_okay=False,
        resolve_path=True,
    ),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Emit stable JSON output.")]

DEFAULT_CONFIG_PATH = Path("config.example.yaml")


@dataclass
class Services:
    db: MediaMemoryDB
    search: SearchService
    ingest: IngestService


def main() -> None:
    app()


def _load_cli_config(config_path: Path) -> MediaMemoryConfig:
    try:
        if config_path.exists():
            return load_config(config_path)
        if config_path != DEFAULT_CONFIG_PATH.resolve() and config_path != DEFAULT_CONFIG_PATH:
            raise typer.BadParameter(f"Config file does not exist: {config_path}")
        config = MediaMemoryConfig()
        validate_supported_runtime_config(config)
        return config
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _db_path(config: MediaMemoryConfig) -> Path:
    return config.index.sqlite_path


def _build_embeddings(config: MediaMemoryConfig) -> EmbeddingProvider:
    if config.embeddings.provider == "mock":
        return MockEmbeddingProvider(dims=config.embeddings.dimensions)
    try:
        return OpenAIEmbeddingProvider(
            config.embeddings.api_key,
            model=_openai_embedding_model(config),
            dimensions=config.embeddings.dimensions,
        )
    except EmbeddingProviderConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _openai_embedding_model(config: MediaMemoryConfig) -> str:
    if config.embeddings.model == EmbeddingsConfig().model:
        return OpenAIEmbeddingProvider.MODEL
    return config.embeddings.model


def _build_vectors(
    db: MediaMemoryDB, embeddings: EmbeddingProvider, config: MediaMemoryConfig
) -> VectorStore:
    vectors = LanceVectorStore(config.index.vector_path)
    vectors.rebuild_from_chunks(db, embeddings)
    return vectors


@contextmanager
def _services(config_path: Path) -> Generator[Services, None, None]:
    config = _load_cli_config(config_path)
    db = MediaMemoryDB(_db_path(config))
    db.init_schema()
    embeddings = _build_embeddings(config)
    vectors = _build_vectors(db, embeddings, config)
    try:
        yield Services(
            db=db,
            search=SearchService(db, embeddings, vectors, use_cache=config.search.cache_results),
            ingest=IngestService(db, embeddings, vectors),
        )
    finally:
        db.close()


def _json_print(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _human_or_json(payload: object, *, json_output: bool, human: str) -> None:
    if json_output:
        _json_print(payload)
        return
    typer.echo(human)


def _media_items_for_path(path: Path) -> list[MediaItem]:
    return scan_media(path)


def _media_items_for_config(config: MediaMemoryConfig) -> list[MediaItem]:
    items: list[MediaItem] = []
    for source in config.media_sources:
        if source.type != "filesystem" or not source.enabled:
            continue
        extensions = source.extensions or sorted(MEDIA_EXTENSIONS)
        items.extend(FilesystemMediaSource(roots=source.roots, extensions=extensions).scan())
    return items


def _scan_payload(items: list[MediaItem]) -> list[dict[str, object]]:
    return [item.to_dict() for item in items]


def _download_providers_enabled(config: MediaMemoryConfig) -> bool:
    return config.subtitle_sources.opensubtitles.enabled or config.subtitle_sources.bazarr.enabled


def _guard_download_missing_subtitles(config: MediaMemoryConfig, requested: bool) -> None:
    if not requested:
        return
    if _download_providers_enabled(config):
        raise typer.BadParameter(
            "Subtitle provider downloads are explicitly enabled in config, but provider implementations are deferred."
        )
    typer.secho(
        "Skipping subtitle downloads: --download-missing-subtitles was set, but no subtitle provider is enabled.",
        err=True,
        fg=typer.colors.YELLOW,
    )


def _provider_enablement(config: MediaMemoryConfig) -> dict[str, object]:
    filesystem_enabled = any(
        source.type == "filesystem" and source.enabled for source in config.media_sources
    )
    plex_enabled = any(source.type == "plex" and source.enabled for source in config.media_sources)
    return {
        "media_sources": {
            "filesystem": filesystem_enabled,
            "plex": plex_enabled,
        },
        "subtitle_sources": {
            "local": config.subtitle_sources.local.enabled,
            "embedded": config.subtitle_sources.embedded.enabled,
            "opensubtitles": config.subtitle_sources.opensubtitles.enabled,
            "bazarr": config.subtitle_sources.bazarr.enabled,
        },
        "metadata": {
            "fetch_external": config.metadata.fetch_external,
            "preferred": list(config.metadata.prefer),
        },
        "embeddings": {
            "provider": config.embeddings.provider,
            "model": config.embeddings.model,
        },
        "mcp": {
            "transport": config.mcp.transport,
            "allow_ingest_tools": config.mcp.allow_ingest_tools,
            "read_only_resources": config.mcp.read_only_resources,
        },
    }


@app.command("init")
def init_config(
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing config file.")
    ] = False,
    json_output: JsonOption = False,
) -> None:
    """Create a local config file with safe defaults."""

    if config.exists() and not force:
        raise typer.BadParameter(f"Config file already exists: {config}")
    config.parent.mkdir(parents=True, exist_ok=True)
    payload = MediaMemoryConfig().model_dump(mode="json")
    import yaml

    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    output = {"config": str(config), "created": True}
    _human_or_json(output, json_output=json_output, human=f"Created config at {config}")


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="Local media root to scan.")],
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    json_output: JsonOption = False,
) -> None:
    """Discover local media files without indexing them."""

    _load_cli_config(config)
    items = _media_items_for_path(path)
    payload = _scan_payload(items)
    _human_or_json(
        payload, json_output=json_output, human=f"Discovered {len(items)} media item(s)."
    )


@app.command()
def ingest(
    path: Annotated[Path | None, typer.Argument(help="Local media root to index.")] = None,
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    all_sources: Annotated[
        bool, typer.Option("--all", help="Index all enabled filesystem roots from config.")
    ] = False,
    download_missing_subtitles: Annotated[
        bool,
        typer.Option(
            "--download-missing-subtitles",
            help="Request missing subtitle downloads when an explicit provider is enabled.",
        ),
    ] = False,
    json_output: JsonOption = False,
) -> None:
    """Index local media and sidecar subtitles."""

    loaded_config = _load_cli_config(config)
    _guard_download_missing_subtitles(loaded_config, download_missing_subtitles)
    if all_sources:
        items = _media_items_for_config(loaded_config)
    elif path is not None:
        items = _media_items_for_path(path)
    else:
        raise typer.BadParameter("Provide PATH or use --all.")

    with _services(config) as services:
        stats = services.ingest.ingest_media_items(items)
    output = {"scanned": len(items), "stats": stats}
    _human_or_json(output, json_output=json_output, human=f"Indexed {len(items)} media item(s).")


@app.command()
def reindex(
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    media_id: Annotated[
        str | None, typer.Option("--media-id", help="Media item ID to reindex.")
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Rebuild the SQLite FTS index."""

    with _services(config) as services:
        if media_id is not None:
            row = services.db.conn.execute(
                "SELECT id FROM media_items WHERE id = ?", (media_id,)
            ).fetchone()
            if row is None:
                raise typer.BadParameter(f"Unknown media ID: {media_id}")
        services.db.rebuild_fts_index()
        chunks = services.db.count_chunks()
    output = {
        "media_id": media_id,
        "reindexed_chunks": chunks,
        "scope": "media" if media_id else "all",
    }
    _human_or_json(
        output, json_output=json_output, human=f"Rebuilt FTS index for {chunks} chunk(s)."
    )


@app.command()
def status(config: ConfigOption = DEFAULT_CONFIG_PATH, json_output: JsonOption = False) -> None:
    """Report database, ingest job, and index status."""

    loaded_config = _load_cli_config(config)
    with _services(config) as services:
        job_rows = services.db.list_ingest_jobs()
        jobs_by_status: dict[str, int] = {}
        pending_jobs = 0
        failed_jobs = 0
        for row in job_rows:
            status_name = str(row["status"])
            jobs_by_status[status_name] = jobs_by_status.get(status_name, 0) + 1
            if status_name == "failed":
                failed_jobs += 1
            elif row["completed_at"] is None:
                pending_jobs += 1
        chunk_count = services.db.count_chunks()
        output = {
            "db": {
                "path": str(_db_path(loaded_config)),
                "exists": _db_path(loaded_config).exists(),
                "schema_version": SCHEMA_VERSION,
            },
            "corpus": {
                "configured": loaded_config.app.corpus_id,
                "count": services.db.count_corpora(),
            },
            "jobs": {
                "total": len(job_rows),
                "pending": pending_jobs,
                "failed": failed_jobs,
                "by_status": jobs_by_status,
            },
            "index": {
                "state": "ready",
                "chunks": chunk_count,
                "fts": "ready",
                "vector_db": loaded_config.index.vector_db,
                "vector_path": str(loaded_config.index.vector_path),
            },
            "counts": {
                "media_items": services.db.count_media_items(),
                "documents": services.db.count_documents(),
                "chunks": chunk_count,
            },
            "providers": _provider_enablement(loaded_config),
        }
    _human_or_json(output, json_output=json_output, human="Media Memory status ready.")


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    show: Annotated[str | None, typer.Option("--show", help="Filter by show title.")] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Filter by media kind.")] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", min=1, help="Maximum result count.")
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Search indexed subtitle text."""

    loaded_config = _load_cli_config(config)
    result_limit = min(limit or loaded_config.search.default_limit, loaded_config.search.max_limit)
    filters = SearchFilters(kind=kind, show=show, show_title=show, limit=result_limit)
    with _services(config) as services:
        results = services.search.search_media(query, limit=result_limit, filters=filters)
    payload = [result.to_dict() for result in results]
    if json_output:
        _json_print(payload)
        return
    if not results:
        typer.echo("No results.")
        return
    for result in results:
        typer.echo(f"{result.title} ({result.media_path}) score={result.combined_score:.3f}")


@app.command()
def mcp(config: ConfigOption = DEFAULT_CONFIG_PATH, json_output: JsonOption = False) -> None:
    """Run the local MCP server over stdio by default."""

    loaded_config = _load_cli_config(config)
    if json_output:
        _json_print(
            {
                "transport": loaded_config.mcp.transport,
                "allow_ingest_tools": loaded_config.mcp.allow_ingest_tools,
                "status": "ready",
            }
        )
        return
    run_server(config, config=loaded_config)


@app.command("mcp-call", hidden=True)
def mcp_call(
    tool_name: Annotated[
        str,
        typer.Argument(help="Legacy local tool name."),
    ],
    config: ConfigOption = DEFAULT_CONFIG_PATH,
    params: Annotated[str, typer.Option("--params", help="JSON object of tool params.")] = "{}",
) -> None:
    """Backward-compatible local MCP tool caller."""

    loaded_config = _load_cli_config(config)
    server = create_legacy_server(config, config=loaded_config)
    try:
        _json_print(server.call_tool(tool_name, **json.loads(params)))
    finally:
        server.services.close()


if __name__ == "__main__":
    main()
