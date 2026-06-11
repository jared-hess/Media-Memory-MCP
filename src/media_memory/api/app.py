from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from media_memory.config import MediaMemoryConfig
from media_memory.mcp_server.tools import create_services

from .routes import (
    health_payload,
    rest_ingest_payload,
    rest_media_payload,
    rest_scene_payload,
    rest_search_payload,
    status_payload,
)

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class SimpleASGIApp:
    """Small optional ASGI app for local REST usage without a required web framework."""

    def __init__(
        self, config_path: Path | str | None = None, *, config: MediaMemoryConfig | None = None
    ):
        self.config_path = config_path
        self.config = config

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await _send_json(send, 500, {"error": "Unsupported ASGI scope"})
            return

        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/"))
        raw_query = scope.get("query_string", b"")
        query = parse_qs(
            raw_query.decode("utf-8") if isinstance(raw_query, bytes) else str(raw_query)
        )

        try:
            status_code, payload = await self._dispatch(method, path, query, receive)
        except PermissionError as exc:
            status_code, payload = 403, {"error": str(exc)}
        except ValueError as exc:
            status_code, payload = 400, {"error": str(exc)}

        await _send_json(send, status_code, payload)

    async def _dispatch(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        receive: Receive,
    ) -> tuple[int, dict[str, object]]:
        if method == "GET" and path == "/health":
            return 200, health_payload()

        services = create_services(self.config_path, config=self.config)
        try:
            if method == "GET" and path == "/status":
                return 200, status_payload(services)
            if method == "POST" and path == "/search":
                return 200, rest_search_payload(services, await _read_json(receive))
            if method == "POST" and path == "/ingest":
                return 200, rest_ingest_payload(services)
            if method == "GET" and path.startswith("/media/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) == 2:
                    return 200, rest_media_payload(services, parts[1])
                if len(parts) == 3 and parts[2] == "scene":
                    return 200, rest_scene_payload(
                        services, parts[1], _first_query_value(query, "start")
                    )
            return 404, {"error": "Not found"}
        finally:
            services.close()


def create_app(
    config_path: Path | str | None = None,
    *,
    config: MediaMemoryConfig | None = None,
) -> SimpleASGIApp:
    """Create the optional local REST API app."""

    return SimpleASGIApp(config_path, config=config)


async def _read_json(receive: Receive) -> dict[str, Any]:
    chunks: list[bytes] = []
    more_body = True
    while more_body:
        message = await receive()
        chunks.append(message.get("body", b""))
        more_body = bool(message.get("more_body", False))
    if not chunks or not b"".join(chunks):
        return {}
    value = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


async def _send_json(send: Send, status_code: int, payload: Mapping[str, object]) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _first_query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    return values[0]


app = create_app()

__all__ = ["SimpleASGIApp", "app", "create_app"]
