# Контракт `metrics.aggregate` v1

Этот документ до реализации фиксирует whitelist и benchmark gate профиля
`metrics.aggregate` version 1 для полного Metrics DTO schema 1 / Metrics
semantics 4. Профиль является one-way Metrics View и не меняет Metrics Core.

## Границы

Проектор принимает только валидированный полный versioned Metrics DTO и
буквально копирует разрешённые leaf values. Запрещены пересчёт, повторное
округление, сортировка, получение новых totals через `len()` и восстановление
значений из округлённых metrics.

Общий envelope, source identity, fingerprint и сериализация совпадают с
Metrics View DTO schema 1. Defaults, `latest`, negotiation и fallback
отсутствуют.

## Whitelist scalar totals

`payload.metrics` содержит ровно следующие пути:

- `size`: `directories`, `files`, `classes`, `abstract_classes`,
  `dataclasses`, `functions`, `methods`, `fields`, `constants`;
- `activity`: `calls`, `local_imports`, `external_imports`;
- `dependency_graph`: `nodes`, `edges`, `weakly_connected_components`;
- `architecture`: `package_edges`;
- `code_quality`: `analyzed_callables`, `async.functions`,
  `exceptions.raise_statements`, `exceptions.callables_raising`;
- `object_oriented`: `classes_analyzed`;
- `call_graph`: `nodes`, `edges`, `callsites_in_local_edges`,
  `external_or_builtin_callsites`, `unresolved_callsites`,
  `unresolved_or_external_callsites`.

Каждый leaf сохраняет path, значение и JSON type полного DTO. Все значения
являются неотрицательными integer counts; `bool` недопустим.

Не публикуются averages, rates, density, extrema, списки, maps, package rows,
nullable object metrics, histograms и quantiles. Число packages, cyclic
components, articulation files, bridges и recursive components не
материализовано отдельным scalar leaf и не вычисляется из коллекций.

## Population semantics

Counts не образуют одну взаимозаменяемую population:

- `size.*`, `analyzed_callables` и `classes_analyzed` — entity/population
  counts;
- `activity.*`, exception statements и callsite counts — occurrence counts;
- dependency, package и call graph edges — unique exact topology counts;
- component count относится к topology partition, а не occurrences.

Повторный import или callsite может увеличить occurrence count, не увеличив
число topology edges. `activity.calls` и сумма callsite buckets имеют разные
owner populations и не обязаны совпадать. Отсутствие exact topology не
доказывает отсутствие runtime relation.

Нормативное соответствие leaf path -> population:

| Path | Count kind | Population |
|---|---|---|
| `size.directories` | entity | unique source directories |
| `size.files` | entity | canonical file/module roots |
| `size.classes` | entity | canonical classes |
| `size.abstract_classes` | entity | canonical abstract classes |
| `size.dataclasses` | entity | canonical dataclasses |
| `size.functions` | entity | non-synthetic functions |
| `size.methods` | entity | non-synthetic methods |
| `size.fields` | entity | canonical fields |
| `size.constants` | entity | canonical constants |
| `activity.calls` | occurrence | structural call occurrences of activity owners |
| `activity.local_imports` | occurrence | project-local direct import occurrences |
| `activity.external_imports` | occurrence | non-project direct import occurrences |
| `dependency_graph.nodes` | unique_topology | dependency graph roots |
| `dependency_graph.edges` | unique_topology | exact directed non-self root pairs |
| `dependency_graph.weakly_connected_components` | topology_partition | weak components of dependency roots |
| `architecture.package_edges` | unique_topology | distinct directed cross-package pairs |
| `code_quality.analyzed_callables` | entity | functions and non-synthetic methods |
| `code_quality.async.functions` | entity | async functions in analyzed callables |
| `code_quality.exceptions.raise_statements` | occurrence | raise statement occurrences |
| `code_quality.exceptions.callables_raising` | entity | analyzed callables containing raise statements |
| `object_oriented.classes_analyzed` | entity | canonical classes |
| `call_graph.nodes` | unique_topology | call-graph owners |
| `call_graph.edges` | unique_topology | exact directed canonical call-owner pairs |
| `call_graph.callsites_in_local_edges` | occurrence | local exact callsite occurrences represented by edges |
| `call_graph.external_or_builtin_callsites` | occurrence | external/builtin callsite occurrences |
| `call_graph.unresolved_callsites` | occurrence | unresolved callsite occurrences |
| `call_graph.unresolved_or_external_callsites` | occurrence | union of external/builtin and unresolved callsite occurrences |

