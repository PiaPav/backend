# План профилей наполненности графа и метрик

## 1. Цель и неизменяемые границы

Нужно предоставить несколько вариантов данных для разных потребителей: от
минимального обзора до полного графа и подробных метрик. При этом текущая
семантика анализа не меняется:

- Parser продолжает строить Graph DTO schema v1 / Parser semantics v7;
- Metrics продолжает вычислять Metrics DTO schema v1 / Metrics semantics v4;
- полнота разрешения Python-конструкций не дорабатывается;
- formulas и thresholds не меняются.

Основное решение:

> Parser всегда создаёт один полный canonical Graph DTO, а Metrics всегда
> рассчитывается из полного валидированного графа. Все сокращённые варианты
> создаются после этого как детерминированные views.

Не следует создавать разные алгоритмы Parser `minimal`, `calls_only` и
`architecture_only`. Иначе один проект будет иметь несколько несовместимых
семантических графов.

## 2. Термины

Точный versioned contract первого набора профилей, включая whitelist и
population matrices, находится в `DATA_PROFILES_INITIAL_CONTRACT.md`.

- **Canonical Graph DTO** — полный текущий Graph DTO v1.
- **Graph View DTO** — сокращённая проекция canonical graph.
- **Graph Summary DTO** — агрегированное представление, которое уже не является
  подграфом.
- **Metrics DTO** — полный текущий результат Metrics.
- **Metrics View DTO** — неизменённые значения выбранных разделов полного
  Metrics DTO.
- **Globally lossless** — позволяет восстановить полный исходный DTO.
- **Query-lossless** — сохраняет всё для явно указанного класса запросов.
- **One-way projection** — полное представление восстановить нельзя.

Только full-профили являются globally lossless.

## 3. Общая архитектура профилей

```text
Python sources
      |
      v
Parser Core
      |
      v
Canonical Graph DTO v1 / semantics v7
      |                         |
      |                         +--> Graph View/Summary projector
      v
Metrics Core
      |
      v
Full Metrics DTO v1 / semantics v4
      |
      +--> Metrics View projector
```

Metrics не принимает сокращённый Graph View. Graph и Metrics views являются
соседними проекциями одного полного source graph и связываются по
`graph_fingerprint`.

## 4. Общий envelope view

Graph View:

```json
{
  "artifact_kind": "graph_view",
  "view_schema_version": 1,
  "profile": {
    "id": "dependency.architecture",
    "version": 1
  },
  "source": {
    "graph_schema_version": 1,
    "parser_semantics_version": 7,
    "graph_fingerprint": "..."
  },
  "completeness": {
    "kind": "query_lossless",
    "preserves": ["exact_file_import_topology"],
    "omits": ["calls", "callable_complexity"]
  },
  "payload": {},
  "view_fingerprint": "..."
}
```

Metrics View дополнительно содержит:

```json
{
  "source": {
    "metrics_schema_version": 1,
    "metrics_semantics_version": 4,
    "graph_fingerprint": "..."
  }
}
```

`source.graph_fingerprint` описывает полный граф. `view_fingerprint` описывает
конкретное сокращённое содержимое.

## 5. Общие инварианты

Перед проецированием необходимо полностью проверить canonical DTO. Projector:

- не разрешает имена повторно;
- не создаёт новые semantic relations;
- не превращает non-exact fact в exact edge;
- не мутирует исходный DTO;
- канонически сортирует результат;
- даёт одинаковый view для одинакового source/profile version;
- сохраняет canonical IDs, если объект не агрегирован;
- указывает все исключённые классы данных.

Для подграфа сохраняется referential closure:

```text
edge(source_id, target_id) -> оба node присутствуют
parent_id -> parent node присутствует
candidate_id -> candidate node присутствует
```

Если relation агрегируется, используются новые aggregate IDs, а не canonical
IDs с изменённым смыслом.

## 6. Предлагаемые Graph profiles

### 6.1. `canonical.full`

Назначение: архивирование, Metrics, аудит и повторные projections.

Содержимое: полный текущий Graph DTO без фильтрации.

Гарантия: единственный globally lossless Graph profile. Он остаётся обычным
Graph DTO v1, а не Graph View DTO.

### 6.2. `inventory.minimal`

Назначение: быстрый каталог проекта и оценка доступного содержимого.

Содержит:

- descriptors корневых файлов/modules: ID, kind, qualified_name, path;
- counts nodes по kind;
- synthetic method count;
- counts diagnostics по kind/status;
- counts import/type/call references по resolution status;
- source/profile metadata.

Не содержит declaration nodes, edges, locations, callsites и complexity facts.

Это inventory summary, а не «минимальный Graph DTO». По нему нельзя делать
выводы о связанности, сложности или отсутствии зависимостей.

### 6.3. `structure.declarations`

Назначение: дерево файлов и объявлений.

