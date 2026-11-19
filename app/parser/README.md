# Parser

`src/parser` contains the canonical Parser Core. `src/parser_service` contains
the service contracts, handler, local filesystem and SQLite adapters, and local
runtime developed in `algorithm`. The service accepts `parser.start.v1` and emits
`graph.ready.v1` or `parser.failed.v1`.

The shared Graph DTO remains in `app/algorithm/src`. Run tests from the repository
root with the source directories on `PYTHONPATH`:

```sh
PYTHONPATH=app/parser/src:app/metrics/src:app/algorithm/src \
  app/algorithm/.venv/bin/python -m pytest -q \
  app/parser/src/parser_service/tests app/parser/src/parser/test_core.py
```

`parser_service.composition.build_application` and `build_runtime` construct
the local service. There is currently no broker adapter or standalone process
entrypoint for this version.
