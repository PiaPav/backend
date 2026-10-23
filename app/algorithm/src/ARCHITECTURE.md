# Актуальная архитектура сервиса статического анализа

## 1. Назначение и границы документа

Сервис анализирует Python-проект в два независимых этапа:

1. **Parser Core** читает исходники, строит семантический граф и сохраняет его
   как версионированный Graph DTO.
2. **Metrics Core** читает готовый Graph DTO, строит аналитические проекции,
   рассчитывает метрики и сохраняет версионированный Metrics DTO.

Документ описывает текущее состояние следующих актуальных элементов:

- `graph_dto`;
- `parser`;
- `metrics`;
- `utils`, которые формально актуальны, но не используются ядрами.

`infrastructure`, `services`, `gpt_work_dir` и `main.py` признаны устаревшими и
не входят в описываемую архитектуру. Они не должны служить основой новой
сервисной оболочки.

## 2. Архитектурное решение

Декомпозиция на два ядра **завершена в запланированных границах**, поэтому
дальнейшее механическое разделение внутренних модулей не требуется. Текущие
Graph DTO schema v1 / Parser semantics v7 и Metrics DTO schema v1 / Metrics
semantics v4 следует закрепить как базовую совместимую версию.

При этом внутренняя продуктовая логика ядер покрывает заявленную цель только
частично. Система строит согласованный граф доказанных статических отношений,
но не полный граф всех возможных связей Python-программы. Поэтому рекомендуется:

- сохранить текущие границы `Parser -> Graph DTO -> Metrics`;
- продолжать семантическое развитие прежде всего Parser Core;
- выпускать изменения смысла графа и формул только новыми версиями semantics;
- не трактовать текущие метрики как абсолютную оценку качества архитектуры;
- отделить будущую транспортную оболочку от чистой логики ядер.

Итог: **закрепить текущую декомпозицию, но не замораживать внутреннюю логику
ядер**.

## 3. Текущий поток данных

```text
Каталог Python-проекта
        |
        v
parser.parse_project(source_path, graph_path)
        |
        +-- обнаружение *.py и построение AST
        +-- индекс модулей и объявлений
        +-- разрешение импортов, типов, наследования и вызовов
        +-- сбор нейтральных complexity facts
        +-- build_graph_v1()
        +-- validate_graph_v1()
        +-- атомарная запись JSON
        |
        v
Graph DTO schema v1 / parser semantics v7
        |
        v
metrics.calculate_metrics(graph_path, metrics_path)
        |
        +-- загрузка и проверка Graph DTO semantics v6/v7
        +-- единый immutable MetricsGraphProjection
        +-- расчёт всех разделов метрик
        +-- атомарная запись JSON
        |
        v
Metrics DTO schema v1 / metrics semantics v4
```

Ядра не импортируют и не вызывают друг друга. Их общая граница — пакет
`graph_dto` и JSON-файл. Metrics не читает Python-исходники, AST или legacy
`body` и не пытается повторно разрешать строковые имена.

## 4. Parser Core

### 4.1. Публичные контракты

Актуальный контракт:

```python
parse_project(source_path: Path, output_path: Path) -> Path
```

Он принимает только `Path`, строит Graph DTO, записывает его через временный
файл и `os.replace`, после чего возвращает абсолютный результирующий путь.

`starter(input_project) -> dict` сохранён как legacy in-memory API. Он создаёт
старое представление с `body` и не является входом актуального Metrics Core.
Из-за совместимости `parse_project` пока выполняет полный legacy-анализ, а затем
строит отдельную canonical-проекцию из внутреннего `ProjectIndex`.

### 4.2. Внутренние этапы

1. `ProjectIndex` рекурсивно находит `*.py`, исключает служебные каталоги,
   читает UTF-8/UTF-8 BOM, строит AST и индексирует имена модулей.
2. `collect_imports` сохраняет статические import occurrences, включая
   вложенные импорты.
3. `collect_definitions` извлекает верхнеуровневые классы, функции, часть
   констант, непосредственные методы и поля классов.
