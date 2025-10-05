FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml ./

RUN mkdir -p /config

COPY config.yml.template ./config/config.yml.template

COPY ./generate_config.sh ./generate_config.sh

RUN chmod +x ./generate_config.sh

RUN uv lock

RUN uv sync --locked --no-dev

COPY src/ /src

EXPOSE 8000

CMD bash ./generate_config.sh /config/config.yml ./config.yml.template && uv run python main.py