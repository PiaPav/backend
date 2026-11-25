FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/harness-micro/src:/app/algorithm/src

WORKDIR /app

COPY algorithm/ ./algorithm/
COPY harness-micro/ ./harness-micro/

WORKDIR /app/harness-micro

RUN uv sync --no-dev

CMD ["uv", "run", "--no-sync", "python", "-m", "harness_service.main"]