4. `RelationResolver` разрешает локальное наследование, типы полей и чтения
   объявленных `self.<field>`.
5. `classify_classes` синтаксически классифицирует обычные, abstract, enum и
   dataclass-классы.
6. `CallResolver` учитывает lexical scope, порядок присваиваний и объединение
   ветвей; сохраняет каждый callsite, вложенность, `await` и статус разрешения.
7. `build_graph_v1` преобразует внутренние AST-модели в Graph DTO semantics v7.

Внутренние модели содержат AST, абсолютные пути и legacy-поля и намеренно не
являются межсервисным DTO.

### 4.3. Что Parser уже моделирует

- файлы, классы, функции, методы, поля и ограниченный набор констант;
- ownership/containment;
- статические импорты и локальную import topology;
- наследование и типы полей для точно разрешённых локальных классов;
- чтение объявленных полей методами;
- локальные, импортированные и некоторые типизированные вызовы;
- вызовы конструкторов и синтетический `__init__`, когда он нужен как цель;
- отдельные callsites и агрегированные `calls`/`awaits` с multiplicity;
- нейтральные факты управляющих конструкций и occurrences для Metrics;
- предупреждения о коллизиях имён модулей.

### 4.4. Ограничения Parser

Текущий граф нельзя считать полной моделью Python. Существенные пробелы:

- вложенные функции, классы и lambda не являются самостоятельными nodes;
- нет полноценной модели closures, `global`/`nonlocal`, higher-order calls и
  callable values;
- `ambiguous` предусмотрен контрактом, но candidate analysis фактически
  ограничен;
- type inference основан преимущественно на простых аннотациях и прямых
  присваиваниях конструкторов;
- нет отношений decorators, override/implementation, parameter type и return
  type;
- не моделируются exports/re-exports, `__all__`, wildcard imports и полноценные
  namespace/source-root rules;
- нет полиморфного dispatch, общей модели `super()`, descriptors, reflection и
  monkey patching;
- field access не разделён на read/write/delete;
- одна синтаксическая ошибка останавливает анализ всего проекта;
- diagnostics не объясняют единым форматом причины каждого неразрешённого
  отношения;
- IDs детерминированы для одинакового входа, но меняются при перемещении кода;
- нет инкрементального анализа, cancellation и ресурсных лимитов.

Статусы `exact`, `ambiguous`, `external`, `dynamic` и `unresolved` отражают
ограничения статического разрешения. Только `exact` создаёт внутреннюю
топологию, поэтому граф является консервативной нижней оценкой связей.

## 5. Graph DTO

`graph_dto/contract.py` — общая декларативная граница ядер. Текущий Parser
производит:

```json
{
  "schema_version": 1,
  "parser_semantics_version": 7,
  "project": {"fingerprint": "sha256"},
  "nodes": [],
  "edges": [],
  "callsites": [],
  "type_references": [],
  "import_references": [],
  "owner_structural_facts": [],
  "diagnostics": []
}
```

### 5.1. Узлы и отношения

Поддерживаются node kinds `file`, `module`, `class`, `field`, `function`,
`method`, `constant`. Текущий Parser использует `file` как корневой node.

Поддерживаются edges:

- `contains`: owner -> declaration;
- `imports`: dependent -> dependency;
- `inherits`: child class -> parent class;
- `field_type`: field -> class;
- `accesses_field`: method -> field;
- `calls`/`awaits`: caller -> callable target.

### 5.2. Основные инварианты

- относительные POSIX-пути;
- уникальные IDs и существующие внутренние ссылки;
- согласованность `parent_id` и `contains`;
- ациклический containment forest;
- один owner для каждого callable;
- соответствие exact callsites агрегированным call edges и их весам;
- соответствие exact imports и type references типизированным edges;
- строгая структура complexity и owner structural facts;
- fingerprint, не зависящий от порядка канонических коллекций.

Общий validator знает исторические semantics 1–7. Актуальный Metrics принимает
только самодостаточные semantics 6 и 7. Semantics 7 запрещает legacy `body`.

