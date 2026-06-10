# Data model scaffold

The current codebase still uses the Task 1 scaffold models. A later task will replace them with corpus-aware durable domain models and stable IDs.

## Current concepts

- Media item: local filesystem media path with basic title/kind/season/episode fields.
- Subtitle chunk: normalized subtitle text with optional timestamps and episode hints.
- Search evidence: matched subtitle text with scores and timestamps.
- Search result: media-level result containing ranked evidence entries.

## Planned durable model boundaries

Future model work should add `corpus_id` to persisted and search-facing records. The default corpus is configured as `app.corpus_id: local` in `config.example.yaml`, with local metadata stored at `index.sqlite_path: /data/media-memory.sqlite` when later schema work consumes the config.

Expected durable concepts include:

- Corpus-scoped media records.
- Subtitle or metadata documents linked to media.
- Stable chunks with deterministic IDs.
- Ingest jobs and provider references.
- Rebuildable lexical and vector indexes derived from source records, with `index.metadata_db`, `index.sqlite_path`, `index.vector_db`, and `index.vector_path` documenting the intended storage backends.

## Deferred provider data

Plex IDs, OpenSubtitles references, Bazarr metadata, hosted tenant fields, and OpenAI embedding metadata are deferred until their integrations are implemented and explicitly enabled.
