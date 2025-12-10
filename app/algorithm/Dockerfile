FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio-tools

COPY app/algorithm/pyproject.toml ./pyproject.toml
COPY app/algorithm/src/ ./algorithm/

COPY proto/ ./proto/

RUN uv lock
RUN uv sync --locked --no-dev
RUN bash ./proto/generate_grpc.sh

EXPOSE 50051

ENTRYPOINT ["uv", "run", "python", "algorithm/main.py"]
