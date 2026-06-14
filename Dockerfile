FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (curl for healthchecks; build tools for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml pyproject.toml
COPY README.md README.md
COPY LICENSE LICENSE

# Modular install via extras.
# Default image builds the full chain deps; compose can override commands.
RUN python -m pip install --no-cache-dir '.[all]'

COPY . .

# Default to the product gateway; docker-compose overrides per-service.
CMD ["python", "-m", "uvicorn", "agent_runtime.product.agent_gateway:app", "--host", "0.0.0.0", "--port", "8080"]
