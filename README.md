# Media-Memory-MCP

Local-first MCP-oriented media search project.

## Implemented initial scope

- Python package layout under `src/media_memory`
- CLI entrypoint: `media-memory`
- SQLite metadata DB with FTS5 lexical search
- LanceDB vector-store abstraction (local fallback implementation)
- Filesystem media scanner and sidecar subtitle discovery (`.srt/.vtt/.ass/.ssa`)
- Subtitle parsing, normalization, and chunking
- Embedding abstraction with deterministic mock provider
- Hybrid lexical + vector search pipeline
- MCP tool surface:
  - `search_media`
  - `find_episode`
  - `find_scene`
  - `search_dialogue`
  - `get_scene_context`

## Quick usage

```bash
PYTHONPATH=src python -m media_memory.cli.main scan /path/to/media
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db ingest /path/to/media
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db search "i am your father"
PYTHONPATH=src python -m media_memory.cli.main --db .media_memory/media_memory.db mcp-call search_dialogue --params '{"query":"winter is coming"}'
```