`population_metadata` имеет точную форму:

```json
{
  "descriptor_version": 1,
  "rounding_policy": {
    "kind": "decimal_places",
    "places": 4,
    "applies_to": "ratio_metrics"
  },
  "definitions": [
    {"id": "entity", "meaning": "counts of named entities or eligible entity subsets"},
    {"id": "occurrence", "meaning": "counts of occurrences; repeated facts count repeatedly"},
    {"id": "topology_partition", "meaning": "counts of components partitioning exact topology"},
    {"id": "unique_topology", "meaning": "counts of unique exact topology nodes or relations"}
  ],
  "metric_denominators": []
}
```

Definitions сортируются по `id`. Rounding policy сохраняет общий формат
descriptor family, но не применяется ни к одному leaf v1.

`aggregate_policy` имеет точную форму:

```json
{
  "descriptor_version": 1,
  "value_policy": "exact_recursive_whitelist_copy",
  "derived_metric_values": "forbidden",
  "top_k": {"kind": "omitted", "rankings": []}
}
```

Полный whitelist, per-path mapping и оба точных descriptor objects также
зафиксированы machine-readable в benchmark manifest. Изменение любой из этих
частей требует новой profile version.

## Инварианты

В дополнение к source contract выполняются:

```text
code_quality.analyzed_callables == size.functions + size.methods
object_oriented.classes_analyzed == size.classes
call_graph.unresolved_or_external_callsites
  == call_graph.external_or_builtin_callsites
   + call_graph.unresolved_callsites
```

Эти равенства валидируются, но не используются для построения отсутствующих
значений.

## Top-k и risk

V1 является scalar-only и не содержит rankings. Для части существующих top-k
доступен честный `total_matching` (`largest_callables`, WMC/CBO/RFC/NOC,
`heaviest_edges`, PageRank и betweenness), но populations неоднородны. Для
nullable LCOM/DIT нужен пересчёт полной class table, а для `risk_top` число
positive-risk candidates в DTO не материализовано.

Частичный набор rankings создавал бы неоднородный hotspot contract. Поэтому все
top-k исключены. Их добавление меняет whitelist, truncation и population
semantics и требует новой profile version.

`risk` нельзя называть probability, defect likelihood или percent. Текущий
score — относительная эвристика с нормализацией внутри одного source, а не
калиброванная вероятность и не межпроектная шкала.

## Completeness

`completeness.kind` — `one_way_projection`.

Профиль сохраняет:

- scalar metric totals;
- различение metric populations;
- source graph identity.

Профиль исключает:

- averages, rates и density;
- architecture details;
- call graph rankings и topology details;
- code quality details кроме counts;
- dependency details кроме counts;
- histograms и quantiles;
- object-oriented details кроме population count;
- top-k rankings.

## Benchmark gate

До runtime-реализации фиксируются неизменённые accepted fixtures
`representative_metrics_v2`, полный transferable envelope и target
`metrics.aggregate <= 15%` от полного Metrics DTO.

Размер и SHA-256 измеряются над одним compact UTF-8 JSON:

```python
json.dumps(value, ensure_ascii=False, sort_keys=True,
           separators=(",", ":")).encode("utf-8")
```

| Fixture | Full Metrics DTO | Максимум view |
|---|---:|---:|
| medium | 23 838 bytes | 3 575 bytes |
| large | 40 974 bytes | 6 146 bytes |

Нормативная проверка использует целочисленное неравенство
`view_bytes * 100 <= source_bytes * 15`. Fingerprint и metadata входят в размер.
Fixture family, serializer и target нельзя менять после измерения результата.

Gate manifest находится в
`views/testdata/metrics_aggregate_benchmark_v1.json`. До реализации он фиксирует
source hashes, populations и caps, но не содержит вымышленного artifact
measurement.

## Критерии реализации

- доступна только точная пара `metrics.aggregate` / `1`;
- каждый metric leaf строго равен full Metrics DTO по path, value и type;
- source extensions не попадают в view;
- source и result взаимно не мутируют;
- payload и descriptors имеют строгую форму;
- top-k и float metric leaves отсутствуют;
- medium и large проходят заранее зафиксированный target;
- golden manifest после реализации содержит bytes и SHA-256 полного artifact.
