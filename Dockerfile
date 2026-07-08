# Minimal image for the polling worker. uv handles deps + the 3.12 runtime.
FROM python:3.12-slim

# git commits knowledge changes; openssh-client lets it push via a deploy key.
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --frozen || uv sync --no-dev

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# .data lives on the mounted volume in production.
ENV PERSONAL_AI_DATA=/data
CMD ["/entrypoint.sh"]
