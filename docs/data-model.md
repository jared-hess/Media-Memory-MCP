# Data model

The codebase uses corpus-aware Pydantic domain models with deterministic stable IDs and a durable SQLite schema. FTS and vector indexes are derived from the canonical SQLite records and can be rebuilt.

## Current concepts

- Media item: local filesystem media path with basic title/kind/season/episode fields.
- Subtitle chunk: normalized subtitle text with optional timestamps and episode hints.
- Search evidence: matched subtitle text with scores and timestamps.
- Search result: media-level result containing ranked evidence entries.

## Durable model boundaries

Persisted and search-facing records include `corpus_id`. The default corpus is configured as `app.corpus_id: local` in `config.example.yaml`, with local metadata stored at `index.sqlite_path: /data/media-memory.sqlite`.

Durable concepts include:

- Corpus-scoped media records.
- Subtitle or metadata documents linked to media.
- Stable chunks with deterministic IDs.
- Ingest jobs and provider references.
- Rebuildable lexical and vector indexes derived from source records, with `index.metadata_db`, `index.sqlite_path`, `index.vector_db`, and `index.vector_path` documenting the intended storage backends.

## Provider data

Plex IDs, OpenSubtitles references, Bazarr metadata, and OpenAI embedding metadata are supported only through explicitly enabled optional integrations. Hosted tenant fields remain future architecture documentation rather than active runtime behavior.
