# План разработки микросервисных оболочек Parser и Metrics

## 1. Цель и границы

Нужно создать две независимые кодовые оболочки вокруг неизменяемых ядер:

- `parser_service` — получает входной сигнал, запускает Parser Core, сохраняет
  Graph DTO и публикует сигнал о результате;
- `metrics_service` — получает сигнал о готовом Graph DTO, запускает Metrics
  Core, сохраняет Metrics DTO и публикует сигнал о результате.

Основной способ взаимодействия — **event choreography**. Каждый сервис знает
только собственный вход, собственную операцию и собственный выход. Он не знает
полный workflow, не запускает соседний сервис напрямую и не ожидает завершения
последующих стадий.

В объём плана не входят:

- установка и настройка брокера, Redis, СУБД или object storage;
- выбор конкретного поставщика инфраструктуры;
- клиентские библиотеки RabbitMQ, Kafka, Redis, S3, SQL и аналогов;
- изменение `parser`, `metrics` или `graph_dto`;
- доработка полноты статического анализа;
- центральный orchestrator и общая workflow state machine.

Вместо инфраструктурных реализаций вводятся чистые порты, локальные адаптеры и
тестовые заглушки. В будущем реальные adapters подключаются в composition root,
не меняя application logic.

## 2. Исходные контракты ядер

Parser Core:

```python
parser.parse_project(source_path: Path, output_path: Path) -> Path
```

- принимает локальный каталог исходников;
- создаёт Graph DTO schema v1 / Parser semantics v7;
- атомарно записывает JSON;
- возвращает итоговый `Path`.

Metrics Core:

```python
metrics.calculate_metrics(graph_path: Path, output_path: Path) -> Path
```

- принимает локальный Graph DTO schema v1 / Parser semantics v6 или v7;
- создаёт Metrics DTO schema v1 / Metrics semantics v4;
- атомарно записывает JSON;
- возвращает итоговый `Path`.

Оболочки используют только эти публичные API. Импорты из `parser.logic` и
`metrics.logic` запрещены.

## 3. Новые директории

Рекомендуемые директории:

```text
app/algorithm/src/parser_service/
app/algorithm/src/metrics_service/
```

Имена явно отделяют transport/application shell от вычислительных пакетов
`parser` и `metrics`. Сервисы не импортируют друг друга.

### 3.1. Parser Service

```text
parser_service/
├── __init__.py
├── contracts/
│   ├── __init__.py
│   ├── envelope.py
│   ├── commands.py
│   ├── events.py
│   └── codecs.py
├── application/
│   ├── __init__.py
│   ├── handlers.py
│   ├── ports.py
│   ├── models.py
│   └── errors.py
├── adapters/
│   ├── __init__.py
│   ├── parser_core.py
│   ├── local_files.py
│   ├── in_memory_idempotency.py
│   ├── file_idempotency.py
│   ├── recording_publisher.py
│   └── manual_input.py
├── composition.py
├── runtime.py
└── tests/
    ├── test_contracts.py
    ├── test_handler.py
    ├── test_idempotency.py
    ├── test_local_adapters.py
    └── test_runtime.py
```

### 3.2. Metrics Service

```text
metrics_service/
├── __init__.py
├── contracts/
│   ├── __init__.py
│   ├── envelope.py
│   ├── commands.py
│   ├── events.py
│   └── codecs.py
├── application/
│   ├── __init__.py
│   ├── handlers.py
│   ├── ports.py
│   ├── models.py
│   └── errors.py
├── adapters/
│   ├── __init__.py
│   ├── metrics_core.py
│   ├── local_files.py
│   ├── in_memory_idempotency.py
│   ├── file_idempotency.py
│   ├── recording_publisher.py
│   └── manual_input.py
├── composition.py
├── runtime.py
└── tests/
    ├── test_contracts.py
    ├── test_handler.py
    ├── test_idempotency.py
    ├── test_local_adapters.py
    ├── test_graph_ready_compatibility.py
    └── test_runtime.py
```

Структура намеренно симметрична, но общего application-пакета между сервисами
нет. Это сохраняет возможность раздельного развёртывания и версионирования.

## 4. Событийная модель

```text
parser.start.v1
       |
       v
 Parser Service
       |
       +----> graph.ready.v1
       `----> parser.failed.v1

graph.ready.v1
       |
       v
 Metrics Service
       |
       +----> metrics.ready.v1
       `----> metrics.failed.v1

metrics.ready.v1 -> неизвестные сервисам последующие потребители
```

Parser публикует факт готовности графа, а не команду Metrics. Metrics просто
подписан на этот факт. Аналогично Metrics не выбирает следующий сервис.

