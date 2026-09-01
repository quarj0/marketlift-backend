# syntax=docker/dockerfile:1.7

FROM python:3.14.6-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/

WORKDIR /app

# Build dependencies only.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        libpq-dev \
        libgdal-dev \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# Install third-party dependencies first so this layer is cached
# until pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev \
        --no-install-project

# Now copy the application.
COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
        --frozen \
        --no-dev


FROM python:3.14.6-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Runtime libraries only.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libpq5 \
        libgdal32 \
        libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system marketlift \
    && adduser \
        --system \
        --ingroup marketlift \
        --home /app \
        marketlift

COPY --from=builder --chown=marketlift:marketlift /app /app

USER marketlift

EXPOSE 8000

HEALTHCHECK \
    --interval=15s \
    --timeout=3s \
    --start-period=30s \
    --retries=4 \
    CMD python -c "import socket; s = socket.create_connection(('127.0.0.1', 8000), 2); s.close()"

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "marketlift.asgi:application"]