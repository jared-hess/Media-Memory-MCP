from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib import parse, request

from media_memory.core.models import MediaItem, ProviderCandidate, ProviderRef
from media_memory.media_sources.base import ProviderError
from media_memory.subtitle_sources.base import SubtitleCandidate

PROVIDER_NAME = "opensubtitles"
DEFAULT_API_BASE_URL = "https://api.opensubtitles.com/api/v1"


class OpenSubtitlesClient(Protocol):
    """Client boundary for OpenSubtitles HTTP operations."""

    def authenticate(self, *, api_key: str, username: str, password: str) -> str:
        """Return an authenticated bearer token."""

    def search(self, *, token: str, params: Mapping[str, object]) -> list[Mapping[str, Any]]:
        """Return raw subtitle search results."""

    def download(self, *, token: str, file_id: str) -> bytes:
        """Return subtitle bytes for an OpenSubtitles file identifier."""


@dataclass(frozen=True)
class OpenSubtitlesFetchMetadata:
    """Metadata recorded for a fetched OpenSubtitles subtitle."""

    provider: str
    language: str | None
    confidence: float
    checksum: str
    license_status: str | None
    path: str
    external_id: str


class OpenSubtitlesHTTPClient:
    """Small stdlib OpenSubtitles API client used only when explicitly configured."""

    def __init__(
        self, *, base_url: str = DEFAULT_API_BASE_URL, timeout_seconds: float = 20.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def authenticate(self, *, api_key: str, username: str, password: str) -> str:
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        response = self._request_json(
            "POST",
            "/login",
            api_key=api_key,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        token = response.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderError("OpenSubtitles authentication did not return a token.")
        return token

    def search(self, *, token: str, params: Mapping[str, object]) -> list[Mapping[str, Any]]:
        query = parse.urlencode(
            {key: value for key, value in params.items() if value not in (None, "", [])}
        )
        response = self._request_json("GET", f"/subtitles?{query}", token=token)
        data = response.get("data", [])
        if not isinstance(data, list):
            raise ProviderError("OpenSubtitles search response has an invalid data shape.")
        return [item for item in data if isinstance(item, Mapping)]

    def download(self, *, token: str, file_id: str) -> bytes:
        response = self._request_json(
            "POST", "/download", token=token, body=json.dumps({"file_id": file_id}).encode("utf-8")
        )
        link = response.get("link")
        if not isinstance(link, str) or not link:
            raise ProviderError("OpenSubtitles download response did not include a link.")
        with request.urlopen(link, timeout=self.timeout_seconds) as subtitle_response:  # noqa: S310 - opt-in provider URL.
            return subtitle_response.read()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        api_key: str | None = None,
        token: str | None = None,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {"User-Agent": "media-memory-mcp", **(dict(headers or {}))}
        if api_key is not None:
            request_headers["Api-Key"] = api_key
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        api_request = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with request.urlopen(api_request, timeout=self.timeout_seconds) as response:  # noqa: S310 - opt-in provider URL.
                decoded = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise ProviderError(f"OpenSubtitles request failed: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ProviderError("OpenSubtitles returned a non-object JSON response.")
        return decoded


class OpenSubtitlesSource:
    """Opt-in OpenSubtitles subtitle provider with cache and budget safeguards."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        languages: list[str] | None = None,
        hearing_impaired: bool = False,
        daily_download_budget: int = 900,
        min_match_confidence: float = 0.85,
        cache_dir: Path | str = Path("/data/subtitles/opensubtitles"),
        client: OpenSubtitlesClient | None = None,
    ) -> None:
        self.enabled = enabled
        self.api_key = _none_if_placeholder(api_key)
        self.username = _none_if_placeholder(username)
        self.password = _none_if_placeholder(password)
        self.languages = languages or ["eng", "en"]
        self.hearing_impaired = hearing_impaired
        self.daily_download_budget = daily_download_budget
        self.min_match_confidence = min_match_confidence
        self.cache_dir = Path(cache_dir)
        self.client = client or OpenSubtitlesHTTPClient()
        self._token: str | None = None

    def find(self, item: MediaItem) -> list[SubtitleCandidate]:
        return self.find_for_media(item)

    def find_for_media(self, item: MediaItem) -> list[SubtitleCandidate]:
        if not self.enabled:
            return []
        token = self._authenticate()
        params = self._search_params(item)
        raw_candidates = self.client.search(token=token, params=params)
        candidates = [self._candidate_from_result(item, result) for result in raw_candidates]
        confident = [
            candidate
            for candidate in candidates
            if (candidate.score or 0.0) >= self.min_match_confidence
        ]
        confident.sort(key=lambda candidate: candidate.score or 0.0, reverse=True)
        return confident

    def fetch(
        self, candidate: Path | SubtitleCandidate | ProviderCandidate, *, force: bool = False
    ) -> Path:
        if isinstance(candidate, Path):
            return candidate
        if isinstance(candidate, SubtitleCandidate) and candidate.provider != PROVIDER_NAME:
            if candidate.path is None:
                raise ProviderError("Non-OpenSubtitles candidate does not include a local path.")
            return candidate.path
        raw = candidate.raw if isinstance(candidate, (SubtitleCandidate, ProviderCandidate)) else {}
        provider_data = raw.get(PROVIDER_NAME)
        if not isinstance(provider_data, Mapping):
            raise ProviderError("OpenSubtitles candidate is missing provider metadata.")
        external_id = _required_string(provider_data, "external_id")
        file_id = _required_string(provider_data, "file_id")
        language = _optional_string(provider_data.get("language"))
        confidence = float(provider_data.get("confidence", 0.0))
        license_status = _optional_string(provider_data.get("license_status"))
        cache_path = self._cache_path(external_id, language)
        metadata_path = self._metadata_path(cache_path)
        if cache_path.exists() and not force:
            return cache_path
        if not self.enabled:
            raise ProviderError("OpenSubtitles fetch requested while provider is disabled.")
        if confidence < self.min_match_confidence:
            raise ProviderError(
                "OpenSubtitles candidate confidence is below the configured threshold."
            )
        self._ensure_budget_available()
        token = self._authenticate()
        content = self.client.download(token=token, file_id=file_id)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        metadata = OpenSubtitlesFetchMetadata(
            provider=PROVIDER_NAME,
            language=language,
            confidence=confidence,
            checksum=checksum,
            license_status=license_status,
            path=str(cache_path),
            external_id=external_id,
        )
        metadata_path.write_text(
            json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self._record_download()
        return cache_path

    def metadata_for(self, subtitle_path: Path | str) -> OpenSubtitlesFetchMetadata | None:
        """Return cached metadata for a fetched subtitle, if present."""

        path = Path(subtitle_path)
        metadata_path = self._metadata_path(path)
        if not metadata_path.exists():
            return None
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        return OpenSubtitlesFetchMetadata(**data)

    def _authenticate(self) -> str:
        if self._token is not None:
            return self._token
        missing = [
            name
            for name, value in {
                "api_key": self.api_key,
                "username": self.username,
                "password": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise ProviderError(
                f"OpenSubtitles is enabled but missing credentials: {', '.join(missing)}."
            )
        self._token = self.client.authenticate(
            api_key=self.api_key or "", username=self.username or "", password=self.password or ""
        )
        return self._token

    def _search_params(self, item: MediaItem) -> dict[str, object]:
        params: dict[str, object] = {
            "languages": ",".join(self.languages),
            "hearing_impaired": "include" if self.hearing_impaired else "exclude",
        }
        imdb_id = _imdb_id_for(item)
        if imdb_id is not None:
            params["imdb_id"] = imdb_id.removeprefix("tt")
            return params
        query = item.show_title or item.title
        if item.kind == "episode" and item.show_title:
            params["parent_feature"] = item.show_title
            params["episode_number"] = item.episode_number or item.episode
            params["season_number"] = item.season_number or item.season
        else:
            params["query"] = query
            params["year"] = item.year
        return {key: value for key, value in params.items() if value is not None}

    def _candidate_from_result(
        self, item: MediaItem, result: Mapping[str, Any]
    ) -> SubtitleCandidate:
        attributes = (
            result.get("attributes") if isinstance(result.get("attributes"), Mapping) else result
        )
        attributes = attributes if isinstance(attributes, Mapping) else {}
        files = attributes.get("files")
        file_id = (
            _first_file_id(files)
            or _optional_string(attributes.get("file_id"))
            or _optional_string(result.get("file_id"))
        )
        external_id = (
            _optional_string(result.get("id")) or _optional_string(attributes.get("id")) or file_id
        )
        if file_id is None or external_id is None:
            confidence = 0.0
        else:
            confidence = _confidence_for(item, result, attributes, self.languages)
        language = _optional_string(attributes.get("language")) or _optional_string(
            attributes.get("language_code")
        )
        license_status = _optional_string(attributes.get("license")) or _optional_string(
            attributes.get("license_status")
        )
        cache_path = self._cache_path(external_id, language) if external_id is not None else None
        raw = {
            PROVIDER_NAME: {
                "external_id": external_id,
                "file_id": file_id,
                "language": language,
                "confidence": confidence,
                "license_status": license_status,
                "cached": bool(cache_path and cache_path.exists()),
                "raw": dict(result),
            }
        }
        refs = (
            [
                ProviderRef(
                    provider=PROVIDER_NAME, id=external_id, confidence=confidence, raw=dict(result)
                )
            ]
            if external_id
            else []
        )
        return SubtitleCandidate(
            path=cache_path if cache_path and cache_path.exists() else None,
            uri=f"opensubtitles://{external_id}" if external_id else None,
            language=language,
            provider=PROVIDER_NAME,
            score=confidence,
            raw={**raw, "refs": [ref.to_dict() for ref in refs]},
        )

    def _ensure_budget_available(self) -> None:
        if self.daily_download_budget < 1:
            raise ProviderError("OpenSubtitles daily download budget is exhausted.")
        usage = self._budget_usage()
        if usage >= self.daily_download_budget:
            raise ProviderError("OpenSubtitles daily download budget is exhausted.")

    def _record_download(self) -> None:
        budget_path = self._budget_path()
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        usage = self._budget_usage() + 1
        budget_path.write_text(
            json.dumps({"date": date.today().isoformat(), "downloads": usage}) + "\n",
            encoding="utf-8",
        )

    def _budget_usage(self) -> int:
        budget_path = self._budget_path()
        if not budget_path.exists():
            return 0
        try:
            data = json.loads(budget_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        if data.get("date") != date.today().isoformat():
            return 0
        downloads = data.get("downloads", 0)
        return int(downloads) if isinstance(downloads, int) else 0

    def _cache_path(self, external_id: str, language: str | None) -> Path:
        cache_key = hashlib.sha256(
            f"{external_id}:{language or 'unknown'}".encode("utf-8")
        ).hexdigest()[:24]
        return self.cache_dir / f"{cache_key}.srt"

    def _metadata_path(self, cache_path: Path) -> Path:
        return cache_path.with_suffix(f"{cache_path.suffix}.json")

    def _budget_path(self) -> Path:
        return self.cache_dir / "budget" / f"{date.today().isoformat()}.json"


def _none_if_placeholder(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if value.startswith("${") and value.endswith("}"):
        return None
    return value


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderError(f"OpenSubtitles candidate is missing {key}.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_file_id(files: object) -> str | None:
    if not isinstance(files, list):
        return None
    for file_entry in files:
        if isinstance(file_entry, Mapping):
            file_id = file_entry.get("file_id")
            if isinstance(file_id, int):
                return str(file_id)
            if isinstance(file_id, str) and file_id:
                return file_id
    return None


def _imdb_id_for(item: MediaItem) -> str | None:
    direct = item.provider_ids.get("imdb") or item.provider_ids.get("imdb_id")
    if direct:
        return direct
    for ref in item.provider_refs:
        if ref.provider == "imdb" or ref.namespace == "imdb":
            return ref.id
    return None


def _confidence_for(
    item: MediaItem,
    result: Mapping[str, Any],
    attributes: Mapping[str, Any],
    preferred_languages: list[str],
) -> float:
    explicit = attributes.get("confidence") or attributes.get("score") or result.get("score")
    if isinstance(explicit, int | float):
        return max(0.0, min(float(explicit), 1.0))
    confidence = 0.45
    result_imdb = _optional_string(attributes.get("imdb_id")) or _optional_string(
        result.get("imdb_id")
    )
    item_imdb = _imdb_id_for(item)
    if item_imdb and result_imdb and item_imdb.removeprefix("tt") == result_imdb.removeprefix("tt"):
        confidence += 0.35
    if _titles_match(item, attributes):
        confidence += 0.2
    if item.year and _int_value(attributes.get("year")) == item.year:
        confidence += 0.1
    if item.kind == "episode":
        if _int_value(attributes.get("season_number") or attributes.get("season")) in {
            item.season,
            item.season_number,
        }:
            confidence += 0.05
        if _int_value(attributes.get("episode_number") or attributes.get("episode")) in {
            item.episode,
            item.episode_number,
        }:
            confidence += 0.05
    language = _optional_string(attributes.get("language")) or _optional_string(
        attributes.get("language_code")
    )
    if language in preferred_languages:
        confidence += 0.1
    return max(0.0, min(confidence, 1.0))


def _titles_match(item: MediaItem, attributes: Mapping[str, Any]) -> bool:
    title = (
        _optional_string(attributes.get("feature_details", {}).get("title"))
        if isinstance(attributes.get("feature_details"), Mapping)
        else None
    )
    title = (
        title
        or _optional_string(attributes.get("title"))
        or _optional_string(attributes.get("movie_name"))
    )
    expected_titles = {item.title.casefold()}
    if item.show_title:
        expected_titles.add(item.show_title.casefold())
    if item.episode_title:
        expected_titles.add(item.episode_title.casefold())
    return bool(title and title.casefold() in expected_titles)


def _int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
