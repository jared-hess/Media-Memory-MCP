from __future__ import annotations

import json
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.models import MediaItem
from media_memory.core.vector_store import LanceDBVectorStore
from media_memory.ingest.pipeline import IngestPipeline
from media_memory.media_sources.plex import PlexMediaSource
from media_memory.metadata_sources.plex import PlexMetadataSource


class FakePlexClient:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, path: str) -> bytes:
        self.calls.append(path)
        return self.responses[path].encode("utf-8")


class FailingPlexClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, path: str) -> bytes:
        self.calls += 1
        raise AssertionError(f"Disabled Plex should not request {path}")


def test_disabled_plex_config_performs_zero_network_calls() -> None:
    client = FailingPlexClient()
    source = PlexMediaSource(
        enabled=False, url="http://plex.local:32400", token="token", client=client
    )

    assert source.scan() == []
    assert source.list_libraries() == []
    assert client.calls == 0


def test_plex_lists_libraries_and_maps_movies_and_episodes(tmp_path: Path) -> None:
    movie_path = tmp_path / "The.Matrix.1999.mkv"
    episode_path = tmp_path / "Seinfeld.S05E14.The.Marine.Biologist.mkv"
    movie_path.write_text("movie", encoding="utf-8")
    episode_path.write_text("episode", encoding="utf-8")
    client = FakePlexClient(
        {
            "/library/sections": """
                <MediaContainer>
                  <Directory key="1" title="Movies" type="movie" />
                  <Directory key="2" title="TV Shows" type="show" />
                </MediaContainer>
            """,
            "/library/sections/1/all": f"""
                <MediaContainer>
                  <Video type="movie" ratingKey="100" title="The Matrix" year="1999"
                         duration="8160000" summary="A hacker learns reality is simulated." rating="8.7">
                    <Media><Part file="{movie_path}" /></Media>
                  </Video>
                </MediaContainer>
            """,
            "/library/sections/2/all": f"""
                <MediaContainer>
                  <Video type="episode" ratingKey="200" title="The Marine Biologist"
                         grandparentTitle="Seinfeld" parentIndex="5" index="14"
                         year="1994" duration="1380000" summary="George saves a whale.">
                    <Media><Part file="{episode_path}" /></Media>
                  </Video>
                </MediaContainer>
            """,
        }
    )
    source = PlexMediaSource(
        enabled=True, url="http://plex.local:32400", token="token", client=client
    )

    libraries = source.list_libraries()
    items = source.scan()

    assert [library.title for library in libraries] == ["Movies", "TV Shows"]
    assert client.calls == [
        "/library/sections",
        "/library/sections",
        "/library/sections/1/all",
        "/library/sections/2/all",
    ]
    movie, episode = items
    assert movie.title == "The Matrix"
    assert movie.path == movie_path
    assert movie.kind == "movie"
    assert movie.year == 1999
    assert movie.runtime_seconds == 8160
    assert movie.provider_ids == {"plex_rating_key": "100"}
    assert movie.provider_refs[0].provider == "plex"
    assert movie.provider_refs[0].id == "100"
    assert movie.provider_refs[0].namespace == "rating-key"
    assert movie.provider_refs[0].raw["summary"] == "A hacker learns reality is simulated."
    assert episode.path == episode_path
    assert episode.kind == "episode"
    assert episode.title == "The Marine Biologist"
    assert episode.show_title == "Seinfeld"
    assert episode.season == 5
    assert episode.episode == 14
    assert episode.runtime_seconds == 1380
    assert episode.provider_ids == {"plex_rating_key": "200"}


