# Контракт начальных Metrics profiles

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

## Population metadata

Оба профиля содержат `population_metadata` descriptor version 1. Он определяет
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
- Graph DTO, Graph View, Graph Summary и raw `calculate_graph_metrics()` result
  не являются допустимым source.
