FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# ONCE (https://github.com/basecamp/once) expects HTTP on port 80 and GET /up
ENV HEALTH_HTTP_PORT=80
EXPOSE 80

CMD ["uv", "run", "python", "bot.py"]