### 5.3. Ограничения DTO

- diagnostics слабо типизированы;
- часть objects допускает дополнительные поля, тогда как другие секции
  проверяются строго;
- нет relation confidence/provenance и устойчивой identity объявления между
  ревизиями;
- нет отдельного публичного validator для Metrics DTO;
- fingerprint описывает логическое содержимое графа, но не заменяет checksum
  передаваемого файла и metadata артефакта.

## 6. Metrics Core

### 6.1. Контракт и проекции

```python
calculate_metrics(graph_path: Path, output_path: Path) -> Path
```

Metrics принимает Graph DTO schema v1 / Parser semantics 6 или 7, полностью
валидирует его, создаёт ровно один immutable `MetricsGraphProjection` и передаёт
его специализированным calculators. Результат:

```json
{
  "schema_version": 1,
  "metrics_semantics_version": 4,
  "input": {
    "graph_schema_version": 1,
    "graph_fingerprint": "..."
  },
  "metrics": {}
}
```

Проекция содержит ориентированные графы импортов файлов и условных пакетов,
неориентированную проекцию импортов, weighted call graph, inheritance,
field-type и field-access relations. Все topology relations берутся только из
canonical IDs.

### 6.2. Рассчитываемые разделы

- **size**: каталоги, файлы, классы, функции, методы, поля, константы;
- **activity**: структурные occurrences вызовов и прямых импортов, средние;
- **dependency_graph**: density, fan-in/out, слабые компоненты, import cycles,
  изолированные файлы;
- **architecture**: package coupling, instability, abstractness, distance,
  package cycles, articulation files и bridges;
- **code_quality**: cyclomatic/cognitive complexity, span lines, nesting,
  async/await и exception facts;
- **object_oriented**: WMC, CBO, RFC, LCOM, DIT, NOC;
- **call_graph**: SCC/recursion, цепочки, reachability, PageRank, betweenness,
  multiplicity и относительный hotspot score с именем `risk`.

### 6.3. Правила интерпретации

Текущие метрики полезны для поиска hotspots и сравнения элементов внутри одного
анализа, но имеют важные ограничения:

1. Topology учитывает только `exact` internal relations. DIT, NOC, CBO, RFC,
   centrality и reachability являются нижними оценками при наличии unresolved,
   external, ambiguous или dynamic связей.
2. `activity.calls` берётся из совместимых structural facts, а call graph — из
   canonical callsites. Аналогично activity imports и import topology описывают
   разные совокупности и не обязаны совпадать.
3. «Пакет» сейчас определяется первым сегментом пути, а не семантикой Python
   package. Package metrics могут отражать верхний каталог, например `src`.
4. Для пакета без связей instability принудительно равна `0`, а без классов
   abstractness равна `0`; distance в таких случаях выглядит определённой, хотя
   исходные отношения методологически неприменимы.
5. `risk` нормирует компоненты по максимумам текущего проекта. Это относительный
   hotspot score `[0, 100]`, не вероятность и не межпроектная шкала.
6. `maximum_call_chain_depth` — глубина DAG, полученного после свёртки SCC, а не
   runtime call-stack depth.
7. Articulation и bridges рассчитаны на неориентированной import-проекции и не
   означают runtime single point of failure.
8. Cognitive complexity — собственная формула проекта; пороги 10/15/4 являются
   эвристиками. LOC — длина span, включая комментарии и пустые строки.
9. PageRank и betweenness игнорируют multiplicity, хотя веса call edges
   сохраняются отдельно.
10. Средние значения скрывают распределение; медианы и квантили отсутствуют.

Следовательно, отчёт должен показывать resolution coverage и оговорки вместе с
числами. Низкая связанность может означать как хорошую архитектуру, так и слабое
разрешение отношений Parser.

## 7. Формально актуальные `utils`

