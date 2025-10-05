#!/bin/bash
set -e

CONFIG_PATH="$1"
TEMPLATE_PATH="$2"

envsubst < "$TEMPLATE_PATH" > "$CONFIG_PATH"

chmod 600 "$CONFIG_PATH"
