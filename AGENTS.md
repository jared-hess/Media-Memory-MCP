# Media Memory MCP Agent Notes

## Current task boundaries

- Keep the project local-first and safe for home-lab use.
- Default to read-only media/config mounts and read-write app data.
- Do not enable ingest MCP tools unless `mcp.allow_ingest_tools` is explicitly `true`.
- Do not enable Plex, OpenSubtitles, Bazarr, OpenAI, REST, Discord, Docker, or hosted services by default.
- Preserve the existing argparse CLI until the planned Typer CLI task.

## Configuration

- Use `config.example.yaml` as the documented shape for local development.
- Use `.env.example` only as a placeholder template; never store real tokens in examples or docs.
- The default corpus is `local` via `app.corpus_id`.
- The default embedding provider and model are both `mock`.
