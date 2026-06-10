# MCP tools and resources

The current scaffold exposes local MCP-style tool calls through the existing CLI path. A FastMCP stdio server is planned for a later task.

## MVP search tools

The intended MVP search surface is:

- `search_media`: general media search.
- `find_episode`: locate an episode by title or episode metadata.
- `find_scene`: find scene-like subtitle matches.
- `search_dialogue`: search spoken dialogue text.
- `get_media`: fetch media metadata by identifier, planned with the durable model work.
- `get_scene_context`: retrieve nearby subtitle context around a match.

## Ingest safety

`ingest_library` is intentionally not enabled by default. It may only be exposed when `mcp.allow_ingest_tools=true` after later MCP server work implements the tool.

## Resources

Resources should be read-only by default and backed by the same SQLite/search services used by the CLI. Configuration uses `mcp.read_only_resources=true` and `mcp.transport=stdio` to document that posture.
