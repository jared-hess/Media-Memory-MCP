FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && python -m pip install --no-cache-dir --upgrade "wheel>=0.46.2" "jaraco.context>=6.1.0" \
    && media-memory --help >/dev/null \
    && ffmpeg -version >/dev/null \
    && ffprobe -version >/dev/null

VOLUME ["/config", "/data", "/media", "/bazarr"]

CMD ["media-memory", "mcp", "--config", "/config/config.yaml"]
