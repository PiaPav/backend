# Контракт Metrics profiles v1

Profiles принимают только полный Metrics DTO schema 1 / Metrics semantics 4.
`metrics.full/1` возвращает глубокую identity-копию и является единственным
globally-lossless Metrics profile. Reduced views копируют explicit whitelist без
пересчёта, повторного округления и silent fallback.

Metrics View envelope содержит `artifact_kind: metrics_view`, schema/profile и
source metadata, `completeness`, `payload`, `population_metadata` и
`view_fingerprint`. Fingerprint — SHA-256 canonical compact JSON без собственного
поля. Каждый metric leaf равен full DTO по path, value и JSON type.

## Профили

### `metrics.overview/1`

Копирует полные `size` и `activity`, основные scalar dependency/call counts и
rates, а также analyzed populations quality/object sections. Это one-way
projection без подробных topology/rankings.

### `metrics.architecture/1`

Копирует import activity, полные `dependency_graph` и `architecture` плюс
package grouping policy. Import activity считает occurrences, edges — unique
exact non-self pairs. Package — первый POSIX-сегмент path либо `<root>`.

### `metrics.quality/1`

Копирует function/method populations и полный `code_quality`. Thresholds:
cyclomatic `>=10` или cognitive `>=15`; nesting `>=4`. `largest_callables` —
fixed top-10 по lines descending, затем node ascending. Sidecar truncation
публикует limit, returned/total и `truncated`.

### `metrics.objects/1`

Копирует class/method/field populations и полный `object_oriented`. Шесть
rankings имеют fixed top-10 и deterministic tie policy. Object relations —
unique exact internal adjacency; call weights не увеличивают CBO/RFC. LCOM
nullable при недостаточной population, DIT nullable при inheritance cycle.

### `metrics.aggregate/1`

Scalar-only one-way projection из 27 integer totals. Averages, rates, density,
derived totals, maps и rankings исключены. Подробный whitelist находится в
`DATA_PROFILES_METRICS_AGGREGATE_CONTRACT.md`.

`metrics.calls` не зарегистрирован: обязательный subtree полного `call_graph`
не позволил пройти section target `<=50%`.

## Population semantics

- callables: functions и non-synthetic methods;
- dependency density denominator: ordered distinct roots `n*(n-1)`;
- callsite rate denominator: local + external + unresolved occurrences;
- package instability: unique afferent + efferent neighbours;
- ratio values уже округлены Metrics Core до четырёх знаков;
- denominator `activity.average_calls_per_call_owner` не материализован и не
  восстанавливается из округлённого average.

Изменение whitelist, population, denominator, grouping, top-k или tie policy
требует новой profile version. Graph DTO/View/Summary и raw calculator result не
являются допустимым source Metrics View.
