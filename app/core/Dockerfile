FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio-tools gunicorn uvicorn[standard]

COPY app/core/pyproject.toml ./pyproject.toml

COPY app/core/src ./core
COPY proto ./proto

RUN uv lock
RUN uv sync --locked --no-dev

RUN bash ./proto/generate_grpc.sh

EXPOSE 8000
EXPOSE 50051

CMD ["uv", "run", "python", "core/main.py"]
