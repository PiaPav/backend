FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/metrics/src:/app/algorithm/src

WORKDIR /app

COPY algorithm/ ./algorithm/
COPY metrics/ ./metrics/

WORKDIR /app/metrics

RUN uv sync --no-dev

CMD ["uv", "run", "--no-sync", "python", "-m", "metrics_service.main"]