FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    bash \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio grpcio-tools

COPY app/grpc-proxy/pyproject.toml .
COPY uv.lock .

RUN uv sync --locked --no-dev

COPY app/grpc-proxy/src ./core
COPY proto ./proto

RUN bash ./proto/generate_grpc.sh

FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /build/core ./core
COPY --from=builder /build/proto ./proto
COPY --from=builder /build/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 50051

CMD ["python", "core/main.py"]