`utils/config.py` и `utils/logger.py` актуальными ядрами не импортируются.
`config.py` смешивает server, broker, S3 и gRPC-настройки, загружает `.env` и
создаёт глобальный `CONFIG` при импорте. `logger.py` создаёт обычный stdout
logger без correlation/trace context.

Эти модули не являются общей платформой Parser и Metrics. Для будущих
микросервисов конфигурация, logging и transport adapters должны находиться во
внешних service shells, а не внутри core packages.

## 8. Рекомендуемое развитие внутренней логики

### P0. Зафиксировать критерии полноты

- определить обязательный перечень отношений Python;
- разделить `proven`, `possible`, `dynamic` и `unsupported`;
- измерять exact-resolution coverage на репрезентативных проектах;
- определить лимиты размера, времени и памяти;
- зафиксировать текущие версии как неизменяемый baseline.

### P1. Parser semantics следующей версии

1. Добавить nodes для nested functions/classes и lambda с корректными owners.
2. Реализовать реальные candidate sets для ambiguous resolution.
3. Разделить builtin, external, dynamic, unresolved и unsupported.
4. Ввести типизированные diagnostics с reason code и location.
5. Добавить decorators, override/implementation, parameter/return type,
   exports/re-exports и явную package/source-root model.
6. Улучшить type propagation и method dispatch без выдачи предположений за
   `exact`.
7. Поддержать частичный результат для повреждённых файлов и ресурсные лимиты.

Эти изменения требуют нового `parser_semantics_version`.

### P2. Graph DTO

- строгая схема всех объектов и Metrics DTO;
- confidence/provenance для отношений;
- стабильная declaration identity отдельно от revision/location identity;
- metadata артефакта: media type, producer version, checksum и размер;
- явная deprecation policy исторических semantics.

### P3. Metrics semantics

1. Добавить coverage/confidence рядом с каждой topology-dependent metric.
2. Перенести package identity в Graph DTO или конфигурируемую модель source
   roots.
3. Возвращать `null`/N/A для неопределённых Martin ratios.
4. Переименовать `risk` в `relative_hotspot_score`.
5. Развести structural occurrences и canonical references/callsites в названиях.
6. Добавить median, p90/p95, maximum и долю превышения порогов.
7. Добавить правила запрещённых зависимостей между архитектурными слоями.
8. Профилировать и ограничить дорогие reachability/betweenness расчёты.

Изменения формул, порогов, N/A semantics и output meaning требуют нового
`metrics_semantics_version`.

## 9. Превращение ядер в микросервисы

### 9.1. Рекомендуемая общая модель

Core packages остаются transport-agnostic. Вокруг каждого создаётся service
shell:

```text
Broker -> Parser worker -> Redis -> Broker -> Metrics worker -> Redis -> Broker
                                                                    |
                                                                    v
                                                         следующий сервис
```

Parser получает команду с URI/путём к исходникам, создаёт Graph DTO, сохраняет
его и публикует `graph.ready`. Metrics по ссылке получает граф, проверяет
checksum и DTO, создаёт Metrics DTO, сохраняет его и публикует `metrics.ready`.

Все опубликованные ready-артефакты должны долговременно храниться как immutable
blobs в object storage: durable broker event не должен пережить доступность
своего результата. В Redis хранятся URI, checksum, schema/semantics, статус и
TTL, а небольшой DTO при необходимости дополнительно кэшируется как сжатый
blob. Потеря кэша не влияет на повторное чтение или replay. Redis не является
единственным хранилищем ready-артефакта даже для небольшого DTO.

### 9.2. Событийный envelope

```json
{
  "event_id": "uuid",
  "event_type": "analysis.parser.start.v1",
  "occurred_at": "RFC3339",
  "analysis_id": "uuid",
  "tenant_id": "tenant",
  "correlation_id": "uuid",
  "causation_id": "uuid",
  "attempt": 1,
  "producer": {"service": "orchestrator", "version": "..."},
  "traceparent": "...",
  "payload": {}
}
```

