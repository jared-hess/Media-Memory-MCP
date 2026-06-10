from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_memory.core.errors import ProviderError
from media_memory.core.models import MediaItem
from media_memory.media_sources.base import ProviderError as SourceProviderError
from media_memory.media_sources.filesystem import FilesystemMediaSource
from media_memory.media_sources.plex import PlexMediaSource
from media_memory.metadata_sources.filename import FilenameMetadataSource
from media_memory.metadata_sources.plex import PlexMetadataSource
from media_memory.metadata_sources.tmdb import TmdbMetadataSource
from media_memory.metadata_sources.tvmaze import TvmazeMetadataSource
from media_memory.subtitle_sources.bazarr import BazarrSubtitleSource
from media_memory.subtitle_sources.embedded import EmbeddedSubtitleSource
from media_memory.subtitle_sources.local import LocalSubtitleSource
from media_memory.subtitle_sources.local_sidecar import LocalSidecarSubtitleSource
from media_memory.subtitle_sources.opensubtitles import OpenSubtitlesSource


class SourceAdapterTests(unittest.TestCase):
    def test_filesystem_scan_discovers_configured_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            episode_path = root / "Show.S01E02.custom"
            movie_path = root / "Movie.mp4"
            ignored_path = root / "notes.txt"
            episode_path.write_text("", encoding="utf-8")
            movie_path.write_text("", encoding="utf-8")
            ignored_path.write_text("", encoding="utf-8")

            items = FilesystemMediaSource(root, extensions=[".custom"]).scan()

        self.assertEqual([episode_path], [item.path for item in items])
        self.assertEqual("episode", items[0].kind)
        self.assertEqual(1, items[0].season)
        self.assertEqual(2, items[0].episode)

    def test_filesystem_scan_preserves_legacy_constructor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_path = root / "Movie.mkv"
            media_path.write_text("", encoding="utf-8")

            items = FilesystemMediaSource(root).scan()

        self.assertEqual([media_path], [item.path for item in items])
        self.assertIsInstance(items[0], MediaItem)

    def test_local_subtitle_source_discovers_configured_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_path = root / "Movie.mkv"
            wanted_path = root / "Movie.en.caption"
            ignored_path = root / "Movie.en.srt"
            media_path.write_text("", encoding="utf-8")
            wanted_path.write_text("subtitle", encoding="utf-8")
            ignored_path.write_text("subtitle", encoding="utf-8")
            item = MediaItem(title="Movie", path=media_path, kind="movie")

            candidates = LocalSubtitleSource(extensions=[".caption"]).find(item)

        self.assertEqual([wanted_path], candidates)

    def test_local_sidecar_compatibility_import_and_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_path = root / "Movie.mkv"
            subtitle_path = root / "Movie.srt"
            media_path.write_text("", encoding="utf-8")
            subtitle_path.write_text("subtitle", encoding="utf-8")
            item = MediaItem(title="Movie", path=media_path, kind="movie")

            candidates = LocalSidecarSubtitleSource().find_for_media(item)

        self.assertEqual([subtitle_path], candidates)

    def test_local_subtitle_source_ignores_symlink_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.srt"
            media_path = root / "Movie.mkv"
            subtitle_path = root / "Movie.srt"
            outside.write_text("secret", encoding="utf-8")
            media_path.write_text("", encoding="utf-8")
            subtitle_path.symlink_to(outside)
            item = MediaItem(title="Movie", path=media_path, kind="movie")

            candidates = LocalSubtitleSource().find(item)

        self.assertEqual([], candidates)

    def test_local_subtitle_source_enforces_configured_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "allowed"
            outside = root / "outside"
            allowed.mkdir()
            outside.mkdir()
            media_path = outside / "Movie.mkv"
            subtitle_path = outside / "Movie.srt"
            media_path.write_text("", encoding="utf-8")
            subtitle_path.write_text("subtitle", encoding="utf-8")
            item = MediaItem(title="Movie", path=media_path, kind="movie")

            candidates = LocalSubtitleSource(roots=[allowed]).find(item)

        self.assertEqual([], candidates)

    def test_disabled_providers_import_construct_and_stay_inert(self) -> None:
        item = MediaItem(title="Movie", path=Path("/media/Movie.mkv"), kind="movie")

        self.assertEqual([], PlexMediaSource().scan())
        self.assertEqual([], EmbeddedSubtitleSource().find(item))
        self.assertEqual([], OpenSubtitlesSource().find(item))
        self.assertEqual([], BazarrSubtitleSource().find(item))
        self.assertEqual(item, FilenameMetadataSource().enrich(item))
        self.assertEqual(item, PlexMetadataSource().enrich(item))
        self.assertEqual(item, TmdbMetadataSource().enrich(item))
        self.assertEqual(item, TvmazeMetadataSource().enrich(item))

    def test_enabled_placeholders_raise_canonical_provider_error(self) -> None:
        item = MediaItem(title="Movie", path=Path("/media/Movie.mkv"), kind="movie")

        self.assertIs(SourceProviderError, ProviderError)
        with self.assertRaises(ProviderError):
            PlexMediaSource(enabled=True).scan()
        self.assertEqual(item, PlexMetadataSource(enabled=True).enrich(item))


if __name__ == "__main__":
    unittest.main()
