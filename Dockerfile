FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

WORKDIR /app

# CPU-only PyTorch for DGSR serving (the CUDA wheels are ~2 GB and unused here).
# Installed before any source is copied so the layer stays cached across code changes.
RUN pip install --no-cache-dir --upgrade pip==25.1.1 \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0"

COPY pyproject.toml ./
# Resolve dependencies before source changes invalidate the application layer.
RUN python -c "import subprocess,tomllib; p=tomllib.load(open('pyproject.toml','rb')); subprocess.check_call(['pip','install','--no-cache-dir','--resume-retries','10',*p['build-system']['requires'],*p['project']['dependencies'],*p['project']['optional-dependencies']['test']])"
COPY apps ./apps
COPY graphrec_core ./graphrec_core
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

RUN pip install --no-cache-dir --no-deps --no-build-isolation ".[test]"

RUN useradd --create-home --uid 10001 graphrec \
    && mkdir -p /app/generated_artifacts \
    && chown -R graphrec:graphrec /app

USER graphrec

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