События содержат metadata и ссылки/ключи, но не исходный код и не полный DTO.
Broker отвечает за доставку; Redis — за состояние, idempotency, metadata и
доступ к кэшу; durable immutable object storage — за долговременное содержимое
каждого опубликованного ready-артефакта.

### 9.3. Последовательность событий

#### 1. Запуск Parser

Topic/queue: `analysis.parser.start.v1`.

```json
{
  "payload": {
    "source": {
      "uri": "file:///workspace/input или object://bucket/key",
      "sha256": "..."
    },
    "requested": {
      "graph_schema_version": 1,
      "parser_semantics_version": 7
    },
    "limits": {
      "deadline": "RFC3339",
      "max_unpacked_bytes": 100000000,
      "max_files": 10000
    }
  }
}
```

Путь должен быть доступен Parser worker и находиться в разрешённом root. Для
распределённого deployment локальный путь необходимо заменить URI общего
хранилища или примонтированного read-only volume.

#### 2. Graph готов

Topic/queue: `analysis.graph.ready.v1`.

```json
{
  "payload": {
    "graph": {
      "redis_key": "analysis:{tenant:analysis_id}:graph:p7",
      "uri": "object://graphs/{tenant}/{analysis}/{fingerprint}.json",
      "sha256": "...",
      "size_bytes": 123,
      "schema_version": 1,
      "parser_semantics_version": 7,
      "graph_fingerprint": "..."
    },
    "diagnostics": {
      "warnings": 0,
      "unresolved_calls": 0
    }
  }
}
```

Parser сначала публикует immutable артефакт в durable storage, затем metadata и
опциональный кэш в Redis и только после этого событие. Metrics не принимает
событие успешно, пока checksum и Graph DTO не проверены.

#### 3. Metrics готовы

Topic/queue: `analysis.metrics.ready.v1`.

```json
{
  "payload": {
    "metrics": {
      "redis_key": "analysis:{tenant:analysis_id}:metrics:m4",
      "uri": "object://metrics/{tenant}/{analysis}/{checksum}.json",
      "sha256": "...",
      "size_bytes": 123,
      "schema_version": 1,
      "metrics_semantics_version": 4
    },
    "graph_fingerprint": "..."
  }
}
```

Абстрактный следующий сервис подписывается на событие, читает Metrics DTO из
Redis или по URI и сверяет checksum и expected semantics.

### 9.4. Redis key model

```text
analysis:{tenant:analysis_id}:state
analysis:{tenant:analysis_id}:graph:p{parser_semantics}
analysis:{tenant:analysis_id}:metrics:m{metrics_semantics}
idempotency:parser:tenant:<tenant>:source:<source_sha256>:p<semantics>
idempotency:metrics:tenant:<tenant>:graph:<graph_fingerprint>:m<semantics>
lease:{tenant:analysis_id}:{service}
```

`state` хранит versioned state machine, ссылки, checksums, timestamps и ошибку.
Blob values должны иметь TTL и лимит размера; metadata может жить дольше. Нельзя
использовать Redis Pub/Sub как единственный надёжный брокер: без durable queues
и acknowledgements сообщения теряются при отключении consumer.

Фрагмент `{tenant:analysis_id}` является единым Redis Cluster hash tag только
для ключей одного анализа, которым нужны атомарные операции; он не концентрирует
все задания tenant в одном slot. В idempotency keys используются обозначенные
через `<...>` placeholders без Redis hash tag: после подстановки весь ключ
хешируется и распределяется в том числе по input hash/fingerprint. Service shell
обязан сверять tenant из авторизованного контекста, события, Redis key и
artifact URI перед каждым чтением и записью.

### 9.5. Варианты workflow

#### Вариант A — choreography

```text
Ingest -> parser.start
Parser -> graph.ready
Metrics -> metrics.ready
Next service -> next.completed
```

Каждый consumer самостоятельно реагирует на событие. В Redis хранятся
idempotency records, leases, stage status и данные/ссылки на артефакты.

Плюсы: слабая связность, независимое масштабирование, простое добавление новых
подписчиков. Минусы: распределённая retry/timeout policy и сложнее наблюдать весь
workflow. Подходит, когда у `graph.ready` и `metrics.ready` будет несколько
независимых потребителей.

