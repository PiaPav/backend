# ==============================================================================
# gRPC CODE GENERATION MAKEFILE
# ==============================================================================

# Генерация gRPC кода
.PHONY: grpc
grpc:
	@echo "Start generate grpc"
	uv sync --project app/core/pyproject.toml
	@echo "uv sync core"
	uv sync --project app/algorithm/pyproject.toml
	@echo "uv sync algorithm"
	@./proto/generate_grpc.sh