Узлы: все canonical nodes со следующими полями:

- `id`, `kind`, `qualified_name`, `parent_id`, `path`;
- `class_kind` для classes;
- `synthetic` для synthetic methods.

Рёбра: только `contains`.

Исключаются complexity facts, imports, calls, type relations, occurrences и
подробные diagnostics.

Гарантия: query-lossless для множества canonical declarations и ownership. Это
не signature/API view: текущий canonical DTO не содержит полных signatures.

### 6.4. `dependency.files`

Назначение: минимальная файловая dependency topology.

Содержит:

- file/module roots;
- exact `imports` edges `dependent -> dependency`;
- counts exact/external/unresolved import occurrences;
- source metadata.

Не содержит classes, declarations и occurrence-level import records.

Достаточен для file topology, SCC, fan-in/out и density. Недостаточен для
package abstractness и подробной диагностики import statements.

### 6.5. `dependency.architecture`

Назначение: подробный анализ файловых и package dependencies.

Содержит:

- file/module roots;
- class nodes с `class_kind` и ownership;
- `contains` root-to-class;
- exact `imports` edges;
- все `import_references` либо явно выбранный detailed variant;
- counts по resolution statuses.

Профиль сохраняет basis текущего dependency/architecture раздела, включая
class populations для abstractness. Package grouping остаётся тем же, что у
текущего Metrics; профиль не исправляет его ограничения.

### 6.6. `types.topology`

Назначение: inheritance и field-type relations.

Содержит:

- roots, classes и fields;
- необходимые `contains` edges;
- `inherits` и `field_type`;
- соответствующие `type_references`.

Достаточен для просмотра доказанных type relations и DIT/NOC basis. Не
достаточен для CBO, RFC, LCOM и WMC.

### 6.7. `objects.metrics_basis`

Назначение: полная основа текущих object metrics.

Содержит:

- roots, classes, fields, methods;
- functions/methods — exact targets method calls;
- ownership closure;
- `inherits`, `field_type`, `accesses_field`;
- exact `calls`/`awaits` от methods;
- type references;
- method complexity facts;
- synthetic flags.

Гарантия: query-lossless для текущих DIT/NOC/CBO/RFC/LCOM/WMC, но не является
полным project graph.

### 6.8. `calls.topology`

Назначение: компактная call topology.

Содержит:

- functions и methods;
- file/module roots с module-level calls;
- class ancestors methods;
- необходимые `contains` edges;
- exact `calls` и `awaits` с исходными positive weights;
- aggregate counts statuses и awaited/non-awaited.

Сохраняет weighted local call topology, но не individual callsites, expressions,
locations, syntactic depths и complexity facts.

Достаточен для SCC, reachability и topology centrality. Недостаточен для полной
текущей секции `call_graph`, в частности для nesting, classification и risk.

### 6.9. `calls.detailed`

Назначение: подробный call analysis без несвязанных import/type данных.

Включает `calls.topology` и:

- все callsites;
- expression, location, syntactic depth, resolution;
- target/candidate IDs и awaited;
- callable complexity facts;
- relevant owner structural facts.

Профиль сохраняет basis текущих call graph metrics и callsite-edge invariants.

### 6.10. `aggregate.packages`

Назначение: компактная карта крупного проекта.

Это quotient graph, а не canonical подграф.

Package node содержит:

- package ID и grouping policy;
- file/declaration/class counts;
- abstract class count;
- exact/external/unresolved import occurrence counts.

Package edge раздельно хранит:

- число уникальных file pairs;
- число canonical file edges;
- число exact import occurrences.

Package cycle означает цикл агрегированного quotient graph и не обязательно
file-level SCC.

### 6.11. `aggregate.overview`

Назначение: минимальный dashboard/LLM payload.

Содержит:

- size/activity totals;
- file/package graph counts;
- counts cyclic components;
- resolution status counts;
- top-k hotspots;
- source/profile metadata.

Каждый усечённый список имеет:

```json
{
  "items": [],
  "returned_count": 10,
  "total_matching": 47,
  "truncated": true
}
```

## 7. Предлагаемые Metrics profiles

Metrics profiles копируют значения из полного Metrics DTO. Они не пересчитывают
формулы из сокращённого графа и не выводят новое значение из уже округлённых
значений.

### 7.1. `metrics.full`

Полный Metrics DTO. Единственный globally lossless Metrics profile.

### 7.2. `metrics.overview`

- `size`;
- `activity`;
- scalar counts dependency/call graph;
- analyzed populations quality/object sections;
- source fingerprint.

Рядом с average/rate должен присутствовать denominator/population.

### 7.3. `metrics.architecture`

- полный `dependency_graph`;
- полный `architecture`;
- import activity counts;
- package grouping metadata.

### 7.4. `metrics.quality`

