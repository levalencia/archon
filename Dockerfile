FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76 AS builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.15@sha256:a5727064a0de127bdb7c9d3c1383f3a9ac307d9f2d8a391edc7896c54289ced0 /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Optional: pre-download the local fastembed model into a cache layer.
# This avoids runtime downloads and lets the production stage mount it read-only.
FROM builder AS model-cache
RUN .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/embedding-models')"

FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76 AS production

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=model-cache /opt/embedding-models /opt/embedding-models
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/container-entrypoint.sh ./container-entrypoint.sh
COPY frontend/static/learning/cogentrex-studio.json ./learning/cogentrex-studio.json

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
# Default local embedding model cache to the pre-downloaded directory.
ENV COGENTREX_EMBEDDING_CACHE_PATH=/opt/embedding-models

RUN groupadd --system --gid 10001 cogentrex \
    && useradd --system --uid 10001 --gid cogentrex --home-dir /app cogentrex \
    && chmod 0555 /app/container-entrypoint.sh \
    && chown -R cogentrex:cogentrex /app

USER cogentrex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["/app/container-entrypoint.sh"]