## 5. Общий wire envelope

```json
{
  "event_id": "uuid-or-ulid",
  "event_type": "graph.ready.v1",
  "schema_version": 1,
  "occurred_at": "2026-10-24T12:00:00Z",
  "correlation_id": "analysis-id",
  "causation_id": "input-event-id",
  "tenant_id": "tenant",
  "producer": {
    "service": "parser-service",
    "version": "service-build-version"
  },
  "payload": {}
}
```

Правила:

- `event_id` уникален и сохраняется при повторной публикации того же события;
- `event_type` версионируется отдельно для каждого payload;
- `schema_version` относится к envelope;
- `correlation_id` переносится без попытки управлять workflow;
- `causation_id` равен `event_id` входного сигнала;
- timestamps передаются в UTC RFC 3339;
- декодер не приводит произвольные значения к строкам;
- неизвестная major-версия отклоняется;
- исходный код, Graph DTO и Metrics DTO не помещаются в сообщение целиком.

DTO рекомендуется реализовать immutable dataclasses и явными методами
`from_mapping()` / `to_mapping()` только на стандартной библиотеке.

## 6. Контракты входов и выходов

### 6.1. `parser.start.v1`

```json
{
  "event_type": "parser.start.v1",
  "payload": {
    "source_uri": "file:///workspace/project",
    "requested_graph": {
      "schema_version": 1,
      "parser_semantics_version": 7
    }
  }
}
```

`source_uri` является непрозрачной ссылкой application layer. Первоначальный
локальный adapter поддерживает абсолютный path и `file://`. Иные схемы
возвращают `unsupported_uri_scheme`, пока не появится соответствующий adapter.

Источник должен обозначать immutable snapshot на время обработки и повторов.
Локальный `file://` предназначен для разработки: вызывающая сторона не должна
изменять каталог до завершения стадии. Проверяемый checksum каталога не входит в
v1, поскольку без канонического manifest его смысл был бы неоднозначен. В
будущем source artifact adapter может добавить отдельный версионированный
manifest/checksum contract.

Путь назначения в событие не включается: размещением результата владеет
`GraphArtifactStore` Parser Service.

### 6.2. `graph.ready.v1`

```json
{
  "event_type": "graph.ready.v1",
  "payload": {
    "source_uri": "file:///workspace/project",
    "graph": {
      "uri": "file:///artifacts/<key>/graph.json",
      "sha256": "artifact-checksum",
      "size_bytes": 123,
      "schema_version": 1,
      "parser_semantics_version": 7,
      "graph_fingerprint": "canonical-graph-fingerprint"
    }
  }
}
```

Versions и fingerprint читаются из фактически созданного DTO. Их нельзя
заполнять константами без проверки результата ядра.

### 6.3. `metrics.ready.v1`

```json
{
  "event_type": "metrics.ready.v1",
  "payload": {
    "graph": {
      "uri": "file:///artifacts/<key>/graph.json",
      "graph_fingerprint": "canonical-graph-fingerprint"
    },
    "metrics": {
      "uri": "file:///artifacts/<key>/metrics.json",
      "sha256": "artifact-checksum",
      "size_bytes": 123,
      "schema_version": 1,
      "metrics_semantics_version": 4
    }
  }
}
```

`graph_fingerprint` должен совпадать с `input.graph_fingerprint` сохранённого
Metrics DTO.

### 6.4. Failure events

- `parser.failed.v1`;
- `metrics.failed.v1`.

```json
{
  "payload": {
    "stage": "parser",
    "failed_event_id": "...",
    "error_code": "source_not_found",
    "message": "safe diagnostic message",
    "retryable": false
  }
}
```

Failure payload не содержит traceback, исходники, credentials или внутренние
пути, отсутствовавшие во входном событии.

## 7. Порты application layer

### 7.1. Общие порты

```python
class EventPublisher(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...

class InputSignalSource(Protocol):
    def start(self, handler: Callable[[Mapping[str, object], DeliveryContext], DeliveryDecision]) -> None: ...
    def stop(self) -> None: ...

class IdempotencyStore(Protocol):
    def claim(self, key: str, payload_digest: str) -> ClaimResult: ...
    def load(self, key: str) -> ProcessingRecord | None: ...
    def record_saved(self, key: str, event: EventEnvelope) -> None: ...
    def record_published(self, key: str) -> None: ...
    def record_failure(self, key: str, event: EventEnvelope) -> None: ...
```

`DeliveryDecision`:

