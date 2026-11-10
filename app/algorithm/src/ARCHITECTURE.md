# Архитектура сервиса статического анализа

## Назначение

Система анализирует Python-проект в два этапа и публикует результаты как
неизменяемые JSON-артефакты:

```text
parser.start.v1 -> Parser Service -> graph.ready.v1
                                      |
                                      v
                              Metrics Service -> metrics.ready.v1
```

Parser и Metrics — независимые сервисные оболочки. Они взаимодействуют только
через versioned wire events и URI артефактов; production-код сервисов не
импортирует соседний сервис и не содержит центрального orchestrator.

## Ядра и DTO

### Parser Core

Публичный API:

```python
parser.parse_project(source_path: Path, output_path: Path) -> Path
parser.parse_project_with_source_index(
    source_path: Path,
    graph_output_path: Path,
    source_index_output_path: Path,
) -> tuple[Path, Path]
```

Parser строит полный Graph DTO schema 1 / Parser semantics 7: файлы,
объявления, ownership, импорты, наследование, типы полей, обращения к полям,
callsites, weighted `calls`/`awaits`, complexity/structural facts и diagnostics.
Только `exact` relations создают внутреннюю топологию. Граф является
консервативной статической моделью, а не полной моделью runtime Python.

Второй API строит тот же canonical Graph DTO и одновременно создаёт Source
Index schema 1 для прямого поиска файлов, классов, методов, функций и констант.
Индекс содержит byte/line spans, SHA-256 файлов и fingerprint snapshot исходников.

### Metrics Core

Публичный API:

```python
metrics.calculate_metrics(graph_path: Path, output_path: Path) -> Path
```

Metrics принимает только полный валидный Graph DTO schema 1 / semantics 6 или
7 и создаёт Metrics DTO schema 1 / Metrics semantics 4. Разделы результата:
`size`, `activity`, `dependency_graph`, `architecture`, `code_quality`,
`object_oriented` и `call_graph`. Reduced views не являются входом Metrics.

Метрики зависят от полноты exact resolution. `risk` — относительный hotspot
score внутри одного проекта, а не вероятность дефекта.

## Сервисные оболочки

`parser_service` принимает только `parser.start.v1`, проверяет tenant и
requested schema/semantics, вызывает Parser Core, валидирует и сохраняет Graph
DTO и Source Index, затем публикует `graph.ready.v1` либо `parser.failed.v1`.
Новые события `graph.ready.v1` содержат дескриптор `source_index` с URI,
SHA-256, размером, версией схемы и project fingerprint. Consumer-контракт
Metrics сохраняет совместимость со старыми событиями без этого поля.

`metrics_service` принимает только `graph.ready.v1`, проверяет URI, размер,
SHA-256, schema/semantics и graph fingerprint, вызывает Metrics Core, сохраняет
Metrics DTO и публикует `metrics.ready.v1` либо `metrics.failed.v1`.

Оба сервиса используют один порядок надёжной обработки:

```text
core -> save immutable artifact -> persist output event -> publish -> mark published
```

SQLite idempotency stores поддерживают lease reclaim, claim-token fencing и
restart-safe состояния `CLAIMED`, `SAVED`, `PUBLISHED`, `FAILED_SAVED`,
`FAILED_PUBLISHED`. После сбоя публикации сохранённое событие переиздаётся без
повторного запуска ядра; доставка после `PUBLISHED` завершается как no-op.

## Runtime и локальные адаптеры

Transport-neutral runtime имеет single-use lifecycle
`CREATED -> STARTING -> RUNNING -> STOPPING -> STOPPED`, graceful drain и
возвращает источнику решение `ACK`, `RETRY` или `REJECT`. Settlement и повторная
доставка принадлежат transport adapter, а не handler/runtime.

Доступны локальные адаптеры:

- filesystem source/graph resolvers с configured-root, traversal и symlink
  protection;
- staging areas и atomic immutable artifact stores;
- SQLite/WAL idempotency stores;
- manual input, recording publisher, UTC clock и UUID generator.

Локальная Parser -> JSON wire -> Metrics choreography проверена с реальными
ядрами, filesystem и SQLite. Конкретный production broker adapter пока не
подключён; требования к нему описаны в `BROKER_INTEGRATION.md`.

## Профили данных

Пакет `views` создаёт детерминированные projections только после полной
валидации canonical DTO. Source не мутируется, canonical IDs сохраняются для
неагрегированных объектов, fingerprints связывают views с полным графом.

Graph profiles: `canonical.full`, `inventory.minimal`,
`structure.declarations`, `dependency.files`, `dependency.architecture`,
`calls.topology`, `calls.detailed`, `types.topology`,
`objects.metrics_basis`, `aggregate.packages/2`, `aggregate.overview/1`.

Metrics profiles: `metrics.full`, `metrics.overview`, `metrics.architecture`,
`metrics.quality`, `metrics.objects`, `metrics.aggregate`. `metrics.calls` не
публикуется: прежний вариант не прошёл size gate.

Выбор требует точных profile ID/version. Defaults, `latest`, negotiation и
silent fallback отсутствуют. Только `canonical.full` и `metrics.full` globally
lossless.

## Точки интеграции

Программные composition roots:

```python
parser_service.composition.build_application(...)
parser_service.composition.build_runtime(...)
metrics_service.composition.build_application(...)
metrics_service.composition.build_runtime(...)
```

Основные порты: `InputSignalSource`, `EventPublisher`, `IdempotencyStore`,
resolvers, staging/artifact stores, core gateways, clock и ID generator.
Production broker должен реализовать только transport-порты и не менять
application handlers.

## Проверки и ограничения

Тесты покрывают wire contracts, producer/consumer compatibility, handlers,
state machines, tenant isolation, filesystem boundaries, SQLite replay/fencing,
runtime lifecycle, profile contracts/golden size gates и полную локальную
choreography с реальными ядрами.

Не реализованы: production broker, remote artifact storage и transport protocol
для materialization reduced profiles. Также нет полного динамического анализа
Python, инкрементального анализа, cancellation и гарантии разрешения всех
runtime relations.
