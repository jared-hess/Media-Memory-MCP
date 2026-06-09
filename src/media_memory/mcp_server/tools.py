from __future__ import annotations

from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceDBVectorStore
from media_memory.mcp_server.server import MediaMemoryMCPServer


def create_server(db_path: Path) -> MediaMemoryMCPServer:
    db = MediaMemoryDB(db_path)
    db.init_schema()
    embeddings = MockEmbeddingProvider()
    vectors = LanceDBVectorStore()
    for row in db.list_all_chunks():
        vectors.upsert(int(row["chunk_id"]), embeddings.embed(str(row["text"])))
    search_service = SearchService(
        db=db,
        embeddings=embeddings,
        vectors=vectors,
    )
    return MediaMemoryMCPServer(search_service=search_service)
