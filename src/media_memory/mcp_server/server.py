from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from media_memory.config import MediaMemoryConfig
from media_memory.mcp_server.resources import register_resources
from media_memory.mcp_server.tools import create_services, register_tools


def create_server(config_path: Path | str | None = None) -> FastMCP:
    """Create the local-first FastMCP server for Media Memory."""

    services = create_services(config_path)
    app = FastMCP(
        "media-memory",
        instructions="Search a local Media Memory SQLite index over stdio.",
    )
    register_tools(app, services)
    register_resources(app, services)
    return app


def run_server(config_path: Path | str | None = None, *, config: MediaMemoryConfig | None = None) -> None:
    """Run the MCP server over the configured safe transport."""

    services = create_services(config_path, config=config)
    app = FastMCP(
        "media-memory",
        instructions="Search a local Media Memory SQLite index over stdio.",
    )
    register_tools(app, services)
    register_resources(app, services)
    app.run(transport=services.config.mcp.transport)


__all__ = ["create_server", "run_server"]
