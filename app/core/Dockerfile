FROM python:3.13-slim

WORKDIR /src

RUN apt-get update && apt-get install -y \
    curl \
    gettext \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml ./

RUN mkdir -p /config

COPY ./makes/config.yml.template ./config/config.yml.template

COPY ./makes/generate_config.sh ./generate_config.sh

RUN chmod +x ./generate_config.sh

RUN uv lock

RUN uv sync --locked --no-dev

COPY src/ /src

EXPOSE 8000

COPY ./makes/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