- `ACK` — завершено или уже было завершено;
- `RETRY` — временная ошибка, допустима повторная доставка;
- `REJECT` — контрактно некорректное сообщение, повтор бессмысленен.

Эти значения не содержат API конкретного брокера.

`DeliveryContext` содержит авторизованный `tenant_id`, полученный будущим
transport adapter из доверенного контекста доставки. Handler обязан сверить его
с `envelope.tenant_id`; значение из payload само по себе не считается
достаточным доказательством tenant.

### 7.2. Parser Service

```python
class SourceResolver(Protocol):
    def materialize(self, source_uri: str) -> ContextManager[Path]: ...

class GraphStagingArea(Protocol):
    def create_target(self, artifact_key: str) -> ContextManager[Path]: ...

class GraphArtifactStore(Protocol):
    def save(self, staged_path: Path, artifact_key: str) -> ArtifactDescriptor: ...

class ParserGateway(Protocol):
    def parse(self, source_path: Path, output_path: Path) -> Path: ...
```

### 7.3. Metrics Service

```python
class GraphInputResolver(Protocol):
    def materialize(self, graph_uri: str) -> ContextManager[Path]: ...

class MetricsStagingArea(Protocol):
    def create_target(self, artifact_key: str) -> ContextManager[Path]: ...

class MetricsArtifactStore(Protocol):
    def save(self, staged_path: Path, artifact_key: str) -> ArtifactDescriptor: ...

class MetricsGateway(Protocol):
    def calculate(self, graph_path: Path, output_path: Path) -> Path: ...
```

Разделение materialize, staging и save необходимо из-за файловых API ядер и
позволяет будущему adapter загрузить удалённый объект во временное локальное
хранилище без изменения handler.

## 8. Application handlers

### 8.1. Parser handler

1. Декодировать и проверить `parser.start.v1`.
2. Сверить авторизованный tenant из `DeliveryContext` с envelope.
3. Вычислить digest нормализованного значимого envelope.
4. Захватить tenant/version-safe idempotency claim.
5. Материализовать `source_uri` в локальный `Path` и проверить tenant namespace.
6. Получить staging path.
7. Вызвать `ParserGateway.parse()`.
8. Проверить metadata и fingerprint Graph DTO.
9. Сохранить артефакт через `GraphArtifactStore`.
10. Один раз создать `graph.ready.v1`.
11. Сохранить полное выходное событие в idempotency state.
12. Опубликовать событие.
13. Зафиксировать `PUBLISHED` и вернуть `ACK`.

### 8.2. Metrics handler

1. Декодировать `graph.ready.v1`.
2. Сверить авторизованный tenant из `DeliveryContext` с envelope.
3. Вычислить digest нормализованного значимого envelope.
4. Захватить tenant/version-safe idempotency claim.
5. Проверить tenant namespace `graph.uri` и материализовать его.
6. Сверить checksum и входную metadata.
7. Получить staging path.
8. Вызвать `MetricsGateway.calculate()`.
9. Проверить envelope результата и graph fingerprint.
10. Сохранить артефакт через `MetricsArtifactStore`.
11. Один раз создать `metrics.ready.v1`.
12. Сохранить выходное событие.
13. Опубликовать событие.
14. Зафиксировать `PUBLISHED` и вернуть `ACK`.

Обязательный порядок:

```text
calculate -> save artifact -> persist output event -> publish -> mark published
```

Ready event никогда не публикуется до успешного сохранения артефакта.

## 9. Идемпотентность и доставка

Ключи обработки включают tenant, версию handler и версию производимого
результата:

```text
parser:<tenant>:<handler-version>:graph-s1-p7:<input-event-id>
metrics:<tenant>:<handler-version>:metrics-s1-m4:<input-event-id>
```

Хранится также digest нормализованных значимых полей envelope: `event_id`,
`event_type`, envelope schema, `occurred_at`, tenant, correlation/causation,
producer identity и payload. Broker delivery headers, attempt counter и время
фактической доставки в digest не входят. Одинаковый `event_id` в одном tenant с
другим digest — ошибка `idempotency_payload_conflict`.

Состояния:

```text
CLAIMED -> SAVED -> PUBLISHED
        -> FAILED_SAVED -> FAILED_PUBLISHED
```

Поведение повторной доставки:

- `PUBLISHED` — не запускать ядро и вернуть `ACK`;
- `SAVED` — не пересчитывать, повторно опубликовать сохранённое событие;
- `FAILED_PUBLISHED` — вернуть `ACK`;
- `FAILED_SAVED` — повторить публикацию сохранённого failure event;
- активный `CLAIMED` — вернуть `RETRY`;
- просроченный `CLAIMED` — разрешить повторный claim по lease policy.

