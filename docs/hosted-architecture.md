# Hosted architecture roadmap (future design)

This repository is intentionally local-first in MVP. The design below is **future and not implemented** in code yet.

## Design principle

- Preserve current SQLite/FTS + corpus-aware schema as the canonical local data model.
- Reuse existing `SearchFilters`, `SearchService`, and deterministic IDs when moving to multi-tenant hosted workloads.
- Keep tenant boundaries explicit and auditable via `app.corpus_id` and per-record `corpus_id`.

## Proposed future service layout

### Ingress/API surface
- FastAPI/HTTP entry point behind an API gateway (optional) for non-MCP clients.
- MCP continues to be supported as an adapter layer over the same service components.
- Optional Discord/other bot adapters continue to consume REST as thin clients.

### Container runtime
- Docker image stays the same local image.
- Deploy to AWS ECS on Fargate using one service per role:
  - `ingest-worker` for scan/fetch/enrich jobs.
  - `search-api` for read/query endpoints.
  - Optional `maintenance` task for cache repair/rebuild.

### Message and job orchestration
- Amazon SQS as a simple job bus:
  - `scan-jobs`, `metadata-enrich-jobs`, `subtitle-ingest-jobs`, `rebuild-index-jobs`.
- Worker tasks pull by queue with lease+retry+dead-letter semantics.

### Storage and persistence
- PostgreSQL on RDS for metadata and search cache/state tables (future migration target).
- Keep corpus and source identifiers in every request/job payload and DB row.
- Object storage in S3 for:
  - Uploaded media/subtitle artifacts and provider sidecars.
  - Optional persisted generated manifests/checkpoints and raw provider payload archives.

### Vector and semantic retrieval
- Keep current local embedding abstraction and swap vector store implementation by configuration:
  - PostgreSQL + `pgvector` for consolidated metadata+vector operations, or
  - Qdrant for dedicated vector service, or
  - OpenSearch kNN for managed managed search+semantic stack.

### Cache layer
- Redis (ElastiCache) for hot query cache, queue coordination, and short-lived rate limiting buckets.
- Cache keys must continue to include `corpus_id` so tenant isolation remains strict.

## Hosted concerns (future, non-goals for MVP)

- Tenant/account management, authN/authZ, and billing integration.
- Public/unauthenticated MCP endpoint exposure.
- Automatic activation of external providers (Plex/OpenSubtitles/Bazarr/OpenAI).
- Public credentials management beyond secret store integration (AWS Secrets Manager / SSM Parameter Store).

## Transition requirement when implemented

- Search and filter paths must continue to enforce corpus/tenant scope at query layer:
  - `SearchFilters.corpus_id` in API/MCP payload paths.
  - Cache keys and persisted artifacts remain tenant-scoped.
- All migration steps remain backward-compatible with existing local sqlite-backed development data and fixtures.
