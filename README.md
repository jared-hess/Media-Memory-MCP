# Media-Memory-MCP

Local-first MCP-oriented media search project.

This repository is currently an MVP scaffold. The safe default path is local filesystem media, local sidecar subtitles, SQLite/FTS search, deterministic mock embeddings, and a stdio MCP server. Embedded subtitle extraction, Plex, OpenSubtitles, Bazarr provider APIs, OpenAI embeddings, REST, Discord, and hosted mode remain disabled unless explicitly enabled and gated in config.

## Implemented initial scope

- Python package layout under `src/media_memory`
- CLI entrypoint: `media-memory`
- SQLite metadata DB with FTS5 lexical search
- LanceDB vector-store abstraction (local fallback implementation)
- Filesystem media scanner, sidecar subtitle discovery (`.srt/.vtt/.ass/.ssa`), and opt-in embedded/Bazarr filesystem subtitle adapters
- Subtitle parsing, normalization, and chunking
- Embedding abstraction with deterministic mock provider
- Hybrid lexical + vector search pipeline
- MCP tool surface:
  - `search_media`
  - `find_episode`
  - `find_scene`
  - `search_dialogue`
  - `get_scene_context`
- Optional REST ASGI app under `media_memory.api`, disabled by default and not used as the Docker command
- Optional Discord bot command facade under `media_memory.discord_bot`, disabled by default and backed only by REST API calls

## Quick usage

```bash
PYTHONPATH=src python -m media_memory.cli.main scan /path/to/media
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db ingest /path/to/media
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db search "i am your father"
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db mcp-call search_dialogue --params '{"query":"winter is coming"}'
```

## Configuration

Start from `config.example.yaml` and `.env.example`. The example config follows the spec-shaped sections future tasks consume: list-based `media_sources`, local/embedded/OpenSubtitles/Bazarr subtitle sections, `metadata.prefer` provider order, `/data/media-memory.sqlite`, `/data/vectors`, mock embeddings, and the default `local` corpus:

```bash
uv run python -c "from media_memory.config import load_config; print(load_config('config.example.yaml').mcp.allow_ingest_tools)"
```

Environment placeholders such as `${PLEX_TOKEN}`, `${OPENAI_API_KEY}`, `${OPENSUBTITLES_API_KEY}`, `${BAZARR_API_KEY}`, and `${DISCORD_BOT_TOKEN}` are resolved at load time when set, but the examples intentionally contain no credentials and all external providers remain disabled by default. `subtitle_sources.embedded` only invokes `ffprobe`/`ffmpeg` when both `enabled` and `extract_with_ffmpeg` are true, and extracted subtitles are written under `extract_to` rather than beside media files. `subtitle_sources.bazarr` can read subtitles that Bazarr has already placed beside media or under configured read-only roots; Bazarr API calls remain off unless `api_enabled` is explicitly true. The Discord bot stays disabled unless `discord.enabled: true`, a token is configured, and a local REST API URL is provided; its handlers call `/search` rather than core search or database services.

## Optional Discord bot

`media_memory.discord_bot` provides command handlers for `/episode show query`, `/scene query`, `/quote query`, and `/movie query`. The handlers use the REST `/search` endpoint only, format concise evidence snippets with timestamps when available, and return safe no-result/error messages. Runtime Discord wiring is optional and requires installing `discord.py` yourself; normal tests and local MCP usage do not require a Discord token or package.

## Optional REST API

The REST app is available as `media_memory.api:create_app` / `media_memory.api:app` for local ASGI runners, but `api.enabled` defaults to `false` and the Docker/home-lab default remains the stdio MCP server. Endpoints are intentionally thin wrappers over the same MCP/core services: `GET /health`, `GET /status`, `POST /search`, `POST /ingest`, `GET /media/{id}`, and `GET /media/{id}/scene?start=123`. `POST /ingest` uses the same safety gate as MCP and returns forbidden unless `mcp.allow_ingest_tools: true` is explicitly configured.

## Docker home-lab usage

The image installs the package and Debian `ffmpeg`, which also provides `ffprobe` for optional embedded subtitle extraction when enabled:

```bash
docker build -t media-memory-mcp:test .
```

For compose, create local host directories and place a safe config at `./config/config.yaml` (for example, copy `config.example.yaml` and keep secrets out of the file unless you intentionally enable a provider):

```bash
mkdir -p config data media bazarr
cp config.example.yaml config/config.yaml
docker compose config
docker compose up media-memory
```

`docker-compose.yml` runs `media-memory mcp --config /config/config.yaml` over stdio by default. It mounts `/config` read-only, `/media` read-only, optional `/bazarr` read-only, and `/data` read-write for SQLite, vectors, caches, and derived subtitle files. Override `MEDIA_LIBRARY_PATH` or `BAZARR_SUBTITLE_PATH` to point at existing host directories; do not mount media read-write.

Operational status is available from the CLI and is safe to emit as JSON because it reports provider enablement flags and model/provider names, not tokens or service URLs:

```bash
media-memory status --config config.example.yaml --json
```

## Documentation

- `docs/home-lab-spec.md`: local deployment assumptions and safe mount defaults.
- `docs/mcp-tools.md`: current/planned MCP tool surface and ingest safety.
- `docs/data-model.md`: current scaffold concepts and planned corpus-aware model boundaries.
- `docs/hosted-architecture.md`: deferred hosted architecture direction.
