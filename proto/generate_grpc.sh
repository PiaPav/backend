#!/bin/bash

# Находим все proto файлы
PROTO_FILES=$(find ./proto -name "*.proto" -type f)

# Создаем директории для генерации если их нет
CORE_DIR="./app/core/src/grpc_control/generated"
ALGORITHM_DIR="./app/algorithm/src/grpc_control/generated"

echo "Creating directories..."
mkdir -p "$CORE_DIR"
mkdir -p "$ALGORITHM_DIR"
echo "Directories created"

echo "Generating gRPC code..."

# Генерация для Core
uv run python \
    -m grpc_tools.protoc \
    --proto_path=./proto \
    --python_out=./app/core/src/grpc_control/generated \
    --grpc_python_out=./app/core/src/grpc_control/generated \
    $PROTO_FILES

# Генерация для Algorithm
uv run python \
    -m grpc_tools.protoc \
    --proto_path=./proto \
    --python_out=./app/algorithm/src/grpc_control/generated \
    --grpc_python_out=./app/algorithm/src/grpc_control/generated \
    $PROTO_FILES

echo "gRPC code generated successfully!"