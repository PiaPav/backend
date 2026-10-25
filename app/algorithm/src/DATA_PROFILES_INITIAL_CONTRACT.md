# Контракт начальных профилей данных

Этот документ конкретизирует первый набор из `DATA_PROFILES_PLAN.md` для
Canonical Graph DTO schema 1 / Parser semantics 7. Изменение перечисленных
populations, обязательных полей или правил агрегации требует новой версии
профиля.

## Профили и виды артефактов

| Profile | Version | Artifact | Состояние |
|---|---:|---|---|
| `canonical.full` | 1 | Canonical Graph DTO | реализован |
| `inventory.minimal` | 1 | Graph Summary DTO | реализован |
| `structure.declarations` | 1 | Graph View DTO | реализован |
| `dependency.files` | 1 | Graph View DTO | реализован |
| `metrics.overview` | 1 | Metrics View DTO | реализован |
| `metrics.architecture` | 1 | Metrics View DTO | реализован |

Выбор всегда требует точных `profile.id` и `profile.version`; default,
`latest`, negotiation и fallback запрещены. Только `canonical.full` является
globally lossless и допустим как вход Metrics Core.

Точный field-level контракт начальных Metrics profiles, включая populations,
denominators и package grouping, находится в
`DATA_PROFILES_METRICS_CONTRACT.md`. Metrics Views строятся только из полного
Metrics DTO schema 1 / semantics 4 и не являются входом Metrics Core.

## `canonical.full` v1

Профиль принимает только полностью валидный Graph DTO schema 1 / Parser
semantics 7 и возвращает независимую глубокую копию без view envelope,
фильтрации, пересортировки или нового fingerprint. Все совместимые расширения
исходного DTO сохраняются. Identity означает равенство содержания, а не
тождество mutable Python-объекта.

Публичный gateway `materialize_graph_profile` поддерживает `canonical.full`,
`inventory.minimal`, `structure.declarations` и `dependency.files`. Специализированные gateway
`project_graph_summary` и `project_graph_view` принимают только профили своего
вида артефакта.

## `inventory.minimal` v1

Это one-way summary без topology, declarations, locations, callsites и
complexity facts. Root descriptor содержит только `id`, `kind`,
`qualified_name` и `path`; неоднозначное производное поле `name` не создаётся.

Summary envelope содержит `artifact_kind: graph_summary`,
`summary_schema_version: 1`, точные profile/source metadata, `completeness`,
`payload` и `summary_fingerprint`. Fingerprint является lowercase SHA-256
compact canonical UTF-8 JSON всего envelope без самого fingerprint; roots
канонизируются по ID, а diagnostic rows — по `(kind, status)`.

Нормативный payload:

```json
{
  "roots": [],
  "node_counts": {
    "class": 0,
    "constant": 0,
    "field": 0,
    "file": 0,
    "function": 0,
    "method": 0,
    "module": 0
  },
  "synthetic_method_count": 0,
  "diagnostics": {"total": 0, "by_kind_status": []},
  "reference_resolution_counts": {
    "imports": {"exact": 0, "external": 0, "unresolved": 0},
    "types": {"ambiguous": 0, "exact": 0, "external": 0, "unresolved": 0},
    "callsites": {
      "ambiguous": 0,
      "dynamic": 0,
      "exact": 0,
      "external": 0,
      "unresolved": 0
    }
  }
}
```

`roots` — точная проекция всех `file`/`module` nodes, отсортированная по ID.
Все закрытые node/status categories обязательны, включая нулевые. Каждый count
является неотрицательным integer, но не boolean. Инварианты:

- сумма `node_counts` равна числу canonical nodes;
- число roots равно `node_counts.file + node_counts.module`;
- synthetic methods входят в `node_counts.method`, а их отдельный count не
  превышает method count;
- суммы import/type/callsite status buckets равны длинам соответствующих
  occurrence-level collections;
- exact callsite count равен сумме weights canonical `calls`/`awaits` edges.

Reference counters считают occurrences: `import_references`,
`type_references` и `callsites`. Они не считают уникальные endpoint pairs или
topology edges. Domain-specific status sets нельзя объединять.

