FROM python:3.11-slim-bookworm@sha256:8dca233de9f3d9bb410665f00a4da6dd06f331083137e0e98ccf227236fcc438 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

FROM python:3.11-slim-bookworm@sha256:8dca233de9f3d9bb410665f00a4da6dd06f331083137e0e98ccf227236fcc438 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgnutls30 libssl3 \
    && apt-get clean \
    && groupadd --gid 10001 media-memory \
    && useradd --uid 10001 --gid media-memory --home-dir /app --no-create-home --shell /usr/sbin/nologin media-memory \
    && mkdir -p /app /config /data /media /bazarr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN find /usr/local/lib/python3.11/site-packages -maxdepth 1 \
    \( -type d -name "jaraco*" -o -type d -name "wheel*" -o -type d -name "setuptools*" -o -type d -name "pip*" \) \
    -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv/lib/python3.11/site-packages -maxdepth 1 \
    \( -type d -name "setuptools*" -o -type d -name "wheel*" -o -type d -name "pip*" \) \
    -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv/lib/python3.11/site-packages/setuptools/_vendor -maxdepth 1 \
    -type d \( -name "jaraco*" -o -name "jaraco_context*" \) -prune -exec rm -rf {} + 2>/dev/null || true
RUN chown -R media-memory:media-memory /app /data /opt/venv

WORKDIR /app

USER media-memory

VOLUME ["/config", "/data", "/media", "/bazarr"]

CMD ["media-memory", "mcp", "--config", "/config/config.yaml"]
