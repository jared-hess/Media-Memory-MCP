FROM python:3.11-slim-bookworm@sha256:8dca233de9f3d9bb410665f00a4da6dd06f331083137e0e98ccf227236fcc438 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv \
    && python -m pip install --no-cache-dir --upgrade pip setuptools "wheel>=0.46.2" "jaraco.context>=6.1.0"

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
    && apt-get install -y --no-install-recommends ffmpeg \
    && groupadd --gid 10001 media-memory \
    && useradd --uid 10001 --gid media-memory --home-dir /app --no-create-home --shell /usr/sbin/nologin media-memory \
    && mkdir -p /app /config /data /media /bazarr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN chown -R media-memory:media-memory /app /data /opt/venv

WORKDIR /app

USER media-memory

VOLUME ["/config", "/data", "/media", "/bazarr"]

CMD ["media-memory", "mcp", "--config", "/config/config.yaml"]
