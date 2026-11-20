# ReelStore production multi-stage image.
# Build context = repository root:
#   docker compose -f reelstore/docker-compose.yml build

FROM node:22-alpine AS web
WORKDIR /web
COPY reelstore/frontend/package.json reelstore/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY reelstore/frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install shared GraphRec Python SDK and pinned dependencies
COPY sdks/python /sdk
COPY reelstore/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir /sdk

COPY reelstore/app ./app
COPY reelstore/scripts ./scripts
COPY reelstore/data ./data
COPY --from=web /web/dist ./frontend/dist

RUN useradd --create-home --uid 10001 reel \
  && mkdir -p /app/state \
  && chown -R reel:reel /app/state

USER reel
EXPOSE 5290

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5290/readyz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5290"]