- полный `code_quality`;
- functions/methods/analyzed callable counts;
- threshold policy metadata.

### 7.5. `metrics.objects`

- полный `object_oriented`;
- relevant class/method/field populations;
- напоминание, что relations учитывают exact internal topology.

### 7.6. `metrics.calls`

- полный `call_graph`;
- call activity;
- callable populations;
- complexity fields, нужные для интерпретации `risk_top`;
- resolution coverage.

### 7.7. `metrics.aggregate`

- scalar totals;
- будущие histograms/quantiles, если они появятся в полном DTO;
- top-k с truncation metadata;
- никаких утверждений, что relative risk является вероятностью.

## 8. Совместимость Graph и Metrics profiles

| Graph profile | Естественный Metrics profile | Гарантия |
|---|---|---|
| `canonical.full` | любой | полная |
| `inventory.minimal` | `metrics.overview` | только overview/counts |
| `structure.declarations` | size subset | declaration populations |
| `dependency.files` | dependency subset | без abstractness |
| `dependency.architecture` | `metrics.architecture` | текущий architecture basis |
| `types.topology` | object subset | только typed topology/DIT/NOC basis |
| `objects.metrics_basis` | `metrics.objects` | текущий object metrics basis |
| `calls.topology` | call topology subset | без classification/nesting/risk |
| `calls.detailed` | `metrics.calls` | текущий call metrics basis |
| `aggregate.packages` | architecture aggregate | только package quotient |
| `aggregate.overview` | `metrics.aggregate` | summary only |

Эта таблица не означает, что Metrics вычисляется из указанного Graph View. Оба
view создаются из full artifacts и сопоставляются по source fingerprint.

## 9. Что нельзя называть Graph DTO v1

Сокращённый/агрегированный артефакт не должен сохранять envelope Graph DTO v1,
если удалены обязательные collections или нарушены его инварианты.

Нельзя называть Graph DTO v1 представление, где:

- отсутствуют обязательные nodes/edges/callsites/references/facts/diagnostics;
- удалены target nodes при сохранённых ссылках;
- exact callsites не соответствуют weighted call edges;
- exact import/type references не соответствуют edges;
- изменены canonical IDs;
- canonical objects агрегированы;
- скопирован `project.fingerprint` как fingerprint нового payload.

Используются отдельные названия Graph View DTO, Graph Summary DTO и Metrics View
DTO.

## 10. Версионирование

Независимые оси:

1. `graph_schema_version`;
2. `parser_semantics_version`;
3. `metrics_schema_version`;
4. `metrics_semantics_version`;
5. `view_schema_version`;
6. `profile.id`;
7. `profile.version`.

`profile.version` повышается при изменении обязательных полей, populations,
правил включения nodes, grouping, aggregation, edge meaning, synthetic/self
edge policy или top-k policy.

`view_schema_version` повышается при несовместимом изменении общего envelope.
Простая фильтрация не меняет Parser/Metrics semantics.

## 11. Допустимые сравнения

Между views одного source допустимо проверять:

- structure nodes являются subset full nodes;
- dependency edges точно соответствуют фильтрации exact imports;
- call weights совпадают с full graph;
- aggregate counts равны группировке full;
- Metrics View значения равны полному Metrics DTO.

Между версиями проекта сравнение допустимо только при совпадении:

- schema/semantics;
- profile ID/version;
- grouping policy;
- population definitions;
- aggregation и top-k policy.

Для averages, density и rates всегда показывается denominator. Рост absolute
counts может отражать рост проекта, а не ухудшение архитектуры.

## 12. Запрещённые интерпретации

Нельзя:

- считать отсутствие поля/edge в minimal view нулевым значением;
- считать reduced view полным индуцированным графом;
- сравнивать density полного и сокращённого populations;
- сравнивать PageRank разных node populations как одну шкалу;
- считать non-exact reference отсутствием runtime relation;
- трактовать package quotient cycle как file-level cycle;
- смешивать unique topology edges и occurrences;
- трактовать `risk` как вероятность дефекта;
- считать top-k полным множеством проблем;
- скрывать synthetic nodes или unresolved counts без completeness metadata.

## 13. План будущей реализации

### Этап 0. Спецификация

1. Утвердить glossary и profile IDs.
2. Для каждого profile определить whitelist полей и relations.
3. Составить матрицу canonical field -> profiles.
4. Составить матрицу metric -> required facts.
5. Запретить reduced Graph View как вход Metrics Core.

### Этап 1. Общий envelope

1. Создать отдельный package views/projections вне Parser и Metrics cores.
2. Реализовать source metadata и view fingerprint.
3. Реализовать profile registry/version checks.
4. Добавить canonical sorting и deterministic serialization.

### Этап 2. Первые безопасные Graph Views

Рекомендуемый первый набор:

1. `canonical.full`;
2. `inventory.minimal`;
3. `structure.declarations`;
4. `dependency.files`.

