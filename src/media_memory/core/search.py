from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

from pydantic import TypeAdapter

from media_memory.core.db import MediaMemoryDB, SCHEMA_VERSION
from media_memory.core.embeddings import EmbeddingProvider
from media_memory.core.models import DEFAULT_CORPUS_ID, SearchEvidence, SearchFilters, SearchResult
from media_memory.core.ranking import (
    RankingSignals,
    combine_structured_scores,
    metadata_confidence,
    normalize_fts_score,
)
from media_memory.core.vector_store import VectorStore


_SEARCH_RESULT_LIST = TypeAdapter(list[SearchResult])
_TOKEN_RE = re.compile(r'"[^"]+"|[\w*]+', re.UNICODE)
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_CACHE_RANKING_VERSION = 2


class SearchService:
    """SQLite FTS-backed search service.

    The constructor keeps the legacy embedding/vector parameters for CLI/MCP compatibility,
    but the query path intentionally does not call them.
    """

    def __init__(
        self,
        db: MediaMemoryDB,
        embeddings: EmbeddingProvider | None = None,
        vectors: VectorStore | None = None,
        *,
        use_cache: bool = True,
    ):
        self.db = db
        self.embeddings = embeddings
        self.vectors = vectors
        self.use_cache = use_cache

    def search_media(
        self,
        query: str,
        limit: int = 10,
        filters: SearchFilters | None = None,
        **filter_values: object,
    ) -> list[SearchResult]:
        """Search indexed media using SQLite FTS only."""

        normalized_query = normalize_query(query)
        if not normalized_query:
            return []

        active_filters = _merge_filters(filters, filter_values, limit=limit)
        result_limit = _limit_from_filters(active_filters, limit)
        cache_key = self._cache_key(normalized_query, active_filters, mode="search_media")
        cached = self._get_cached_results(cache_key)
        if cached is not None:
            return cached[:result_limit]

        rows = self._fts_rows(
            normalized_query,
            active_filters,
            limit=max(result_limit * 6, 30),
            preferred_source_kinds=set(),
        )
        results = self._group_media_results(
            rows,
            result_limit,
            preferred_source_kinds=set(),
            query=normalized_query,
        )
        self._set_cached_results(cache_key, normalized_query, active_filters, results)
        return results

    def find_episode(
        self,
        query: str,
        season: int | None = None,
        episode: int | None = None,
        limit: int = 10,
        filters: SearchFilters | None = None,
        **filter_values: object,
    ) -> list[SearchResult]:
        """Find episode-like media, preferring summary or metadata source rows."""

        merged = dict(filter_values)
        merged.setdefault("kind", "episode")
        if season is not None:
            merged["season"] = season
            merged["season_number"] = season
        if episode is not None:
            merged["episode"] = episode
            merged["episode_number"] = episode
        active_filters = _merge_filters(filters, merged, limit=limit)
        rows = self._fts_rows(
            normalize_query(query),
            active_filters,
            limit=max(limit * 8, 40),
            preferred_source_kinds={"summary", "metadata", "description"},
        )
        return self._group_media_results(
            rows,
            _limit_from_filters(active_filters, limit),
            preferred_source_kinds={"summary", "metadata", "description"},
            query=normalize_query(query),
        )

    def find_scene(
        self,
        query: str,
        media_path: str | None = None,
        limit: int = 10,
        filters: SearchFilters | None = None,
        **filter_values: object,
    ) -> list[dict[str, object]]:
        """Find timestamped subtitle scenes for a query."""

        merged = dict(filter_values)
        if media_path is not None:
            merged["media_path"] = media_path
        active_filters = _merge_filters(filters, merged, limit=limit)
        rows = self._fts_rows(
            normalize_query(query),
            active_filters,
            limit=max(limit * 6, 30),
            preferred_source_kinds={"subtitle", "srt", "caption", "subtitles"},
            require_timestamps=True,
        )
        return [
            self._scene_shape(row, query=query)
            for row in rows[: _limit_from_filters(active_filters, limit)]
        ]

    def search_dialogue(
        self,
        query: str,
        limit: int = 10,
        filters: SearchFilters | None = None,
        **filter_values: object,
    ) -> list[dict[str, object]]:
        """Search dialogue with timestamped subtitle evidence."""

        return self.find_scene(query=query, limit=limit, filters=filters, **filter_values)

    def get_media(
        self,
        media_id: int | str | None = None,
        *,
        media_path: str | None = None,
        corpus_id: str = DEFAULT_CORPUS_ID,
    ) -> dict[str, object] | None:
        """Return one media item by canonical/legacy id or path."""

        if media_id is None and media_path is None:
            return None
        where = ["m.corpus_id = ?"]
        params: list[object] = [corpus_id]
        if media_id is not None:
            where.append("(m.legacy_id = ? OR m.id = ?)")
            params.extend([_as_int_or_none(media_id), str(media_id)])
        if media_path is not None:
            where.append("m.path = ?")
            params.append(media_path)
        row = self.db.conn.execute(
            f"""
            SELECT m.*
            FROM media_items m
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return _media_shape(row)

    def get_scene_context(self, chunk_id: int | str, window: int = 2) -> dict[str, object] | None:
        """Return the matching chunk plus before/after chunks in document order."""

        current = self._chunk_row(chunk_id)
        if current is None:
            return None
        safe_window = max(0, int(window))
        before = self._context_rows(current, direction="before", limit=safe_window)
        after = self._context_rows(current, direction="after", limit=safe_window)
        before = list(reversed(before))
        current_shape = self._chunk_shape(current)
        before_shapes = [self._chunk_shape(row) for row in before]
        after_shapes = [self._chunk_shape(row) for row in after]
        evidence = before_shapes + [current_shape] + after_shapes
        return {
            "chunk_id": current_shape["chunk_id"],
            "media": _media_shape(current),
            "before": before_shapes,
            "current": current_shape,
            "after": after_shapes,
            "evidence": evidence,
            "context": "\n".join(str(item["text"]) for item in evidence),
        }

    def _fts_rows(
        self,
        normalized_query: str,
        filters: SearchFilters,
        *,
        limit: int,
        preferred_source_kinds: set[str],
        require_timestamps: bool = False,
    ) -> list[sqlite3.Row]:
        fts_query = to_fts_query(normalized_query)
        if not fts_query:
            return []
        clauses, params = _filter_clauses(filters)
        if require_timestamps:
            clauses.append("c.start_ms IS NOT NULL")
        sql = f"""
            SELECT c.legacy_id AS chunk_id,
                   c.id AS stable_chunk_id,
                   c.corpus_id AS corpus_id,
                   c.document_id AS document_id,
                   c.media_item_id AS media_id,
                   c.chunk_index AS chunk_index,
                   c.text AS text,
                   c.normalized_text AS normalized_text,
                   c.start_ms AS start_ms,
                   c.end_ms AS end_ms,
                   c.start_seconds AS start_seconds,
                   c.end_seconds AS end_seconds,
                   c.media_path AS chunk_media_path,
                   c.subtitle_path AS subtitle_path,
                   c.source_kind AS chunk_source_kind,
                   c.language AS language,
                   d.source_kind AS document_source_kind,
                    d.source_path AS source_path,
                    d.source_uri AS source_uri,
                    d.provider_ids_json AS document_provider_ids_json,
                    d.provider_refs_json AS document_provider_refs_json,
                    d.checksum AS document_checksum,
                   m.id AS stable_media_id,
                   m.legacy_id AS media_legacy_id,
                   m.path AS media_path,
                   m.title AS title,
                   m.kind AS kind,
                   m.show_title AS show_title,
                   m.season AS season,
                   m.episode AS episode,
                   m.season_number AS season_number,
                   m.episode_number AS episode_number,
                   m.episode_title AS episode_title,
                   m.year AS year,
                   m.provider_ids_json AS media_provider_ids_json,
                   bm25(chunks_fts) * -1.0 AS lexical_score
            FROM chunks_fts
            JOIN chunks c ON c.legacy_id = chunks_fts.rowid
            JOIN media_items m ON m.id = c.media_item_id
            JOIN documents d ON d.id = c.document_id
            WHERE chunks_fts MATCH ? AND {" AND ".join(clauses)}
            ORDER BY bm25(chunks_fts),
                     CASE WHEN c.start_ms IS NULL THEN 1 ELSE 0 END,
                     c.start_ms,
                     c.legacy_id
            LIMIT ?
        """
        rows = list(self.db.conn.execute(sql, [fts_query, *params, limit]))
        if preferred_source_kinds:
            rows.sort(
                key=lambda row: (
                    self._rank(
                        row, query=normalized_query, preferred_source_kinds=preferred_source_kinds
                    ).combined_score,
                    row["start_ms"] is not None,
                ),
                reverse=True,
            )
        return rows

    def _group_media_results(
        self,
        rows: list[sqlite3.Row],
        limit: int,
        *,
        preferred_source_kinds: set[str],
        query: str,
    ) -> list[SearchResult]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "row": None,
                "lexical": 0.0,
                "combined": 0.0,
                "confidence": 0.0,
                "why": [],
                "evidences": [],
            }
        )
        for row in rows:
            key = str(row["stable_media_id"])
            entry = grouped[key]
            signals = self._rank(row, query=query, preferred_source_kinds=preferred_source_kinds)
            score = signals.combined_score
            if entry["row"] is None or score > float(entry["combined"]):
                entry["row"] = row
                entry["why"] = signals.why
                entry["confidence"] = signals.confidence
            entry["lexical"] = max(float(entry["lexical"]), float(row["lexical_score"] or 0.0))
            entry["combined"] = max(float(entry["combined"]), score)
            entry["evidences"].append(self._evidence(row, score=score))

        results: list[SearchResult] = []
        for entry in grouped.values():
            row = entry["row"]
            if row is None:
                continue
            evidences = sorted(
                entry["evidences"],
                key=lambda evidence: evidence.score,
                reverse=True,
            )[:5]
            results.append(
                SearchResult(
                    id=str(row["stable_media_id"]),
                    corpus_id=str(row["corpus_id"]),
                    media_id=str(row["stable_media_id"]),
                    media_path=str(row["media_path"]),
                    title=str(row["title"]),
                    kind=row["kind"],
                    show_title=row["show_title"],
                    season=row["season"],
                    episode=row["episode"],
                    season_number=row["season_number"],
                    episode_number=row["episode_number"],
                    episode_title=row["episode_title"],
                    year=row["year"],
                    provider_ids=_json_dict(row["media_provider_ids_json"]),
                    combined_score=float(entry["combined"]),
                    lexical_score=float(entry["lexical"]),
                    vector_score=0.0,
                    confidence=float(entry["confidence"]),
                    why=list(entry["why"]),
                    evidences=evidences,
                )
            )
        results.sort(key=lambda result: result.combined_score, reverse=True)
        return results[:limit]

    def _scene_shape(self, row: sqlite3.Row, *, query: str) -> dict[str, object]:
        normalized_query = normalize_query(query)
        signals = self._rank(
            row,
            query=normalized_query,
            preferred_source_kinds={"subtitle", "srt", "caption", "subtitles"},
        )
        score = signals.combined_score
        evidence = self._chunk_shape(row) | {"score": score}
        why = "; ".join(signals.why) if signals.why else "Matched indexed text"
        return {
            "query": normalized_query,
            "media": _media_shape(row),
            "chunk_id": row["chunk_id"],
            "confidence": signals.confidence,
            "why": why,
            "evidence": evidence,
            "results": [evidence],
        }

    def _evidence(self, row: sqlite3.Row, *, score: float) -> SearchEvidence:
        return SearchEvidence(
            chunk_id=row["chunk_id"],
            text=str(row["text"]),
            score=score,
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            corpus_id=str(row["corpus_id"]),
            media_id=str(row["stable_media_id"]),
            document_id=str(row["document_id"]),
            media_path=str(row["media_path"]),
            subtitle_path=row["subtitle_path"],
            normalized_text=row["normalized_text"],
            start_seconds=row["start_seconds"],
            end_seconds=row["end_seconds"],
            source_kind=row["document_source_kind"] or row["chunk_source_kind"],
            source_provider=_source_provider(row),
            source_path=row["source_path"],
            source_uri=row["source_uri"],
            provider_ids=_json_dict(row["document_provider_ids_json"]),
            checksum=row["document_checksum"],
        )

    def _rank(
        self, row: sqlite3.Row, *, query: str, preferred_source_kinds: set[str]
    ) -> RankingSignals:
        lexical_raw = float(row["lexical_score"] or 0.0)
        lexical_score = normalize_fts_score(lexical_raw)
        metadata_scores: list[float] = []
        why: list[str] = []

        source_kind = str(row["document_source_kind"] or row["chunk_source_kind"] or "")
        if source_kind:
            why.append(f"matched {source_kind} source")
            if source_kind.casefold() in preferred_source_kinds:
                metadata_scores.append(0.35)

        query_terms, quoted_phrases = _query_terms_and_phrases(query)
        text = str(row["normalized_text"] or row["text"] or "").casefold()
        text_tokens = set(_WORD_RE.findall(text))
        title_text = " ".join(
            str(value or "") for value in (row["title"], row["show_title"], row["episode_title"])
        ).casefold()
        title_tokens = set(_WORD_RE.findall(title_text))
        matched_terms = [term for term in query_terms if term in text_tokens]
        if matched_terms:
            metadata_scores.append(min(0.20, 0.04 * len(matched_terms)))
            why.append("matched query terms: " + ", ".join(matched_terms[:5]))
        exact_phrases = [phrase for phrase in quoted_phrases if phrase in text]
        if exact_phrases:
            metadata_scores.append(0.35)
            why.append("matched exact phrase: " + "; ".join(exact_phrases[:2]))
        title_matches = [term for term in query_terms if term in title_tokens]
        if title_matches:
            metadata_scores.append(0.25)
            why.append("matched title/show: " + ", ".join(title_matches[:5]))
        if row["start_ms"] is not None:
            metadata_scores.append(
                0.15
                if source_kind.casefold() in {"subtitle", "srt", "caption", "subtitles"}
                else 0.05
            )
            why.append(f"matched timestamp metadata at {_format_ms(int(row['start_ms']))}")

        metadata_score = metadata_confidence(metadata_scores)
        combined_score = combine_structured_scores(
            lexical_score=lexical_score,
            metadata_score=metadata_score,
            vector_score=None,
        )
        confidence = max(lexical_score, combined_score)
        return RankingSignals(
            combined_score=combined_score,
            lexical_score=lexical_score,
            vector_score=0.0,
            metadata_score=metadata_score,
            confidence=confidence,
            why=why,
        )

    def _chunk_row(self, chunk_id: int | str) -> sqlite3.Row | None:
        return self.db.conn.execute(
            """
            SELECT c.legacy_id AS chunk_id,
                   c.id AS stable_chunk_id,
                   c.corpus_id AS corpus_id,
                   c.document_id AS document_id,
                   c.media_item_id AS media_id,
                   c.chunk_index AS chunk_index,
                   c.text AS text,
                   c.normalized_text AS normalized_text,
                   c.start_ms AS start_ms,
                   c.end_ms AS end_ms,
                   c.start_seconds AS start_seconds,
                   c.end_seconds AS end_seconds,
                   c.media_path AS chunk_media_path,
                   c.subtitle_path AS subtitle_path,
                   c.source_kind AS chunk_source_kind,
                   c.language AS language,
                   m.id AS stable_media_id,
                   m.legacy_id AS media_legacy_id,
                   m.path AS media_path,
                   m.title AS title,
                   m.kind AS kind,
                   m.show_title AS show_title,
                   m.season AS season,
                   m.episode AS episode,
                   m.season_number AS season_number,
                   m.episode_number AS episode_number,
                   m.episode_title AS episode_title,
                   m.year AS year,
                   m.provider_ids_json AS media_provider_ids_json
            FROM chunks c
            JOIN media_items m ON m.id = c.media_item_id
            WHERE c.legacy_id = ? OR c.id = ?
            LIMIT 1
            """,
            (_as_int_or_none(chunk_id), str(chunk_id)),
        ).fetchone()

    def _context_rows(
        self, current: sqlite3.Row, *, direction: str, limit: int
    ) -> list[sqlite3.Row]:
        if limit == 0:
            return []
        comparator = "<" if direction == "before" else ">"
        ordering = "DESC" if direction == "before" else "ASC"
        return list(
            self.db.conn.execute(
                f"""
                SELECT c.legacy_id AS chunk_id,
                       c.id AS stable_chunk_id,
                       c.corpus_id AS corpus_id,
                       c.document_id AS document_id,
                       c.media_item_id AS media_id,
                       c.chunk_index AS chunk_index,
                       c.text AS text,
                       c.normalized_text AS normalized_text,
                       c.start_ms AS start_ms,
                       c.end_ms AS end_ms,
                       c.start_seconds AS start_seconds,
                       c.end_seconds AS end_seconds,
                       c.media_path AS chunk_media_path,
                       c.subtitle_path AS subtitle_path,
                       c.source_kind AS chunk_source_kind,
                       c.language AS language,
                       m.id AS stable_media_id,
                       m.legacy_id AS media_legacy_id,
                       m.path AS media_path,
                       m.title AS title,
                       m.kind AS kind,
                       m.show_title AS show_title,
                       m.season AS season,
                       m.episode AS episode,
                       m.season_number AS season_number,
                       m.episode_number AS episode_number,
                       m.episode_title AS episode_title,
                       m.year AS year,
                       m.provider_ids_json AS media_provider_ids_json
                FROM chunks c
                JOIN media_items m ON m.id = c.media_item_id
                WHERE c.document_id = ? AND c.chunk_index {comparator} ?
                ORDER BY c.chunk_index {ordering}, c.legacy_id {ordering}
                LIMIT ?
                """,
                (current["document_id"], current["chunk_index"], limit),
            )
        )

    def _chunk_shape(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "chunk_id": row["chunk_id"],
            "stable_chunk_id": row["stable_chunk_id"],
            "text": row["text"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "start_seconds": row["start_seconds"],
            "end_seconds": row["end_seconds"],
            "media_path": row["media_path"],
            "subtitle_path": row["subtitle_path"],
            "source_kind": row["chunk_source_kind"],
        }

    def _cache_key(self, normalized_query: str, filters: SearchFilters, *, mode: str) -> str:
        filters_json = json.dumps(filters.to_dict(), sort_keys=True, separators=(",", ":"))
        raw = f"v{SCHEMA_VERSION}:rank{_CACHE_RANKING_VERSION}:{mode}:{normalized_query}:{filters_json}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_cached_results(self, cache_key: str) -> list[SearchResult] | None:
        if not self.use_cache:
            return None
        row = self.db.conn.execute(
            "SELECT result_json FROM search_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["result_json"]))
        except json.JSONDecodeError:
            return None
        return _SEARCH_RESULT_LIST.validate_python(payload)

    def _set_cached_results(
        self,
        cache_key: str,
        normalized_query: str,
        filters: SearchFilters,
        results: list[SearchResult],
    ) -> None:
        if not self.use_cache:
            return
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO search_cache(cache_key, corpus_id, query, filters_json, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                cache_key,
                filters.corpus_id,
                normalized_query,
                json.dumps(filters.to_dict(), sort_keys=True),
                json.dumps([result.to_dict() for result in results]),
            ),
        )
        self.db.conn.commit()


def normalize_query(query: str) -> str:
    """Normalize user search text before FTS/cache use."""

    return " ".join(query.casefold().strip().split())


def to_fts_query(normalized_query: str) -> str:
    """Build a conservative FTS5 query, preserving quoted phrase searches."""

    tokens = _TOKEN_RE.findall(normalized_query)
    clean_tokens = [_clean_fts_token(token) for token in tokens]
    clean_tokens = [token for token in clean_tokens if token]
    if not clean_tokens:
        return ""
    return " AND ".join(clean_tokens)


def _clean_fts_token(token: str) -> str:
    if token.startswith('"') and token.endswith('"'):
        phrase_terms = _WORD_RE.findall(token.strip('"'))
        if not phrase_terms:
            return ""
        return '"' + " ".join(phrase_terms) + '"'

    has_trailing_wildcard = token.endswith("*")
    term = token.rstrip("*")
    if "*" in term:
        term = term.replace("*", "")
        has_trailing_wildcard = False
    term = "".join(_WORD_RE.findall(term))
    if not term:
        return ""
    return f"{term}*" if has_trailing_wildcard else term


def _query_terms_and_phrases(normalized_query: str) -> tuple[list[str], list[str]]:
    tokens = _TOKEN_RE.findall(normalized_query)
    terms: list[str] = []
    phrases: list[str] = []
    for token in tokens:
        clean = token.strip('"*').casefold()
        clean_parts = _WORD_RE.findall(clean)
        clean = " ".join(clean_parts)
        if not clean:
            continue
        if token.startswith('"') and token.endswith('"'):
            phrases.append(clean)
            terms.extend(clean_parts)
        else:
            terms.extend(clean_parts)
    deduped_terms = list(dict.fromkeys(terms))
    if len(deduped_terms) > 1:
        phrases.append(" ".join(deduped_terms))
    return deduped_terms, list(dict.fromkeys(phrases))


def _merge_filters(
    filters: SearchFilters | None,
    filter_values: dict[str, object],
    *,
    limit: int,
) -> SearchFilters:
    data: dict[str, object] = filters.to_dict() if filters is not None else {}
    data.update({key: value for key, value in filter_values.items() if value is not None})
    data.setdefault("limit", limit)
    return SearchFilters.model_validate(data)


def _limit_from_filters(filters: SearchFilters, fallback: int) -> int:
    return max(1, min(100, int(filters.limit or fallback)))


def _filter_clauses(filters: SearchFilters) -> tuple[list[str], list[object]]:
    clauses = ["c.corpus_id = ?"]
    params: list[object] = [filters.corpus_id]
    exact_fields = {
        "media_id": "m.id",
        "media_path": "m.path",
        "kind": "m.kind",
        "season": "m.season",
        "episode": "m.episode",
        "season_number": "m.season_number",
        "episode_number": "m.episode_number",
        "year": "m.year",
        "language": "c.language",
    }
    for field, column in exact_fields.items():
        value = getattr(filters, field)
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if filters.media_id is not None:
        clauses[-1] = "(m.id = ? OR m.legacy_id = ?)"
        params[-1] = str(filters.media_id)
        params.append(_as_int_or_none(filters.media_id))
    if filters.title is not None:
        clauses.append("(m.title LIKE ? OR m.episode_title LIKE ?)")
        params.extend([f"%{filters.title}%", f"%{filters.title}%"])
    show = filters.show or filters.show_title
    if show is not None:
        clauses.append("(m.show_title LIKE ? OR m.title LIKE ?)")
        params.extend([f"%{show}%", f"%{show}%"])
    source_kind = filters.source_kind or filters.source_type
    if source_kind is not None:
        clauses.append("(c.source_kind = ? OR d.source_kind = ?)")
        params.extend([source_kind, source_kind])
    if filters.source_provider is not None:
        clauses.append("(m.provider_ids_json LIKE ? OR d.provider_ids_json LIKE ?)")
        params.extend([f'%"{filters.source_provider}"%', f'%"{filters.source_provider}"%'])
    for provider, provider_id in filters.provider_ids.items():
        clauses.append(
            "(m.provider_ids_json LIKE ? OR m.provider_ids_json LIKE ? "
            "OR d.provider_ids_json LIKE ? OR d.provider_ids_json LIKE ?)"
        )
        needle = f'%"{provider}": "{provider_id}"%'
        compact_needle = f'%"{provider}":"{provider_id}"%'
        params.extend([needle, compact_needle, needle, compact_needle])
    return clauses, params


def _media_shape(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["stable_media_id"] if "stable_media_id" in row.keys() else row["id"],
        "legacy_id": row["media_legacy_id"]
        if "media_legacy_id" in row.keys()
        else row["legacy_id"],
        "corpus_id": row["corpus_id"],
        "path": row["media_path"] if "media_path" in row.keys() else row["path"],
        "title": row["title"],
        "kind": row["kind"],
        "show_title": row["show_title"],
        "season": row["season"],
        "episode": row["episode"],
        "season_number": row["season_number"],
        "episode_number": row["episode_number"],
        "episode_title": row["episode_title"],
        "year": row["year"],
        "provider_ids": _json_dict(
            row["media_provider_ids_json"]
            if "media_provider_ids_json" in row.keys()
            else row["provider_ids_json"]
        ),
    }


def _json_dict(value: object) -> dict[str, str]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(val) for key, val in loaded.items()}


def _source_provider(row: sqlite3.Row) -> str | None:
    provider_ids = _json_dict(
        row["document_provider_ids_json"] if "document_provider_ids_json" in row.keys() else None
    )
    return provider_ids.get("source_provider") or provider_ids.get("provider")


def _as_int_or_none(value: int | str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_ms(value: int) -> str:
    total_seconds = value // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
