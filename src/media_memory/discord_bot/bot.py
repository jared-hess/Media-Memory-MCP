from __future__ import annotations

# pyright: reportUnusedFunction=false

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib import error, request

from media_memory.config import MediaMemoryConfig


class RestClientError(RuntimeError):
    """Raised when the optional Discord bot cannot read from the REST API."""


class SearchRestClient(Protocol):
    async def search(
        self,
        *,
        query: str,
        limit: int | None = None,
        kind: str | None = None,
        show: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DiscordBotSettings:
    enabled: bool = False
    token: str | None = None
    api_base_url: str = "http://127.0.0.1:8765"
    default_limit: int = 3

    @property
    def is_ready(self) -> bool:
        return self.enabled and bool(self.token) and bool(self.api_base_url.strip())


class DiscordBotDisabled(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UrlLibSearchRestClient:
    """Small stdlib REST client used only by the opt-in Discord bot runtime."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        *,
        query: str,
        limit: int | None = None,
        kind: str | None = None,
        show: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._search_sync,
            query=query,
            limit=limit,
            kind=kind,
            show=show,
        )

    def _search_sync(
        self,
        *,
        query: str,
        limit: int | None,
        kind: str | None,
        show: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, object] = {"query": query}
        if limit is not None:
            payload["limit"] = limit
        if kind is not None:
            payload["kind"] = kind
        if show is not None:
            payload["show"] = show

        body = json.dumps(payload).encode("utf-8")
        api_request = request.Request(
            f"{self.base_url}/search",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(api_request, timeout=self.timeout_seconds) as response:  # noqa: S310 - local opt-in REST URL.
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise RestClientError(f"REST API returned HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise RestClientError(f"Could not reach REST API: {exc.reason}") from exc

        try:
            decoded = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RestClientError("REST API returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise RestClientError("REST API returned an unexpected payload")
        if "error" in decoded:
            raise RestClientError("REST API returned an error payload")
        return decoded


class MediaMemoryDiscordBot:
    """Command handler facade for Discord slash commands backed by REST search."""

    def __init__(self, rest_client: SearchRestClient, *, default_limit: int = 3) -> None:
        self.rest_client = rest_client
        self.default_limit = default_limit

    async def episode(self, show: str, query: str) -> str:
        return await self._search_response(query=query, kind="episode", show=show)

    async def scene(self, query: str) -> str:
        return await self._search_response(query=query)

    async def quote(self, query: str) -> str:
        return await self._search_response(query=query)

    async def movie(self, query: str) -> str:
        return await self._search_response(query=query, kind="movie")

    async def _search_response(
        self,
        *,
        query: str,
        kind: str | None = None,
        show: str | None = None,
    ) -> str:
        try:
            payload = await self.rest_client.search(
                query=query,
                limit=self.default_limit,
                kind=kind,
                show=show,
            )
        except RestClientError:
            return "Media Memory REST API is unavailable."
        except Exception:  # pragma: no cover - defensive boundary for chat responses.
            return "Media Memory client error."
        return format_search_response(payload)

    def build_discord_client(self) -> object:
        """Create a discord.py client only when the optional package is installed."""

        try:
            import discord  # type: ignore[import-not-found]
            from discord import app_commands  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional runtime dependency.
            raise DiscordBotDisabled("Install discord.py to run the optional Discord bot") from exc

        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)

        @tree.command(name="episode", description="Search for an episode moment in a show")
        async def episode_command(interaction: discord.Interaction, show: str, query: str) -> None:
            await interaction.response.send_message(
                await self.episode(show, query),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @tree.command(name="scene", description="Search for a timestamped scene")
        async def scene_command(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.send_message(
                await self.scene(query),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @tree.command(name="quote", description="Search for dialogue or a quote")
        async def quote_command(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.send_message(
                await self.quote(query),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @tree.command(name="movie", description="Search for a movie result")
        async def movie_command(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.send_message(
                await self.movie(query),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @client.event
        async def on_ready() -> None:
            await tree.sync()

        return client


def create_discord_bot(
    config: MediaMemoryConfig,
    *,
    rest_client: SearchRestClient | None = None,
) -> MediaMemoryDiscordBot | DiscordBotDisabled:
    settings = DiscordBotSettings(
        enabled=config.discord.enabled,
        token=config.discord.token,
        api_base_url=config.discord.api_base_url,
        default_limit=config.discord.default_limit,
    )
    if not settings.enabled:
        return DiscordBotDisabled("Discord bot is disabled in config")
    if not settings.token:
        return DiscordBotDisabled("Discord bot token is not configured")
    if not settings.api_base_url.strip():
        return DiscordBotDisabled("Discord REST API base URL is not configured")
    if not _is_loopback_http_url(settings.api_base_url):
        return DiscordBotDisabled("Discord REST API base URL must be loopback HTTP")
    return MediaMemoryDiscordBot(
        rest_client or UrlLibSearchRestClient(settings.api_base_url),
        default_limit=settings.default_limit,
    )


def format_search_response(payload: dict[str, Any], *, max_results: int = 3) -> str:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return "No Media Memory results found."

    lines: list[str] = []
    for result in results[:max_results]:
        if not isinstance(result, dict):
            continue
        title = (
            _string(result.get("title")) or _string(result.get("media_title")) or "Unknown title"
        )
        show = _string(result.get("show_title")) or _string(result.get("show"))
        label = f"{show} - {title}" if show and show not in title else title
        evidence = _first_evidence(result)
        timestamp = _format_timestamp(evidence)
        snippet = _snippet(_string(evidence.get("text")) or _string(result.get("text")))
        confidence = result.get("confidence")

        parts = [label]
        if timestamp:
            parts.append(timestamp)
        if isinstance(confidence, int | float):
            parts.append(f"confidence {confidence:.2f}")
        header = " | ".join(parts)
        lines.append(f"**{header}**\n{snippet}" if snippet else f"**{header}**")

    if not lines:
        return "No Media Memory results found."
    return _cap_discord_message("\n\n".join(lines))


def _is_loopback_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "http":
        return False
    return (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}


def _cap_discord_message(message: str, *, max_length: int = 1900) -> str:
    if len(message) <= max_length:
        return message
    return f"{message[: max_length - 3].rstrip()}..."


def _first_evidence(result: dict[str, Any]) -> dict[str, Any]:
    evidences = result.get("evidences")
    if isinstance(evidences, list) and evidences and isinstance(evidences[0], dict):
        return evidences[0]
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        return evidence
    return {}


def _format_timestamp(evidence: dict[str, Any]) -> str | None:
    value = evidence.get("start_ms")
    if not isinstance(value, int | float):
        value = evidence.get("start_seconds")
        if isinstance(value, int | float):
            value = value * 1000
    if not isinstance(value, int | float):
        return None
    total_seconds = max(0, int(value // 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _snippet(text: str | None, *, max_length: int = 180) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}..."


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