Artifact namespace также включает tenant и версии результата:

```text
tenants/<tenant>/graphs/schema-1/parser-7/events/<input-event-id>/graph.json
tenants/<tenant>/metrics/schema-1/metrics-4/events/<input-event-id>/metrics.json
```

Один key с другим содержимым даёт `artifact_conflict`. Handler и artifact
adapter сверяют соответствие tenant из `DeliveryContext`, envelope, artifact key
и возвращаемого URI. Перезапись namespace другого tenant запрещена, даже если
путь технически находится внутри общего storage root.

Без общей транзакции state store и publisher exactly-once недостижим. Контракт:

- идемпотентная обработка;
- at-least-once публикация;
- допустимые дубликаты одного и того же сохранённого output event ID.

## 10. Ошибки

Постоянные ошибки создают failure event и завершаются `ACK`/`REJECT` согласно
правилам runtime:

- malformed envelope;
- неизвестная версия;
- неподдерживаемая URI scheme;
- окончательно отсутствующий source/graph;
- невалидный Graph DTO;
- неподдерживаемая Parser semantics для Metrics;
- checksum/fingerprint mismatch;
- payload или artifact conflict.

Временные ошибки возвращают `RETRY` без ложного failure event:

- временная недоступность publisher/store;
- занятый claim;
- временная ошибка чтения или записи;
- невозможность создать staging area;
- остановка процесса во время обработки.

Если артефакт успешно сохранён, сбой публикации ready event не превращает
операцию в `parser.failed`/`metrics.failed`. При повторе публикуется сохранённый
ready event без повторного запуска ядра.

## 11. Адаптеры без внешней инфраструктуры

### Production-neutral adapters

- `ParserCoreAdapter` вызывает только `parser.parse_project`;
- `MetricsCoreAdapter` вызывает только `metrics.calculate_metrics`.

### Local adapters

- `LocalSourceResolver`;
- `LocalGraphInputResolver`;
- `LocalStagingArea`;
- `LocalGraphArtifactStore`;
- `LocalMetricsArtifactStore`;
- `FileIdempotencyStore`.

Они поддерживают path/`file://`, ограничивают допустимый root, защищают от
`..`/symlink escape, проверяют tenant namespace и используют temporary file +
atomic replace.

### Test/stub adapters

- `ManualInputSignalSource`;
- `RecordingEventPublisher`;
- `InMemoryIdempotencyStore`;
- `FixedClock`;
- `DeterministicIdGenerator`.

`RecordingEventPublisher` только записывает events и умеет имитировать ошибку.
Он не симулирует конкретный брокер. Полностью in-memory artifacts не нужны,
поскольку ядра работают с `Path`; тесты используют временные директории.

## 12. Composition и lifecycle

`composition.py` предоставляет два способа сборки:

```text
build_parser_application(ports...)
build_metrics_application(ports...)
```

для будущих adapters и:

```text
build_local_parser_runtime(settings)
build_local_metrics_runtime(settings)
```

для локальной разработки.

Handler не читает environment variables и не создаёт adapter самостоятельно.
Settings локального runtime содержат только artifact/staging/state roots, lease
duration и instance name. Broker/Redis/DB URLs отсутствуют.

Lifecycle:

```text
CREATED -> STARTING -> RUNNING -> STOPPING -> STOPPED
```

Runtime сначала прекращает приём новых сигналов, затем ожидает активные handlers
до timeout и закрывает ports. Текущие ядра синхронны, поэтому application layer
также остаётся синхронным; будущий async transport adapter сам выбирает worker
context.

## 13. Правила зависимостей

```text
parser_service.application -> parser_service.contracts
parser_service.adapters.parser_core -> parser public API

metrics_service.application -> metrics_service.contracts
metrics_service.adapters.metrics_core -> metrics public API
```

Запрещено:

```text
parser_service -> metrics_service
metrics_service -> parser_service
service handlers -> parser.logic / metrics.logic
service packages -> broker / Redis / DB / S3 SDK
```

Producer и consumer DTO `graph.ready.v1` хранятся независимо. Compatibility
test сериализует producer representation и декодирует consumer representation.
Metrics production code не импортирует contracts Parser Service.

## 14. План тестирования

### Contract tests

- строгая сериализация/deserialization envelope;
- обязательность полей и типов;
- неподдерживаемые версии;
- стабильные wire names;
- отсутствие side effects при decode;
- producer/consumer compatibility для `graph.ready.v1`.

### Handler tests

