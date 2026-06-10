# Home-lab deployment spec

Media Memory MCP is currently a local-first MVP scaffold for indexing personal media subtitles and searching them from a local machine or home server.

## Safe defaults

- `mcp.allow_ingest_tools` defaults to `false`, so remote MCP clients cannot trigger ingestion unless the operator opts in.
- `embeddings.provider` defaults to `mock`, avoiding external network calls and provider credentials.
- Embedded subtitle extraction defaults to disabled and never writes into media mounts; extracted files go under the configured `/data` cache when enabled.
- `app.corpus_id` defaults to `local`, giving future durable records an obvious local corpus boundary.
- `app.data_dir` defaults to `/data`, matching the expected read-write app data mount.
- Filesystem media roots are treated as read-only inputs.
- `index.sqlite_path` defaults to `/data/media-memory.sqlite`, and `index.vector_path` defaults to `/data/vectors` for rebuildable LanceDB vector data.

## Expected mounts

For containerized home-lab deployment, mount paths follow this model:

- `/media`: read-only media library mount.
- `/config`: read-only configuration mount containing the YAML config and environment file.
- `/data`: read-write application data mount for SQLite, derived indexes, logs, and caches.
- `/bazarr`: optional read-only subtitle export mount for future Bazarr integration work.

The compose service runs `media-memory mcp --config /config/config.yaml` over stdio. It does not publish an HTTP MCP port, and media/config/Bazarr inputs stay read-only while `/data` remains writable.

## Operational status checks

Use `media-memory status --json` to check the configured DB path, distinct corpus count, media/document/chunk counts, FTS/vector index state, pending/failed ingest jobs, and config-safe provider enablement. Status output must not include secrets, provider tokens, usernames, passwords, or external service URLs.

## Provider posture

Local sidecar subtitles are enabled by default through `subtitle_sources.local`. Embedded subtitle extraction is available but disabled by default; when enabled with `extract_with_ffmpeg=true`, it uses `ffprobe`/`ffmpeg` and writes extracted subtitles only under `subtitle_sources.embedded.extract_to`. Bazarr filesystem mode is available for subtitles already placed beside media or exported under read-only `subtitle_sources.bazarr.roots`, while Bazarr API mode remains disabled unless `api_enabled=true` and an API client is explicitly configured. Plex, OpenSubtitles, Bazarr API, OpenAI, REST, Discord, and hosted integrations stay disabled unless explicitly enabled and gated.
