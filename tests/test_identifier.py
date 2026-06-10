from __future__ import annotations

import unittest

from media_memory.core.ids import chunk_id, document_id, embedding_id, ingest_job_id, media_id
from media_memory.ingest.identify import identify_media_path


class IdentifierTests(unittest.TestCase):
    def test_identifies_dotted_episode_filename(self) -> None:
        item = identify_media_path("/media/Show.Name.S07E01.Episode.Title.mkv")

        self.assertEqual("episode", item.kind)
        self.assertEqual("Show Name", item.show_title)
        self.assertEqual(7, item.season)
        self.assertEqual(1, item.episode)
        self.assertEqual("Episode Title", item.episode_title)

    def test_identifies_dash_separated_episode_filename(self) -> None:
        item = identify_media_path("/media/Show Name - S07E01 - Episode Title.mkv")

        self.assertEqual("episode", item.kind)
        self.assertEqual("Show Name", item.show_title)
        self.assertEqual(7, item.season_number)
        self.assertEqual(1, item.episode_number)
        self.assertEqual("Episode Title", item.title)

    def test_identifies_episode_from_season_folder_path(self) -> None:
        item = identify_media_path("/media/Show Name/Season 07/01 - Episode Title.mkv")

        self.assertEqual("episode", item.kind)
        self.assertEqual("Show Name", item.show_title)
        self.assertEqual(7, item.season)
        self.assertEqual(1, item.episode)
        self.assertEqual("Episode Title", item.episode_title)

    def test_identifies_movie_with_parenthesized_year(self) -> None:
        item = identify_media_path("/movies/Movie Name (1999).mkv")

        self.assertEqual("movie", item.kind)
        self.assertEqual("Movie Name", item.title)
        self.assertEqual(1999, item.year)

    def test_identifies_movie_with_dotted_year_and_quality(self) -> None:
        item = identify_media_path("/movies/Movie.Name.1999.1080p.mkv")

        self.assertEqual("movie", item.kind)
        self.assertEqual("Movie Name", item.title)
        self.assertEqual(1999, item.year)

    def test_episode_release_suffixes_do_not_become_episode_titles(self) -> None:
        for path in (
            "/media/Show.Name.S01E01.1080p.WEB-DL.mkv",
            "/media/Show.Name.S01E01.WEB.H264.mkv",
        ):
            with self.subTest(path=path):
                item = identify_media_path(path)
                self.assertEqual("Show Name", item.show_title)
                self.assertEqual(1, item.season)
                self.assertEqual(1, item.episode)
                self.assertIsNone(item.episode_title)
                self.assertEqual("Show Name", item.title)

    def test_episode_title_strips_trailing_release_quality(self) -> None:
        item = identify_media_path("/media/Show.Name.S01E01.Episode.Title.1080p.mkv")

        self.assertEqual("Episode Title", item.episode_title)
        self.assertEqual("Episode Title", item.title)

    def test_media_ids_are_deterministic_and_corpus_sensitive(self) -> None:
        first = media_id(path="/media/Show/S01E01.mkv", corpus_id="local")
        second = media_id(path="/media/Show/S01E01.mkv", corpus_id="local")
        other_corpus = media_id(path="/media/Show/S01E01.mkv", corpus_id="archive")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other_corpus)
        self.assertTrue(first.startswith("v1:media:local:s01e01:"))

    def test_external_ids_take_precedence_over_path_for_media_ids(self) -> None:
        original_path = media_id(
            path="/media/old-name.mkv",
            corpus_id="local",
            external_ids={"tmdb": "1234"},
        )
        renamed_path = media_id(
            path="/media/new-name.mkv",
            corpus_id="local",
            external_ids={"tmdb": "1234"},
        )

        self.assertEqual(original_path, renamed_path)

    def test_document_chunk_ingest_and_embedding_ids_are_stable(self) -> None:
        media = media_id(path="/media/movie.mkv")
        document = document_id(media_id=media, source_path="/media/movie.en.srt")
        chunk = chunk_id(document_id=document, text="hello there", start_ms=1000, end_ms=2000)
        ingest = ingest_job_id(media_id=media, document_id=document, source_path="/media/movie.en.srt")
        embedding = embedding_id(chunk_id=chunk, provider="mock", model="mock")

        self.assertEqual(document, document_id(media_id=media, source_path="/media/movie.en.srt"))
        self.assertEqual(chunk, chunk_id(document_id=document, text="hello there", start_ms=1000, end_ms=2000))
        self.assertEqual(ingest, ingest_job_id(media_id=media, document_id=document, source_path="/media/movie.en.srt"))
        self.assertEqual(embedding, embedding_id(chunk_id=chunk, provider="mock", model="mock"))
        self.assertTrue(document.startswith("v1:doc:local:"))
        self.assertTrue(chunk.startswith("v1:chunk:local:"))
        self.assertTrue(ingest.startswith("v1:ingest:local:"))
        self.assertTrue(embedding.startswith("v1:emb:local:mock:"))

    def test_ids_are_strings_with_valid_prefixes_when_hints_are_empty(self) -> None:
        media = media_id(corpus_id="local")
        empty_corpus = media_id(path="/media/movie.mkv", corpus_id="")
        document = document_id(media_id=media, source_path=None, source_kind="")
        chunk = chunk_id(document_id=document, text="", start_ms=None, end_ms=None)
        ingest = ingest_job_id(corpus_id="local")
        embedding = embedding_id(chunk_id=chunk, provider="mock", model="")

        self.assertIsInstance(media, str)
        self.assertIsInstance(empty_corpus, str)
        self.assertIsInstance(document, str)
        self.assertIsInstance(chunk, str)
        self.assertIsInstance(ingest, str)
        self.assertIsInstance(embedding, str)
        self.assertTrue(media.startswith("v1:media:local:"))
        self.assertTrue(empty_corpus.startswith("v1:media:unknown:movie:"))
        self.assertTrue(document.startswith("v1:doc:local:unknown:"))
        self.assertTrue(chunk.startswith("v1:chunk:local:"))
        self.assertTrue(ingest.startswith("v1:ingest:local:"))
        self.assertTrue(embedding.startswith("v1:emb:local:unknown:"))


if __name__ == "__main__":
    unittest.main()
