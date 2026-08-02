FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY apps ./apps
COPY graphrec_core ./graphrec_core
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

RUN pip install --no-cache-dir --upgrade pip==25.1.1 \
    && pip install --no-cache-dir ".[test]"

RUN useradd --create-home --uid 10001 graphrec \
    && chown -R graphrec:graphrec /app

USER graphrec

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
