from __future__ import annotations

import argparse
import json
from pathlib import Path

from media_memory.core.db import MediaMemoryDB
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.core.search import SearchService
from media_memory.core.vector_store import LanceDBVectorStore
from media_memory.ingest.indexer import IngestService
from media_memory.ingest.scanner import scan_media
from media_memory.mcp_server.tools import create_server


def _build_services(db_path: Path) -> tuple[MediaMemoryDB, SearchService, IngestService]:
    db = MediaMemoryDB(db_path)
    db.init_schema()
    embeddings = MockEmbeddingProvider()
    vectors = LanceDBVectorStore()
    for row in db.list_all_chunks():
        vectors.upsert(int(row["chunk_id"]), embeddings.embed(str(row["text"])))
    return db, SearchService(db, embeddings, vectors), IngestService(db, embeddings, vectors)


def main() -> None:
    parser = argparse.ArgumentParser(prog="media-memory")
    parser.add_argument("--db", default=".media_memory/media_memory.db", help="SQLite DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan", help="Scan local media files")
    scan_cmd.add_argument("media_root", type=Path)

    ingest_cmd = sub.add_parser("ingest", help="Scan and index media/subtitles")
    ingest_cmd.add_argument("media_root", type=Path)

    search_cmd = sub.add_parser("search", help="Search indexed subtitles")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=10)

    mcp_cmd = sub.add_parser("mcp-call", help="Call an MCP tool locally")
    mcp_cmd.add_argument("tool_name", choices=["search_media", "find_episode", "find_scene", "search_dialogue", "get_scene_context"])
    mcp_cmd.add_argument("--params", default="{}", help='JSON dictionary of tool params, e.g. {"query":"hello"}')

    args = parser.parse_args()
    db_path = Path(args.db)

    if args.command == "scan":
        media_items = scan_media(args.media_root)
        print(json.dumps([item.__dict__ | {"path": str(item.path)} for item in media_items], indent=2))
        return

    if args.command == "mcp-call":
        server = create_server(db_path)
        params = json.loads(args.params)
        print(json.dumps(server.call_tool(args.tool_name, **params), indent=2))
        return

    db, search, ingest = _build_services(db_path)
    try:
        if args.command == "ingest":
            stats = ingest.ingest_media_items(scan_media(args.media_root))
            print(json.dumps(stats, indent=2))
            return
        if args.command == "search":
            print(json.dumps([item.to_dict() for item in search.search_media(args.query, limit=args.limit)], indent=2))
            return
    finally:
        db.close()


if __name__ == "__main__":
    main()
