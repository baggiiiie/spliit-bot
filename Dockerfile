FROM ghcr.io/anomalyco/opencode:latest AS opencode

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

COPY --from=opencode /usr/local/bin/opencode /usr/local/bin/opencode

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "bot.py"]