#### Вариант B — центральный orchestrator (рекомендуется первым)

```text
Orchestrator -> parser.start
Parser -> graph.ready
Orchestrator -> metrics.start
Metrics -> metrics.ready
Orchestrator -> next.start
Next service -> next.ready
```

Orchestrator ведёт в Redis state machine:

```text
RECEIVED -> PARSER_RUNNING -> GRAPH_READY -> METRICS_RUNNING
         -> METRICS_READY -> NEXT_RUNNING -> COMPLETED | FAILED
```

Плюсы: ясный статус, централизованные timeout, cancellation и re-drive.
Минусы: orchestrator — критический компонент; нужны version/fencing tokens,
чтобы просроченный worker не перезаписал новый результат. Этот вариант лучше
всего соответствует текущему строго последовательному pipeline.

#### Вариант C — partitioned event log

Команды и результаты находятся в durable topics, partition key —
`tenant_id + analysis_id`; Parser, Metrics и следующий сервис используют
отдельные consumer groups. Redis служит быстрым control plane и кэшем, broker
log — источником истории, immutable storage — источником артефактов.

Плюсы: высокая пропускная способность, replay и массовый перерасчёт Metrics
новой версии. Минусы: высокая эксплуатационная сложность и необходимость
управлять schema compatibility, retention и replay storm. Вариант нужен только
после появления подтверждённого объёма и сценариев reprocessing.

### 9.6. Надёжность и идемпотентность

- ключ операции включает tenant, input hash/fingerprint и semantics version;
- consumer ведёт inbox по `event_id` и безопасно обрабатывает повторную доставку;
- артефакт записывается в durable storage под детерминированным immutable key,
  после чего его metadata и опциональный кэш публикуются в Redis;
- acknowledge выполняется только после сохранения результата и события/outbox;
- Redis lock используется только с TTL и fencing token;
- retryable ошибки получают exponential backoff с jitter;
- повреждённый input, неизвестная schema и checksum mismatch не повторяются
  бесконечно;
- после лимита попыток сообщение попадает в stage-specific DLQ;
- атомарность «сохранить результат + отправить событие» обеспечивается outbox
  либо идемпотентной повторной публикацией уже сохранённого immutable результата.

### 9.7. Наблюдаемость и безопасность

Во всех событиях и логах нужны `analysis_id`, `event_id`, `correlation_id`,
`causation_id`, `traceparent`, producer version и semantics versions.

Основные telemetry:

- broker lag, stage duration, retry и DLQ rate;
- размеры исходников, графов и Metrics DTO;
- resolution/coverage rates;
- Redis memory, TTL expiry, lock contention и cache hit rate;
- распределение работ по schema/semantics version.

Требования безопасности:

- TLS/mTLS, broker ACL и Redis ACL;
- tenant-scoped keys и проверка URI namespace;
- read-only source mounts или короткоживущие signed URLs;
- checksum до обработки и после чтения;
- защита от path traversal, symlink escape и archive bombs;
- ограничения file count, unpacked bytes, CPU, memory и deadline;
- секреты только из secret manager;
- исходники и DTO не записываются в broker payload и логи;
- отдельная retention policy для source, graph, metrics и operational state.

## 10. Итог

Текущая реализация образует хорошую базу двух независимых ядер: файловые API,
строгий Graph DTO, единая аналитическая проекция и отсутствие повторного
semantic resolution в Metrics уже реализуют правильную границу ответственности.

Для цели «покрыть все взаимосвязи Python-кода» этого недостаточно. Главный
следующий этап — не новая декомпозиция, а версионированное расширение Parser
semantics, повышение наблюдаемой полноты графа и корректная интерпретация Metrics.
Микросервисную оболочку следует строить отдельно; для первого production-варианта
предпочтителен orchestrator, durable broker, Redis state/idempotency и durable
immutable-хранилище всех опубликованных ready-артефактов.