- ядро вызывается ровно один раз;
- save происходит раньше publish;
- событие содержит descriptor сохранённого артефакта;
- save failure не создаёт ready event;
- publish failure возвращает `RETRY`;
- повтор после save не запускает ядро;
- неверный event type не вызывает ports.

### Idempotency tests

- повторы для каждого состояния;
- один ID с разным payload;
- изменение значимого envelope field, включая `occurred_at`, даёт conflict;
- изменение delivery metadata не меняет digest;
- одинаковый event ID в разных tenants;
- несовпадение authorized/envelope/URI tenant;
- разные handler/result versions для одного input event;
- стабильный output event ID;
- active/expired claim;
- failure event replay;
- artifact conflict;
- сбой между каждой парой соседних шагов state machine.

### Local adapter tests

- path и `file://`;
- unsupported scheme;
- root traversal и symlink escape;
- atomic save и cleanup staging;
- сохранение прежнего результата при ошибке;
- round-trip file idempotency state.

### Integration tests

```text
temporary source -> parser.start -> real Parser Core
-> local graph artifact -> recorded graph.ready
```

```text
graph artifact -> graph.ready -> real Metrics Core
-> local metrics artifact -> recorded metrics.ready
```

Локальный choreography test вручную передаёт записанный `graph.ready` в Metrics
handler. В production code общей orchestration-функции не появляется.

## 15. Этапы разработки

### Этап 1. Wire contracts

1. Создать две директории.
2. Реализовать envelope и stage DTO.
3. Зафиксировать event names и major versions.
4. Добавить compatibility fixture для `graph.ready.v1`.

### Этап 2. Application model

1. Объявить Protocol ports.
2. Ввести `ArtifactDescriptor`, `ProcessingRecord`, `ClaimResult`.
3. Ввести `DeliveryDecision` и typed errors.
4. Зафиксировать retry/non-retry классификацию.

### Этап 3. Parser Service

1. Добавить Parser Core adapter.
2. Реализовать handler и ordering.
3. Добавить in-memory state и recording publisher.
4. Покрыть success/failure/crash boundaries.

### Этап 4. Metrics Service

1. Добавить Metrics Core adapter.
2. Реализовать handler и fingerprint checks.
3. Добавить in-memory state и recording publisher.
4. Покрыть unsupported Graph DTO и повторы.

### Этап 5. Local persistence

1. Реализовать local URI resolvers.
2. Реализовать staging и artifact stores.
3. Реализовать file idempotency store.
4. Добавить path boundaries и cleanup.

### Этап 6. Composition и runtime

1. Добавить dependency-injected builders.
2. Добавить local builders и manual input.
3. Реализовать start/stop/graceful drain.
4. Проверить независимый запуск каждого runtime.

### Этап 7. Интеграция

1. Прогнать каждый shell с реальным ядром.
2. Проверить contract compatibility.
3. Проверить локальную choreography.
4. Проверить повторную доставку на обеих стадиях.

## 16. Критерии готовности

Parser Service готов, если:

- принимает только `parser.start.v1`;
- вызывает публичный `parser.parse_project`;
- сохраняет Graph DTO до publish;
- публикует `graph.ready.v1` или `parser.failed.v1`;
- после `SAVED` не запускает parsing повторно;
- не знает о Metrics Service.

Metrics Service готов, если:

- принимает только `graph.ready.v1`;
- вызывает публичный `metrics.calculate_metrics`;
- проверяет checksum, versions и fingerprint;
- сохраняет Metrics DTO до publish;
- публикует `metrics.ready.v1` или `metrics.failed.v1`;
- не знает следующих потребителей.

Общие критерии:

- ядра и Graph DTO не изменены;
- сервисы не импортируют друг друга;
- нет внешних инфраструктурных SDK;
- порядок save-before-publish закреплён тестами;
- documented at-least-once допускает стабильные дубликаты;
- local adapters позволяют проверить полный код оболочек;
- будущий transport adapter подключается только через ports/composition.

## 17. Основные риски

1. Файловые ядра требуют materialization удалённых URI и cleanup временных
   данных.
2. Без транзакции store/publisher возможны дубликаты, но не должна возникать
   потеря уже сохранённого результата.
3. File idempotency adapter безопасен только в документированном локальном
   режиме; распределённая синхронизация остаётся будущему adapter.
4. Дублированный producer/consumer contract может дрейфовать; обязательны
   compatibility fixtures.
5. Неверная классификация ошибок вызывает бесконечные retries или потерю
   обработки.
6. Workflow-логика может случайно проникнуть в handlers; запрещены команды
   следующей стадии и ожидание чужого результата.
7. Нельзя публиковать ready event со staging URI или до durable save.
