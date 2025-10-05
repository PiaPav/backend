FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml ./

RUN uv lock

RUN uv sync --locked --no-dev

COPY src/ /src

EXPOSE 8000

ENTRYPOINT ["python", "main.py"]
