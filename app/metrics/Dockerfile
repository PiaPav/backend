FROM python:3.13-slim AS builder
WORKDIR /build/app/metrics

COPY app/metrics/pyproject.toml ./pyproject.toml
COPY app/metrics/src ./src
COPY app/algorithm/src/graph_dto ../algorithm/src/graph_dto

RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels metrics-service \
    && rm -rf /wheels \
    && groupadd --gid 10001 metrics \
    && useradd --uid 10001 --gid metrics --no-create-home metrics

USER metrics:metrics

ENTRYPOINT ["python", "-m", "metrics_service"]
