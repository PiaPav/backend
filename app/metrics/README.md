# Metrics

`src/metrics` contains the canonical Metrics Core. `src/metrics_service` contains
the service contracts, handler, local filesystem and SQLite adapters, and local
runtime developed in `algorithm`. The service accepts `graph.ready.v1` and emits
`metrics.ready.v1` or `metrics.failed.v1`.

The shared Graph DTO and `views` packages remain in `app/algorithm/src`. Until
they are extracted, run from the repository root with all source directories:

```sh
PYTHONPATH=app/parser/src:app/metrics/src:app/algorithm/src \
  app/algorithm/.venv/bin/python -m pytest -q \
  app/metrics/src/metrics_service/tests app/metrics/src/metrics/test_core.py
```

`metrics_service.composition.build_application` and `build_runtime` construct
the local service. This version has no RabbitMQ/S3 adapter or standalone process
entrypoint. The previous worker and its Compose profile remain in `legacy/`.
