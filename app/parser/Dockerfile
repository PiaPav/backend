FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/parser/src:/app/algorithm/src

WORKDIR /app

COPY algorithm/ ./algorithm/
COPY parser/ ./parser/

WORKDIR /app/parser

RUN uv sync --no-dev

CMD ["uv", "run", "--no-sync", "python", "-m", "parser_service.main"]