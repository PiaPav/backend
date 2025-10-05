#!/bin/bash
set -e

/src/generate_config.sh /config/config.yml /src/config/config.yml.template

exec uv run python main.py
