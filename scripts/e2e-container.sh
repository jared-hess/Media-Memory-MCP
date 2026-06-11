#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="${IMAGE_TAG:-media-memory-mcp:e2e}"
SKIP_BUILD="${SKIP_BUILD:-0}"
KEEP_E2E_TMP="${KEEP_E2E_TMP:-0}"
CONTAINER_UID="10001"
CONTAINER_GID="10001"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURE_MEDIA="${REPO_ROOT}/tests/fixtures/media"
TMP_ROOT="$(mktemp -d -t media-memory-e2e.XXXXXX)"
CONFIG_DIR="${TMP_ROOT}/config"
MEDIA_DIR="${TMP_ROOT}/media"
DATA_DIR="${TMP_ROOT}/data"
OUTPUT_DIR="${TMP_ROOT}/outputs"

cleanup() {
  if [[ "${KEEP_E2E_TMP}" == "1" ]]; then
    echo "KEEP_E2E_TMP=1"
    echo "Temp root preserved: ${TMP_ROOT}"
    echo "Cleanup command: docker run --rm --user 0:0 -v '${TMP_ROOT}:/e2e-tmp:rw' '${IMAGE_TAG}' chown -R $(id -u):$(id -g) /e2e-tmp && rm -rf '${TMP_ROOT}'"
    return
  fi
  if ! rm -rf "${TMP_ROOT}" 2>/dev/null; then
    docker run --rm --user 0:0 --volume "${TMP_ROOT}:/e2e-tmp:rw" "${IMAGE_TAG}" chown -R "$(id -u):$(id -g)" /e2e-tmp
    rm -rf "${TMP_ROOT}"
  fi
}
trap cleanup EXIT

log() {
  printf '\n==> %s\n' "$1"
}

docker_run() {
  docker run --rm \
    --volume "${CONFIG_DIR}:/config:ro" \
    --volume "${MEDIA_DIR}:/media:ro" \
    --volume "${DATA_DIR}:/data:rw" \
    "${IMAGE_TAG}" "$@"
}

assert_json() {
  local label="$1"
  local file_path="$2"
  local expression="$3"

  python3 - "$label" "$file_path" "$expression" <<'PY'
import json
import sys
from pathlib import Path

label, file_path, expression = sys.argv[1:4]
payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
safe_globals = {
    "__builtins__": {},
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "dict": dict,
}
if not eval(expression, safe_globals, {"payload": payload}):
    raise SystemExit(f"Assertion failed for {label}: {expression}\nPayload: {payload!r}")
print(f"ASSERT PASS: {label}")
PY
}

assert_file_contains() {
  local label="$1"
  local file_path="$2"
  local needle="$3"

  python3 - "$label" "$file_path" "$needle" <<'PY'
import sys
from pathlib import Path

label, file_path, needle = sys.argv[1:4]
text = Path(file_path).read_text(encoding="utf-8")
if needle not in text:
    raise SystemExit(f"Assertion failed for {label}: missing {needle!r} in {file_path}")
print(f"ASSERT PASS: {label}")
PY
}

log "Container E2E setup"
echo "Image tag: ${IMAGE_TAG}"
echo "Temp root: ${TMP_ROOT}"
echo "Config dir: ${CONFIG_DIR}"
echo "Media dir: ${MEDIA_DIR}"
echo "Data dir: ${DATA_DIR}"

if [[ "${SKIP_BUILD}" == "1" ]]; then
  log "Skipping image build because SKIP_BUILD=1"
else
  log "Building image ${IMAGE_TAG}"
  docker build -t "${IMAGE_TAG}" "${REPO_ROOT}"
fi

log "Preparing temp config, media, and data"
mkdir -p "${CONFIG_DIR}" "${MEDIA_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}"
cp -R "${FIXTURE_MEDIA}/." "${MEDIA_DIR}/"

cat > "${CONFIG_DIR}/config.yaml" <<'YAML'
app:
  name: media-memory-mcp
  environment: local
  data_dir: /data
  log_level: info
  corpus_id: local

mcp:
  transport: stdio
  allow_ingest_tools: false
  read_only_resources: true

api:
  enabled: false
  host: 127.0.0.1
  port: 8765

discord:
  enabled: false
  token: ${DISCORD_BOT_TOKEN}
  api_base_url: http://127.0.0.1:8765
  default_limit: 3

media_sources:
  - type: filesystem
    enabled: true
    name: e2e-fixture-media
    roots:
      - /media
    read_only: true
    extensions:
      - .mkv
      - .mp4
      - .avi
      - .mov
  - type: plex
    enabled: false
    url: ${PLEX_BASE_URL}
    token: ${PLEX_TOKEN}
    libraries: []

subtitle_sources:
  local:
    enabled: true
    roots:
      - /media
    sidecar_extensions:
      - .srt
      - .vtt
      - .ass
      - .ssa
    read_only: true
  embedded:
    enabled: false
    extract_with_ffmpeg: false
    extract_to: /data/subtitles/embedded
    languages:
      - eng
      - en
  opensubtitles:
    enabled: false
    api_key: ${OPENSUBTITLES_API_KEY}
    username: ${OPENSUBTITLES_USERNAME}
    password: ${OPENSUBTITLES_PASSWORD}
    languages:
      - eng
      - en
    hearing_impaired: false
    daily_download_budget: 0
    min_match_confidence: 0.85
    cache_dir: /data/subtitles/opensubtitles
  bazarr:
    enabled: false
    url: ${BAZARR_BASE_URL}
    api_key: ${BAZARR_API_KEY}
    api_enabled: false
    roots:
      - /bazarr
    sidecar_extensions:
      - .srt
      - .vtt
      - .ass
      - .ssa