Diagnostics представлены совместным распределением `(kind, status)`:

```json
{"kind": "shadowed_module", "status": "warning", "count": 2}
```

Строки уникальны, имеют положительный count, сортируются по `(kind, status)`, а
их сумма равна `total` и длине `diagnostics`. Поскольку общий Graph DTO
validator пока не требует diagnostic `kind`/`status`, projector v1 обязан
отклонять source diagnostic без непустых строк в обоих полях. Неявная категория
`unknown` запрещена.

## `structure.declarations` v1

Нормативный whitelist и query guarantee определены в `views/CONTRACT.md`.
Профиль сохраняет все canonical nodes, canonical ownership и только `contains`
relations.

## `dependency.files` v1

Профиль содержит descriptors всех `file`/`module` roots и уникальную exact
import topology в направлении `dependent -> dependency`. Один derived edge
соответствует одной уникальной паре `(source_id, target_id)` и содержит
`exact_occurrence_count`. Его ID равен `aggregate:imports:<digest>`, где
`digest` — lowercase SHA-256 compact JSON-массива `[source_id, target_id]` в
UTF-8 с `ensure_ascii=false`. Он не совпадает с ID отдельного canonical import
occurrence.

Глобальные `import_resolution_counts` содержат обязательные `exact`, `external`
и `unresolved` buckets. Для каждого результата выполняется:

```text
sum(edge.exact_occurrence_count) == import_resolution_counts.exact
len(edges) <= import_resolution_counts.exact
```

Non-exact references не создают topology. Профиль не сохраняет occurrence IDs,
locations, aliases и source spelling.

Payload имеет строго форму `nodes`, `edges`, `import_resolution_counts`.
Root nodes имеют ровно `id`, `kind`, `qualified_name`, `path`; edges — ровно
`id`, `kind`, `source_id`, `target_id`, `exact_occurrence_count`. Ordered endpoint
pairs уникальны, self-loop допустим, а reverse pair является отдельной
зависимостью. Все nodes/edges сортируются по ID. Гарантированный запрос:
точные зависимости между canonical roots с числом exact occurrences и полное
распределение всех import occurrences по трём resolution buckets. Например,
по view нельзя восстановить строку `from x import y as z` или её location:
две такие записи для одной пары представлены одним edge с count `2`.

## Матрица canonical data

| Canonical data | canonical.full | inventory.minimal | structure.declarations | dependency.files |
|---|---|---|---|---|
| schema/semantics, source fingerprint | как есть | metadata | metadata | metadata |
| root descriptors | полностью | descriptors/counts | whitelist nodes | descriptors |
| declaration nodes | полностью | counts | whitelist nodes | исключены |
| `class_kind` | полностью | только общий node count | classes | исключён |
| `synthetic` | полностью | method count | только `true` methods | исключён |
| locations/complexity facts | полностью | исключены | исключены | исключены |
| `contains` | полностью | исключены | canonical edges | исключены |
| `imports` | полностью | occurrence counts | исключены | unique derived pairs |
| остальные edges | полностью | исключены | исключены | исключены |
| callsites/type/import references | полностью | resolution counts | исключены | import aggregates |
| owner structural facts | полностью | исключены | исключены | исключены |
| diagnostics | полностью | joint counts | исключены | исключены |

Derived dependency edges не являются canonical edge objects.

## Матрица Metrics facts

| Metrics section | Необходимые canonical facts |
|---|---|
| `size` | node kinds, `class_kind`, synthetic policy |
| `activity` | ownership, node populations, `owner_structural_facts` |
| `dependency_graph` | roots и exact `imports` topology |
| `architecture` | roots/path grouping, classes/`class_kind`, ownership, exact imports |
| `code_quality` | non-synthetic callables и `complexity_facts` |
| `object_oriented` | ownership, typed/field/call relations, complexity |
| `call_graph` | call owners/targets, callsites, weighted calls/awaits, complexity |

Матрица описывает basis, но не разрешает вычислять текущий Metrics DTO из
reduced profile. Metrics Core принимает только полный canonical graph.
