# Reel storefront. Build context = repository root (it needs sdks/python):
#   docker compose -f apps/reel-storefront/docker-compose.yml build
# apps/reel-storefront/Dockerfile.dockerignore replaces the root .dockerignore (which excludes sdks/).

FROM node:22-alpine AS web
WORKDIR /web
COPY apps/reel-storefront/frontend/package.json apps/reel-storefront/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY apps/reel-storefront/frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY sdks/python /sdk
RUN pip install /sdk "fastapi>=0.116" "uvicorn[standard]>=0.35" "pydantic>=2.10" "pydantic-settings>=2.10"
COPY apps/reel-storefront/app ./app
COPY apps/reel-storefront/scripts ./scripts
COPY apps/reel-storefront/data ./data
COPY --from=web /web/dist ./frontend/dist
RUN useradd --create-home reel && mkdir -p /app/state && chown reel /app/state
USER reel
EXPOSE 5290
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5290/api/reel/genres')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5290"]
