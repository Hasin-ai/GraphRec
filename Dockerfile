FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

# Dependencies resolve from pyproject alone, so this layer is cached until the
# dependency set actually changes.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY graphrec ./graphrec
COPY apps ./apps
COPY scripts ./scripts

# Non-root: the container has no reason to write to its own filesystem.
RUN useradd --create-home --uid 10001 graphrec \
 && chown -R graphrec:graphrec /app
USER graphrec

EXPOSE 8010

CMD ["uvicorn", "apps.control_api.main:app", "--host", "0.0.0.0", "--port", "8010"]
