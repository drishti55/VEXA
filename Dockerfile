# ---- Stage 1: build the React dashboard -------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same origin as the API (empty base URL). Defaults suit small hosts; override with --build-arg.
ARG VITE_DEFAULT_VERIFIER=adk_a2a
ARG VITE_DEFAULT_TOOL_TRANSPORT=mcp
ENV VITE_VEXA_API_URL="" \
    VITE_DEFAULT_VERIFIER=$VITE_DEFAULT_VERIFIER \
    VITE_DEFAULT_TOOL_TRANSPORT=$VITE_DEFAULT_TOOL_TRANSPORT
RUN npm run build

# ---- Stage 2: backend (serves the API and the built dashboard) --------------
FROM python:3.11-slim

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CREWAI_DISABLE_TELEMETRY=true

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 vexa \
    && mkdir -p /data/workspaces && chown -R vexa /data

WORKDIR /app

# Source must be present before installing the package
COPY pyproject.toml ./
COPY backend/ ./backend/
COPY benchmarks/ ./benchmarks/
RUN pip install --no-cache-dir ".[dev]"
COPY --from=frontend /frontend/dist ./frontend/dist

# Writable state lives under /data (mount a disk there to keep it across restarts)
ENV WORKSPACE_ROOT=/data/workspaces \
    VEXA_DB_PATH=/data/vexa.sqlite3

USER vexa
EXPOSE 8000

# 0.0.0.0 inside the container only. Render sets $PORT; docker-compose publishes 8000 to localhost.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
