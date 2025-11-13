FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv grpcio-tools

COPY app/core/pyproject.toml ./
COPY app/core/src/ /src/core/

COPY app/algorithm/pyproject.toml ./algorithm_pyproject.toml
COPY app/algorithm/src/ /src/algorithm/

COPY proto/ /src/proto/

RUN uv lock
RUN uv sync --locked --no-dev
RUN bash /src/proto/generate_grpc.sh

EXPOSE 8000

ENTRYPOINT ["uv", "run", "python", "main.py"]
