FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY app/core/pyproject.toml ./
COPY app/core/src/ /src/

COPY proto/ /src/proto

RUN uv lock
RUN uv sync --locked --no-dev

EXPOSE 8000

ENTRYPOINT ["uv", "run", "python", "main.py"]
