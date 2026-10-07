# GraphRec API, worker and scheduler image (A-12).
#
#   runtime (default)  minimal, non-root, no tests or test extras
#   test               runtime + tests and test extras, for CI and `docker compose run`
#
# Dependencies resolve against constraints.txt so every build installs the same versions.

FROM python:3.12.11-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# CPU-only PyTorch for DGSR training and serving (the CUDA wheels are ~2 GB and unused).
# Installed before any source is copied so the layer stays cached across code changes.
RUN pip install --no-cache-dir --upgrade pip==25.1.1 \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0"

WORKDIR /src
COPY pyproject.toml constraints.txt VERSION ./
RUN python -c "import subprocess,tomllib; p=tomllib.load(open('pyproject.toml','rb')); subprocess.check_call(['pip','install','--no-cache-dir','-c','constraints.txt',*p['build-system']['requires'],*p['project']['dependencies']])"
COPY apps ./apps
COPY graphrec_core ./graphrec_core
COPY scripts ./scripts
RUN pip install --no-cache-dir --no-deps --no-build-isolation .


FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    GRAPHREC_ENV=production

RUN useradd --create-home --uid 10001 graphrec
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=graphrec:graphrec apps ./apps
COPY --chown=graphrec:graphrec graphrec_core ./graphrec_core
COPY --chown=graphrec:graphrec scripts ./scripts
COPY --chown=graphrec:graphrec migrations ./migrations
COPY --chown=graphrec:graphrec alembic.ini VERSION ./
RUN mkdir -p /app/generated_artifacts && chown graphrec:graphrec /app/generated_artifacts

USER graphrec
EXPOSE 8000
# FORWARDED_ALLOW_IPS (read by uvicorn and GraphRec) names the trusted reverse proxy.
# WEB_CONCURRENCY sets the number of API worker processes; limits and leases are shared in Redis.
CMD ["sh", "-c", "exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --timeout-graceful-shutdown 20"]


FROM runtime AS test

USER root
COPY pyproject.toml constraints.txt ./
RUN python -c "import subprocess,tomllib; p=tomllib.load(open('pyproject.toml','rb')); subprocess.check_call(['pip','install','--no-cache-dir','-c','constraints.txt',*p['project']['optional-dependencies']['test']])"
COPY --chown=graphrec:graphrec tests ./tests
ENV GRAPHREC_ENV=development
USER graphrec
