#!/bin/bash
set -e

CONFIG_PATH="$1"  # путь к файлу, передаем как аргумент
mkdir -p "$(dirname "$CONFIG_PATH")"

echo "auth:" > "$CONFIG_PATH"
echo "  ACCESS_SECRET_KEY: \"$ACCESS_SECRET_KEY\"" >> "$CONFIG_PATH"
echo "  REFRESH_SECRET_KEY: \"$REFRESH_SECRET_KEY\"" >> "$CONFIG_PATH"
echo "  ALGORITHM: \"$ALGORITHM\"" >> "$CONFIG_PATH"
echo "  ACCESS_TOKEN_EXPIRE_MINUTES: $ACCESS_TOKEN_EXPIRE_MINUTES" >> "$CONFIG_PATH"
echo "  REFRESH_TOKEN_EXPIRE_DAYS: $REFRESH_TOKEN_EXPIRE_DAYS" >> "$CONFIG_PATH"

echo "server:" >> "$CONFIG_PATH"
echo "  host: \"$CORE_HOST\"" >> "$CONFIG_PATH"
echo "  port: $CORE_PORT" >> "$CONFIG_PATH"

echo "db:" >> "$CONFIG_PATH"
echo "  host: postgres" >> "$CONFIG_PATH"
echo "  port: 5432" >> "$CONFIG_PATH"
echo "  name: \"$POSTGRES_DB\"" >> "$CONFIG_PATH"
echo "  user: \"$POSTGRES_USER\"" >> "$CONFIG_PATH"
echo "  password: \"$POSTGRES_PASSWORD\"" >> "$CONFIG_PATH"
echo "  echo: true" >> "$CONFIG_PATH"

chmod 600 "$CONFIG_PATH"
