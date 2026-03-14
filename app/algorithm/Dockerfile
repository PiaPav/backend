FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio-tools

COPY app/algorithm/pyproject.toml .
COPY app/algorithm/uv.lock .

RUN uv sync --locked --no-dev

COPY app/algorithm/src ./algorithm
COPY proto ./proto

RUN bash ./proto/generate_grpc.sh


FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv

COPY --from=builder /build/algorithm ./algorithm
COPY --from=builder /build/proto ./proto

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 50051

ENTRYPOINT ["python", "algorithm/main.py"]
