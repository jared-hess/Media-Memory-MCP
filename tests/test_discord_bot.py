from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any
from urllib import error

from media_memory.config import MediaMemoryConfig
from media_memory.discord_bot import (
    DiscordBotDisabled,
    MediaMemoryDiscordBot,
    RestClientError,
    create_discord_bot,
)
from media_memory.discord_bot.bot import UrlLibSearchRestClient


class FakeRestClient:
    def __init__(
        self, payload: dict[str, Any] | None = None, *, error: Exception | None = None
    ) -> None:
        self.payload = payload or {"results": []}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        *,
        query: str,
        limit: int | None = None,
        kind: str | None = None,
        show: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"query": query, "limit": limit, "kind": kind, "show": show})
        if self.error is not None:
            raise self.error
        return self.payload


def test_scene_command_formats_timestamped_result() -> None:
    client = FakeRestClient(
        {
            "results": [
                {
                    "title": "Winter Is Coming",
                    "show_title": "Example Show",
                    "confidence": 0.91,
                    "evidences": [
                        {
                            "start_ms": 65_000,
                            "end_ms": 70_000,
                            "text": "The cold open evidence line appears here.",
                        }
                    ],
                }
            ]
        }
    )
    bot = MediaMemoryDiscordBot(client, default_limit=2)

    response = asyncio.run(bot.scene("cold open"))

    assert client.calls == [{"query": "cold open", "limit": 2, "kind": None, "show": None}]
    assert "Example Show - Winter Is Coming" in response
    assert "1:05" in response
    assert "The cold open evidence line appears here." in response
    assert "confidence 0.91" in response


def test_episode_command_passes_show_filter_to_rest() -> None:
    client = FakeRestClient({"results": []})
    bot = MediaMemoryDiscordBot(client, default_limit=3)

    response = asyncio.run(bot.episode("Example Show", "winter"))

    assert client.calls == [
        {"query": "winter", "limit": 3, "kind": "episode", "show": "Example Show"}
    ]
    assert response == "No Media Memory results found."


def test_quote_and_movie_commands_use_rest_kinds() -> None:
    client = FakeRestClient({"results": []})
    bot = MediaMemoryDiscordBot(client, default_limit=1)

    asyncio.run(bot.quote("famous line"))
    asyncio.run(bot.movie("space"))

    assert client.calls == [
        {"query": "famous line", "limit": 1, "kind": None, "show": None},
        {"query": "space", "limit": 1, "kind": "movie", "show": None},
    ]


def test_rest_errors_are_returned_as_safe_chat_message() -> None:
    client = FakeRestClient(error=RestClientError("secret-token connection refused"))
    bot = MediaMemoryDiscordBot(client)

    response = asyncio.run(bot.scene("anything"))

    assert response == "Media Memory REST API is unavailable."
    assert "secret-token" not in response


def test_missing_token_or_disabled_config_disables_bot_without_client() -> None:
    disabled = create_discord_bot(MediaMemoryConfig())
    assert isinstance(disabled, DiscordBotDisabled)
    assert disabled.reason == "Discord bot is disabled in config"

    missing_token_config = MediaMemoryConfig(discord={"enabled": True, "token": None})
    missing_token = create_discord_bot(missing_token_config)

    assert isinstance(missing_token, DiscordBotDisabled)
    assert missing_token.reason == "Discord bot token is not configured"

    remote_config = MediaMemoryConfig(
        discord={
            "enabled": True,
            "token": "placeholder-token",
            "api_base_url": "https://example.com",
        }
    )
    remote_disabled = create_discord_bot(remote_config)

    assert isinstance(remote_disabled, DiscordBotDisabled)
    assert remote_disabled.reason == "Discord REST API base URL must be loopback HTTP"


def test_enabled_config_uses_injected_rest_client_without_network() -> None:
    client = FakeRestClient({"results": []})
    config = MediaMemoryConfig(discord={"enabled": True, "token": "placeholder-token"})

    bot = create_discord_bot(config, rest_client=client)

    assert isinstance(bot, MediaMemoryDiscordBot)
    assert asyncio.run(bot.movie("no hits")) == "No Media Memory results found."
    assert client.calls == [{"query": "no hits", "limit": 3, "kind": "movie", "show": None}]


def test_formatter_caps_discord_message_length() -> None:
    client = FakeRestClient(
        {
            "results": [
                {
                    "title": "A" * 2000,
                    "evidences": [{"text": "B" * 1000}],
                }
            ]
        }
    )
    bot = MediaMemoryDiscordBot(client)

    response = asyncio.run(bot.movie("long"))

    assert len(response) <= 1900
    assert response.endswith("...")


def test_url_lib_rest_client_does_not_echo_http_error_body(monkeypatch: Any) -> None:
    def raise_http_error(*_args: object, **_kwargs: object) -> None:
        raise error.HTTPError(
            "http://127.0.0.1:8765/search",
            500,
            "Internal Server Error",
            hdrs=None,
            fp=BytesIO(b'{"error":"secret-token leaked"}'),
        )

    monkeypatch.setattr("media_memory.discord_bot.bot.request.urlopen", raise_http_error)
    client = UrlLibSearchRestClient("http://127.0.0.1:8765")

    try:
        asyncio.run(client.search(query="anything"))
    except RestClientError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion path.
        raise AssertionError("expected RestClientError")

    assert message == "REST API returned HTTP 500"
    assert "secret-token" not in message


def test_url_lib_rest_client_does_not_echo_json_error_payload(monkeypatch: Any) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"error":"secret-token leaked"}'

    def return_error_payload(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("media_memory.discord_bot.bot.request.urlopen", return_error_payload)
    client = UrlLibSearchRestClient("http://127.0.0.1:8765")

    try:
        asyncio.run(client.search(query="anything"))
    except RestClientError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion path.
        raise AssertionError("expected RestClientError")

    assert message == "REST API returned an error payload"
    assert "secret-token" not in message