metadata:
  prefer:
    - filename
  fetch_external: false

embeddings:
  provider: mock
  model: mock
  batch_size: 128
  api_key: ${OPENAI_API_KEY}
  dimensions: 16

index:
  metadata_db: sqlite
  sqlite_path: /data/media-memory.sqlite
  vector_db: lancedb
  vector_path: /data/vectors

search:
  default_limit: 5
  max_limit: 50
  lexical_weight: 0.45
  vector_weight: 0.45
  metadata_boost_weight: 0.10
  cache_results: true
YAML

if chown -R "${CONTAINER_UID}:${CONTAINER_GID}" "${DATA_DIR}" 2>/dev/null; then
  echo "Prepared ${DATA_DIR} for ${CONTAINER_UID}:${CONTAINER_GID} with host chown"
else
  echo "Host chown failed; preparing ${DATA_DIR} with root container"
  docker run --rm --user 0:0 --volume "${DATA_DIR}:/data:rw" "${IMAGE_TAG}" chown -R "${CONTAINER_UID}:${CONTAINER_GID}" /data
fi

log "Verifying read-only /config mount"
if docker_run sh -c "touch /config/e2e-write-test"; then
  echo "ERROR: /config accepted writes"
  exit 1
fi
echo "ASSERT PASS: /config is read-only"

log "Verifying read-only /media mount"
if docker_run sh -c "touch /media/e2e-write-test"; then
  echo "ERROR: /media accepted writes"
  exit 1
fi
echo "ASSERT PASS: /media is read-only"

SCAN_JSON="${OUTPUT_DIR}/scan.json"
INGEST_JSON="${OUTPUT_DIR}/ingest.json"
STATUS_JSON="${OUTPUT_DIR}/status.json"
SEARCH_JSON="${OUTPUT_DIR}/search-red-pill.json"
MCP_JSON="${OUTPUT_DIR}/mcp.json"
MCP_SEARCH_JSON="${OUTPUT_DIR}/mcp-search-dialogue.json"

log "Running scan"
docker_run media-memory scan /media --config /config/config.yaml --json | tee "${SCAN_JSON}"
assert_json "scan found fixture items" "${SCAN_JSON}" "isinstance(payload, list) and len(payload) > 0"

log "Running ingest"
docker_run media-memory ingest /media --config /config/config.yaml --json | tee "${INGEST_JSON}"
assert_json "ingest scanned positive count" "${INGEST_JSON}" "payload.get('scanned', 0) > 0"

log "Checking SQLite DB file"
DB_PATH="${DATA_DIR}/media-memory.sqlite"
if [[ ! -s "${DB_PATH}" ]]; then
  echo "ERROR: expected non-empty DB at ${DB_PATH}"
  exit 1
fi
echo "ASSERT PASS: ${DB_PATH} exists and is non-empty"
echo "Container DB path: /data/media-memory.sqlite"

log "Running status"
docker_run media-memory status --config /config/config.yaml --json | tee "${STATUS_JSON}"
assert_json "status proves indexed database" "${STATUS_JSON}" "payload.get('db', {}).get('path') == '/data/media-memory.sqlite' and payload.get('db', {}).get('exists') is True and payload.get('counts', {}).get('media_items', 0) > 0 and payload.get('counts', {}).get('chunks', 0) > 0"

log "Running CLI search red pill"
docker_run media-memory search "red pill" --config /config/config.yaml --json | tee "${SEARCH_JSON}"
assert_file_contains "CLI search returns The.Matrix.1999.mkv" "${SEARCH_JSON}" "The.Matrix.1999.mkv"

log "Running MCP readiness JSON"
docker_run media-memory mcp --config /config/config.yaml --json | tee "${MCP_JSON}"
assert_json "MCP ready and ingest tools disabled" "${MCP_JSON}" "payload.get('status') == 'ready' and payload.get('allow_ingest_tools') is False"

log "Running MCP search_dialogue"
docker_run media-memory mcp-call search_dialogue --config /config/config.yaml --params '{"query":"red pill","limit":5}' | tee "${MCP_SEARCH_JSON}"
assert_file_contains "MCP search_dialogue returns The.Matrix.1999.mkv" "${MCP_SEARCH_JSON}" "The.Matrix.1999.mkv"
assert_file_contains "MCP evidence includes search_dialogue command" <(printf '%s\n' "media-memory mcp-call search_dialogue") "search_dialogue"

log "Output files"
echo "scan: ${SCAN_JSON}"
echo "ingest: ${INGEST_JSON}"
echo "status: ${STATUS_JSON}"
echo "search red pill: ${SEARCH_JSON}"
echo "mcp: ${MCP_JSON}"
echo "mcp search_dialogue: ${MCP_SEARCH_JSON}"

log "E2E PASS"
echo "E2E PASS"
