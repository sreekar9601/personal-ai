# Minimal image for the polling worker. uv handles deps + the 3.12 runtime.
FROM python:3.12-slim

# git is required: the agent commits knowledge changes.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --frozen || uv sync --no-dev

COPY . .

# .data lives on the mounted volume in production.
ENV PERSONAL_AI_DATA=/data
CMD ["uv", "run", "python", "-m", "agent.main"]
