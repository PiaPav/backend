FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio-tools

COPY app/core/pyproject.toml .
COPY app/core/uv.lock .

RUN uv sync --locked --no-dev

COPY app/core/src ./core
COPY proto ./proto

RUN bash ./proto/generate_grpc.sh


FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uvicorn[standard] gunicorn uv

COPY --from=builder /build/.venv /app/.venv

COPY --from=builder /build/core ./core
COPY --from=builder /build/proto ./proto

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
EXPOSE 50051

CMD ["python", "core/main.py"]
