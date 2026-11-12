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
the local service. There is currently no RabbitMQ/S3 adapter or standalone
process entrypoint for this version. The previous worker and Compose profile
were removed when this implementation became authoritative; a broker adapter
must be added before deploying it as a worker.
