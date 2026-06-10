from __future__ import annotations

from collections import defaultdict

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import EmbeddingProvider
from media_memory.core.models import SearchEvidence, SearchResult
from media_memory.core.ranking import combine_scores
from media_memory.core.vector_store import VectorStore


class SearchService:
    def __init__(self, db: MediaMemoryDB, embeddings: EmbeddingProvider, vectors: VectorStore):
        self.db = db
        self.embeddings = embeddings
        self.vectors = vectors

    def search_media(self, query: str, limit: int = 10) -> list[SearchResult]:
        lexical_rows = self.db.lexical_search(query, limit=max(limit * 4, 20))
        vector_hits = self.vectors.search(self.embeddings.embed(query), limit=max(limit * 4, 20))
        vector_scores = {chunk_id: score for chunk_id, score in vector_hits}

        grouped: dict[str, dict[str, object]] = defaultdict(lambda: {
            "title": "",
            "lexical": 0.0,
            "vector": 0.0,
            "evidences": [],
        })

        for row in lexical_rows:
            media_path = str(row["media_path"])
            entry = grouped[media_path]
            entry["title"] = str(row["title"])
            lexical_score = float(row["lexical_score"])
            vector_score = float(vector_scores.get(int(row["chunk_id"]), 0.0))
            entry["lexical"] = max(float(entry["lexical"]), lexical_score)
            entry["vector"] = max(float(entry["vector"]), vector_score)
            entry["evidences"].append(
                SearchEvidence(
                    chunk_id=int(row["chunk_id"]),
                    text=str(row["text"]),
                    score=combine_scores(lexical_score, vector_score),
                    start_ms=row["start_ms"],
                    end_ms=row["end_ms"],
                )
            )

        for chunk_id, vector_score in vector_hits:
            if any(int(row["chunk_id"]) == chunk_id for row in lexical_rows):
                continue
            row = self.db.get_chunk_by_id(chunk_id)
            if row is None:
                continue
            media_path = str(row["media_path"])
            entry = grouped[media_path]
            entry["title"] = str(row["title"])
            entry["vector"] = max(float(entry["vector"]), float(vector_score))
            entry["evidences"].append(
                SearchEvidence(
                    chunk_id=chunk_id,
                    text=str(row["text"]),
                    score=combine_scores(0.0, float(vector_score)),
                    start_ms=row["start_ms"],
                    end_ms=row["end_ms"],
                )
            )

        results = []
        for media_path, data in grouped.items():
            lexical_score = float(data["lexical"])
            vector_score = float(data["vector"])
            results.append(
                SearchResult(
                    media_path=media_path,
                    title=str(data["title"]),
                    combined_score=combine_scores(lexical_score, vector_score),
                    lexical_score=lexical_score,
                    vector_score=vector_score,
                    evidences=sorted(data["evidences"], key=lambda item: item.score, reverse=True)[:3],
                )
            )

        results.sort(key=lambda item: item.combined_score, reverse=True)
        return results[:limit]

    def find_episode(self, query: str, season: int | None = None, episode: int | None = None) -> list[SearchResult]:
        results = self.search_media(query, limit=20)
        if season is None and episode is None:
            return results
        filtered = []
        season_token = f"s{season:02d}" if season is not None else None
        episode_token = f"e{episode:02d}" if episode is not None else None
        for result in results:
            candidate = result.media_path.lower()
            if season_token and season_token not in candidate:
                continue
            if episode_token and episode_token not in candidate:
                continue
            filtered.append(result)
        return filtered

    def find_scene(self, query: str, media_path: str | None = None, limit: int = 10) -> list[dict[str, object]]:
        results = self.search_media(query, limit=limit * 2)
        scenes: list[dict[str, object]] = []
        for result in results:
            if media_path and result.media_path != media_path:
                continue
            for evidence in result.evidences:
                scenes.append(
                    {
                        "media_path": result.media_path,
                        "title": result.title,
                        "chunk_id": evidence.chunk_id,
                        "text": evidence.text,
                        "score": evidence.score,
                        "start_ms": evidence.start_ms,
                        "end_ms": evidence.end_ms,
                    }
                )
        scenes.sort(key=lambda item: float(item["score"]), reverse=True)
        return scenes[:limit]

    def search_dialogue(self, query: str, limit: int = 10) -> list[dict[str, object]]:
        return self.find_scene(query=query, limit=limit)

    def get_scene_context(self, chunk_id: int, window: int = 2) -> dict[str, object] | None:
        center = self.db.get_chunk_by_id(chunk_id)
        if center is None:
            return None
        media_path = str(center["media_path"])
        chunks = self.db.list_chunks_for_media(media_path, limit=500)
        chunk_ids = [int(row["chunk_id"]) for row in chunks]
        if chunk_id not in chunk_ids:
            return None
        idx = chunk_ids.index(chunk_id)
        start = max(0, idx - window)
        end = min(len(chunks), idx + window + 1)
        context = [
            {
                "chunk_id": int(row["chunk_id"]),
                "text": str(row["text"]),
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
            for row in chunks[start:end]
        ]
        return {
            "media_path": media_path,
            "title": str(center["title"]),
            "focus_chunk_id": chunk_id,
            "context": context,
        }