def test_plex_library_filter_accepts_key_or_title(tmp_path: Path) -> None:
    media_path = tmp_path / "The.Matrix.1999.mkv"
    media_path.write_text("movie", encoding="utf-8")
    client = FakePlexClient(
        {
            "/library/sections": """
                <MediaContainer>
                  <Directory key="1" title="Movies" type="movie" />
                  <Directory key="2" title="TV Shows" type="show" />
                </MediaContainer>
            """,
            "/library/sections/1/all": f"""
                <MediaContainer>
                  <Video type="movie" ratingKey="100" title="The Matrix">
                    <Media><Part file="{media_path}" /></Media>
                  </Video>
                </MediaContainer>
            """,
        }
    )

    items = PlexMediaSource(
        enabled=True,
        url="http://plex.local:32400",
        token="token",
        libraries=["Movies"],
        client=client,
    ).scan()

    assert [item.path for item in items] == [media_path]
    assert "/library/sections/2/all" not in client.calls


def test_plex_metadata_source_uses_already_fetched_item_data() -> None:
    item = MediaItem(
        title="The Marine Biologist",
        path=Path("/media/Seinfeld.S05E14.The.Marine.Biologist.mkv"),
        kind="episode",
        season=5,
        episode=14,
        show_title="Seinfeld",
        season_number=5,
        episode_number=14,
        year=1994,
        runtime_seconds=1380,
        provider_ids={"plex_rating_key": "200"},
        provider_refs=[
            {
                "provider": "plex",
                "id": "200",
                "namespace": "rating-key",
                "raw": {"summary": "George saves a whale.", "rating": "8.9"},
            }
        ],
    )

    documents = PlexMetadataSource(enabled=True).find_documents(item)

    assert len(documents) == 1
    document = documents[0]
    assert document.source_path == "plex://metadata/200"
    assert document.source_kind == "metadata"
    assert document.provider_ids == {"source_provider": "plex", "plex_rating_key": "200"}
    assert "Show: Seinfeld" in document.text
    assert "Overview: George saves a whale." in document.text


def test_plex_items_upsert_media_metadata_and_metadata_documents(tmp_path: Path) -> None:
    media_path = tmp_path / "Seinfeld.S05E14.The.Marine.Biologist.mkv"
    media_path.write_text("episode", encoding="utf-8")
    source = PlexMediaSource(
        enabled=True,
        url="http://plex.local:32400",
        token="token",
        client=FakePlexClient(
            {
                "/library/sections": """
                    <MediaContainer><Directory key="2" title="TV Shows" type="show" /></MediaContainer>
                """,
                "/library/sections/2/all": f"""
                    <MediaContainer>
                      <Video type="episode" ratingKey="200" title="The Marine Biologist"
                             grandparentTitle="Seinfeld" parentIndex="5" index="14"
                             year="1994" duration="1380000" summary="George saves a whale.">
                        <Media><Part file="{media_path}" /></Media>
                      </Video>
                    </MediaContainer>
                """,
            }
        ),
    )
    db = MediaMemoryDB(tmp_path / "media-memory.sqlite")
    db.init_schema()
    stats = IngestPipeline(
        db,
        MockEmbeddingProvider(),
        LanceDBVectorStore(tmp_path / "vectors"),
        metadata_sources=[PlexMetadataSource(enabled=True)],
    ).ingest_media_items(source.scan())

    assert stats["failed_jobs"] == 0
    assert stats["documents"] == 1
    row = db.conn.execute(
        """
        SELECT title, kind, show_title, season_number, episode_number, runtime_seconds,
               provider_ids_json, provider_refs_json
        FROM media_items
        WHERE path = ?
        """,
        (str(media_path),),
    ).fetchone()
    assert row is not None
    assert row["title"] == "The Marine Biologist"
    assert row["show_title"] == "Seinfeld"
    assert row["runtime_seconds"] == 1380
    assert json.loads(row["provider_ids_json"]) == {"plex_rating_key": "200"}
    assert json.loads(row["provider_refs_json"])[0]["namespace"] == "rating-key"
    document = db.conn.execute(
        """
        SELECT d.source_path, d.provider_ids_json, c.text
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.source_kind = 'metadata'
        """
    ).fetchone()
    assert document is not None
    assert document["source_path"] == "plex://metadata/200"
    assert json.loads(document["provider_ids_json"]) == {
        "source_provider": "plex",
        "plex_rating_key": "200",
    }
    assert "Overview: George saves a whale." in document["text"]
