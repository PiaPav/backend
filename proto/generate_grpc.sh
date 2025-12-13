#!/bin/bash

# Находим все proto файлы
PROTO_FILES=$(find ./proto -name "*.proto" -type f)

# Создаем директории для генерации если их нет
PROXY_DIR="/src/grpc-proxy/grpc_control/generated"
ALGORITHM_DIR="/src/algorithm/grpc_control/generated"

echo "Creating directories..."
mkdir -p "$PROXY_DIR"
mkdir -p "$ALGORITHM_DIR"
echo "Directories created"

echo "Generating gRPC code..."

# Генерация для PROXY
uv run python \
    -m grpc_tools.protoc \
    --proto_path=./proto \
    --python_out="$PROXY_DIR" \
    --grpc_python_out="$PROXY_DIR" \
    $PROTO_FILES

# Генерация для Algorithm
uv run python \
    -m grpc_tools.protoc \
    --proto_path=./proto \
    --python_out="$ALGORITHM_DIR" \
    --grpc_python_out="$ALGORITHM_DIR" \
    $PROTO_FILES

echo "Fixing imports..."

# Исправляем импорты в сгенерированных файлах
find "$PROXY_DIR" -name "*.py" -type f | while read file; do
    sed -i 's/^from \(api\|shared\)/from grpc_control.generated.\1/g' "$file"
    sed -i 's/^import \(api\|shared\)/import grpc_control.generated.\1/g' "$file"
done

find "$ALGORITHM_DIR" -name "*.py" -type f | while read file; do
    sed -i 's/^from \(api\|shared\)/from grpc_control.generated.\1/g' "$file"
    sed -i 's/^import \(api\|shared\)/import grpc_control.generated.\1/g' "$file"
done

echo "gRPC code generated and fixed successfully!"