Профили реализуются whitelist-проекциями. Новое поле canonical DTO не должно
автоматически попадать в compact view.

### Этап 3. Domain Graph Views

1. `dependency.architecture`;
2. `calls.topology`;
3. `calls.detailed`;
4. `types.topology`;
5. `objects.metrics_basis`.

Для каждого профиля фиксируется query guarantee и контрпример того, что он не
сохраняет.

### Этап 4. Metrics Views

1. Реализовать section-level copying из полного Metrics DTO.
2. Добавить denominator/population metadata.
3. Добавить truncation metadata.
4. Проверять exact equality значений с full Metrics DTO.

### Этап 5. Aggregates

1. Формально зафиксировать package grouping policy.
2. Развести topology и occurrence weights.
3. Реализовать `aggregate.packages`.
4. Реализовать `aggregate.overview`.
5. Маркировать quotient graph machine-readable полем.

### Этап 6. Consumer integration

1. Consumer запрашивает profile ID/version.
2. Проверяет `completeness` до использования.
3. Связывает Graph/Metrics views по fingerprint.
4. При недостатке данных явно запрашивает более полный профиль.
5. Silent fallback detailed -> minimal запрещён.

## 14. Тестовые сценарии

Минимальные fixtures:

1. пустой проект;
2. один изолированный файл;
3. два файла и exact import;
4. повторные imports одной пары;
5. external и unresolved imports;
6. exact/external/ambiguous/dynamic/unresolved calls;
7. два exact callsites с weight 2;
8. обычный call и await одной пары;
9. class/method/field access;
10. inheritance chain и cycle;
11. package quotient cycle без file-level SCC;
12. synthetic constructor;
13. top-k truncation.

Property/invariant tests:

- перестановка full collections не меняет view;
- source не мутируется;
- referential closure;
- IDs существуют в source;
- exact edge sets равны фильтрации full;
- non-exact facts не создают topology;
- aggregates равны группировке full;
- Metrics View значения строго равны full Metrics;
- sibling views имеют одинаковый source fingerprint;
- содержательное изменение меняет view fingerprint.

Golden fixtures для каждого profile хранят manifest с profile versions и size
measurements. Переносимый артефакт измеряется целиком, включая его собственное
поле fingerprint; hash размера не использует fingerprint canonical payload.

## 15. Size budgets

Размер измеряется как полный object в compact UTF-8 JSON, включая fingerprint:
`json.dumps(artifact, ensure_ascii=False, sort_keys=True,
separators=(',', ':')).encode('utf-8')`. Один и тот же byte payload используется
для размера и full-artifact SHA-256. Pretty serializers и canonical payload,
из которого исключается fingerprint, для benchmark не используются. Token count
может быть benchmark, но не контрактом, поскольку зависит от tokenizer/version.

Предварительные цели для medium/large fixtures:

| Graph profile | Бюджет от canonical Graph DTO |
|---|---:|
| `structure.declarations` | <= 45% |
| `dependency.files` | <= 20% |
| `dependency.architecture` | <= 30% |
| `calls.topology` | <= 35% |
| `calls.detailed` | <= 60% |
| `aggregate.packages` | <= 15% |
| `aggregate.overview` | <= 8% |

| Metrics profile | Бюджет от full Metrics DTO |
|---|---:|
| `metrics.overview` | <= 20% |
| section profile | <= 50% |
| `metrics.aggregate` | <= 15% |

Бюджеты являются заранее заданными fixture-scoped product targets, а не
математическими гарантиями. Состав fixture и target нельзя подгонять после
измерения. На маленьких fixtures envelope может быть больше payload. Size
regression проверяется отдельно от semantic correctness.

## 16. Критерии готовности

- Parser по-прежнему создаёт только полный canonical DTO.
- Metrics рассчитывается только из полного Graph DTO.
- Reduced views не маркируются как Graph DTO v1.
- Каждый profile имеет whitelist и completeness metadata.
- Referential closure и exact/non-exact distinctions сохранены.
- Topology и occurrence multiplicity не смешиваются.
- Graph/Metrics views связаны source fingerprint.
- Values Metrics View равны values полного DTO.
- Golden fixtures и counterexamples покрывают каждый profile.
- Consumer не может молча принять minimal view за full.

## 17. Рекомендуемый начальный scope

Чтобы не создавать сразу слишком много контрактов, первая реализация должна
ограничиться следующими профилями:

1. `canonical.full` — identity и provenance baseline;
2. `inventory.minimal` — быстрый summary;
3. `structure.declarations` — структура проекта;
4. `dependency.files` — компактные зависимости;
5. `metrics.overview` — краткий набор метрик;
6. `metrics.architecture` — первый domain Metrics View.

Остальные профили добавляются после подтверждения query needs и size benefits.
