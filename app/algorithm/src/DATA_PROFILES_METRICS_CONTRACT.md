# Контракт Metrics profiles v1

Этот документ фиксирует Metrics View DTO schema 1 для полного Metrics DTO
schema 1 / Metrics semantics 4. Projector принимает только versioned full
Metrics DTO и копирует значения по явному whitelist без пересчёта, повторного
округления и сортировки.

## Envelope

Metrics View содержит ровно поля `artifact_kind: "metrics_view"`,
`view_schema_version: 1`, точные profile/source metadata, `completeness`,
`payload` и `view_fingerprint`. Fingerprint — lowercase SHA-256 compact
canonical UTF-8 JSON всего envelope без самого fingerprint. Serializer выдаёт
детерминированный pretty JSON с сортировкой object keys и завершающим LF.
Defaults, `latest`, negotiation и fallback отсутствуют.

## `metrics.overview` v1

Whitelist `payload.metrics`:

- полный текущий `size`;
- полный текущий `activity`;
- `dependency_graph`: `nodes`, `edges`, `density`, `average_fan_in`,
  `average_fan_out`, `weakly_connected_components`;
- `code_quality.analyzed_callables`;
- `object_oriented.classes_analyzed`;
- `call_graph`: `nodes`, `edges`, `callsites_in_local_edges`,
  `external_or_builtin_callsites`, `unresolved_callsites`,
  `unresolved_or_external_callsites`, `local_resolution_rate`,
  `classified_callsite_rate`, `maximum_call_chain_depth`,
  `maximum_syntactic_call_nesting`.

Профиль является one-way projection. Списки topology/rankings, подробные
quality/object metrics и architecture не сохраняются.

## `metrics.architecture` v1

Whitelist `payload.metrics`:

- `activity.local_imports` и `activity.external_imports`;
- все поля текущего `dependency_graph`;
- все поля текущего `architecture`, включая полные package rows.

Это query-lossless представление текущих dependency/architecture metrics, но
не canonical basis для их повторного вычисления. Import activity считает
occurrences, тогда как dependency edges являются уникальными exact non-self
topology pairs.

`package_grouping` фиксирует действующую policy: package определяется первым
POSIX-сегментом root path, path без `/` относится к `<root>`; file topology
использует distinct exact non-self pairs, package topology — distinct
cross-package pairs. Это не Python package discovery.

## `metrics.quality` v1

Whitelist `payload.metrics`:

- `size.functions` и `size.methods`;
- полный текущий `code_quality` без пересчёта, повторного округления или
  изменения порядка строк.

Профиль является query-lossless для текущей quality-секции полного Metrics DTO.
`code_quality.analyzed_callables` равен сумме `size.functions + size.methods`:
обе populations включают functions и несинтетические methods.

`threshold_policy` descriptor version 1 фиксирует действующие правила Metrics
semantics 4:

- `high_complexity_callables`: cyclomatic `>= 10` **или** cognitive `>= 15`;
- `deeply_nested_callables`: nesting `>= 4`;
- `largest_callables`: не более 10 строк в порядке lines descending, затем node
  ascending; ties не расширяют результат сверх limit.

Threshold-filtered списки не являются усечёнными. Единственный усечённый список
профиля — `metrics.code_quality.largest_callables`.

## Truncation metadata

`metrics.quality` содержит sidecar `truncation_metadata` descriptor version 1,
не изменяя форму скопированной quality-секции. Descriptor для
`metrics.code_quality.largest_callables` содержит:

- `limit: 10`;
- `returned_count` — число возвращённых строк;
- `total_matching` — число кандидатов после фильтрации и до limit; для этого
  ranking фильтр тождественно истинный, поэтому значение равно
  `code_quality.analyzed_callables`;
- `truncated` — `total_matching > returned_count`;
- детерминированный порядок `lines descending`, `node ascending`.

Значение `total_matching` не означает число строк, равных граничной строке
ranking. Изменение limit, порядка, tie policy или смысла population требует
новой версии profile.

## `metrics.objects` v1

Whitelist `payload.metrics`:

- `size.classes`, `size.methods` и `size.fields`;
- полный текущий `object_oriented`, включая полную таблицу `classes` и все
  шесть rankings.

Профиль является query-lossless для текущей object-oriented секции полного
Metrics DTO. Значения, типы и порядок строк копируются без пересчёта,
повторного округления или сортировки. `classes_analyzed`, `size.classes` и
длина `classes` обязаны совпадать.

