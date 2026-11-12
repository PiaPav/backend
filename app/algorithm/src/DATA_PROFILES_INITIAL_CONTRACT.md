# Реестр профилей данных

Все profiles работают с Graph DTO schema 1 / Parser semantics 7 либо Metrics
DTO schema 1 / Metrics semantics 4. Выбор требует точных `id` и `version`;
default, `latest`, negotiation и silent fallback запрещены.

| Profile | Version | Artifact | Назначение |
|---|---:|---|---|
| `canonical.full` | 1 | Graph DTO | Полный globally-lossless граф |
| `inventory.minimal` | 1 | Graph Summary | Roots и population/status counts |
| `structure.declarations` | 1 | Graph View | Объявления и ownership |
| `dependency.files` | 1 | Graph View | Exact file dependencies |
| `dependency.architecture` | 1 | Graph View | Imports, classes и package basis |
| `calls.topology` | 1 | Graph View | Weighted exact call topology |
| `calls.detailed` | 1 | Graph View | Callsites и call metric basis |
| `types.topology` | 1 | Graph View | Inheritance и field types |
| `objects.metrics_basis` | 1 | Graph View | Basis object metrics |
| `aggregate.packages` | 2 | Graph Summary | Package quotient compact wire |
| `aggregate.overview` | 1 | Graph Summary | Compact graph dashboard |
| `metrics.full` | 1 | Metrics DTO | Полный globally-lossless результат |
| `metrics.overview` | 1 | Metrics View | Общие counts/rates |
| `metrics.architecture` | 1 | Metrics View | Dependency/architecture sections |
| `metrics.quality` | 1 | Metrics View | Code quality section |
| `metrics.objects` | 1 | Metrics View | Object-oriented section |
| `metrics.aggregate` | 1 | Metrics View | Scalar-only totals |

`metrics.calls` не зарегистрирован: draft не прошёл неизменяемый size target.

## Общие правила

- Canonical DTO полностью валидируется до projection.
- Reduced artifact не маркируется как полный DTO и не принимается Metrics Core.
- Whitelist явный: новые source-поля не попадают в view автоматически.
- Source не мутируется; output сортируется и fingerprint детерминирован.
- Неагрегированные объекты сохраняют canonical IDs и referential closure.
- Non-exact references не создают topology.
- Occurrence counts и unique topology не смешиваются.
- Graph/Metrics sibling views связываются по source graph fingerprint.

`inventory.minimal` публикует root descriptors, node/synthetic/diagnostic counts
и zero-filled import/type/call resolution counts. `structure.declarations`
сохраняет declaration nodes и `contains`. `dependency.files` агрегирует exact
imports по ordered root pair с `exact_occurrence_count`; external/unresolved
imports остаются только в counters.

Точные domain whitelists и ограничения приведены в соседних contract-файлах.
