# VEXA execution sandbox image.
# Build:  docker build -t vexa-sandbox:latest -f docker/sandbox.Dockerfile docker
# Contains only what generated projects need to run their tests.
FROM python:3.11-slim

RUN pip install --no-cache-dir "pytest>=8.3" "pytest-asyncio>=0.24" \
    && useradd --create-home --uid 10001 sandbox

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace
USER sandbox
