FROM python:3.11-slim

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CREWAI_DISABLE_TELEMETRY=true

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 vexa

WORKDIR /app

# Source must be present before installing the package
COPY pyproject.toml ./
COPY backend/ ./backend/
COPY benchmarks/ ./benchmarks/
RUN pip install --no-cache-dir ".[dev]"

USER vexa
EXPOSE 8000

# 0.0.0.0 inside the container only; publish the port to localhost on the host (see docker-compose.yml)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
