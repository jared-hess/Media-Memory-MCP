# MCP tools and resources

The project exposes a local FastMCP stdio server through `media-memory mcp`. Tools and resources use the same SQLite/search services as the CLI.

## MVP search tools

The intended MVP search surface is:

- `search_media`: general media search.
- `find_episode`: locate an episode by title or episode metadata.
- `find_scene`: find scene-like subtitle matches.
- `search_dialogue`: search spoken dialogue text.
- `get_media`: fetch media metadata by identifier or media path.
- `get_scene_context`: retrieve nearby subtitle context around a match.

## Ingest safety

`ingest_library` is implemented but intentionally hidden by default. It is only registered when `mcp.allow_ingest_tools=true`, so normal MCP clients get read/search tools without mutation access.

## Resources

Resources should be read-only by default and backed by the same SQLite/search services used by the CLI. Configuration uses `mcp.read_only_resources=true` and `mcp.transport=stdio` to document that posture.