Object-specific population metadata различает canonical classes,
не синтетические directly owned methods, directly owned fields и exact
canonical callable targets. Полная population callable targets в Metrics DTO
не материализована и не восстанавливается из опубликованных counts.

`topology_policy` фиксирует basis Metrics semantics 4: object metrics используют
уникальную exact internal canonical adjacency; `calls` и `awaits` образуют
unweighted adjacency, поэтому веса и повторные occurrences не увеличивают CBO
или RFC. Ownership является непосредственным. Synthetic methods исключены как
declared methods и callers, но exact synthetic target может учитываться;
standalone function target может учитываться в RFC. Отсутствие exact relation
не доказывает отсутствие runtime relation.

LCOM имеет denominator из неупорядоченных пар directly declared
non-synthetic methods. При менее чем двух таких methods либо при отсутствии
directly declared fields результат равен `null`, а не `0.0`. `dit: null`
означает цикл во внутренней exact inheritance topology. Поле `class` является
display label, а не canonical ID.

Каждый из шести rankings имеет limit 10, fixed-size tie policy и порядок
`metric descending`, затем `class ascending`. Rankings являются точными
полнострочными срезами таблицы `classes`. `total_matching` равен
`classes_analyzed` для WMC/CBO/RFC/NOC и числу non-null строк для LCOM/DIT;
`lowest_cohesion` сортируется по LCOM descending.

## Population metadata

Все профили содержат `population_metadata` descriptor version 1. Он определяет
populations, rounding policy и denominator binding для каждого опубликованного
average/rate/density. Descriptor не является новым результатом Metrics и не
содержит пересчитанных denominator values.

Основные правила:

- callables — functions и несинтетические methods;
- activity call owners — несинтетические functions/methods плюс roots, у
  которых structural `call_occurrences` больше нуля;
- call-graph owners — все function/method nodes, включая synthetic methods,
  плюс roots с callsite или исходящим canonical call edge;
- callsite population состоит только из occurrences владельцев из
  call-graph-owner population;
- file population — canonical file/module roots;
- density denominator — ordered distinct root pairs `n * (n - 1)`;
- callsite rate denominator — local + external + unresolved occurrences;
- package abstractness denominator — непосредственно принадлежащие root classes;
- package instability denominator — сумма уникальных afferent/efferent package
  neighbours;
- при нулевом denominator Metrics semantics 4 публикует `0.0`;
- ratio values округлены Metrics Core до четырёх знаков и не являются точными
  рациональными значениями.

Численный denominator гибридной метрики
`activity.average_calls_per_call_owner` в полном Metrics DTO не материализован;
он относится к activity-call-owner population, а descriptor явно указывает
`not_materialized`. Его нельзя подменять call-graph-owner population или
восстанавливать из округлённого значения.

Для `metrics.quality` descriptor содержит только callable population и bindings
трёх averages к `code_quality.analyzed_callables`; при пустой population полный
Metrics DTO публикует `0.0`. Для `metrics.objects` descriptor содержит только
object-specific populations и отдельную nullable LCOM semantics.

## Инварианты

- каждый metric leaf равен одноимённому leaf полного Metrics DTO, включая тип;
- source и result не мутируют друг друга;
- совместимые source extensions не попадают в profile автоматически;
- неканонический порядок source collections отклоняется, а не исправляется;
- source schema 1 / semantics 4 обязан содержать все известные поля и корректные
  shapes/types семи Metrics sections; неизвестные extensions разрешены;
- dependency/package SCC содержат минимум два уникальных непустых строковых ID,
  канонически сортируются внутри и снаружи и не дублируются; recursive call SCC
  содержит минимум один ID и допускает singleton для self-recursion;
- bridge содержит две различные непустые строки, а endpoints и общий список
  bridges уникальны и канонически отсортированы;
- изменение population, grouping, whitelist или denominator policy требует
  новой profile version;
- для quality выполняются `analyzed_callables = size.functions + size.methods`
  и `len(largest_callables) = min(analyzed_callables, 10)`;
- для objects выполняются
  `classes_analyzed = size.classes = len(classes)`, а каждый ranking равен
  нормативному top-10 срезу полной таблицы classes;
- строки quality rankings имеют канонический порядок, положительные `lines` и
  cyclomatic complexity, а threshold rows удовлетворяют опубликованным
  включительным границам;
- Graph DTO, Graph View, Graph Summary и raw `calculate_graph_metrics()` result
  не являются допустимым source.
