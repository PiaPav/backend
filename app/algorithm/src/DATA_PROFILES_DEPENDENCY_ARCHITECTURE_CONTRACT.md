# Контракт `dependency.architecture` v1

Профиль является Graph View DTO schema 1 над валидным Graph DTO schema 1 /
Parser semantics 7. Он сохраняет detailed basis текущего dependency и package
architecture analysis, но не является Graph DTO и не принимается Metrics Core.

## Payload

Payload содержит ровно:

- `nodes` — все canonical file/module roots и classes;
- `edges` — canonical root-to-class `contains` и aggregate `imports` topology;
- `import_references` — все canonical import occurrences;
- `import_resolution_counts` — zero-filled `exact`, `external`, `unresolved`;
- `package_grouping` — versioned descriptor действующей Metrics policy.

Root descriptor содержит только `id`, `kind`, `qualified_name`, `path`. Class
descriptor дополнительно содержит `parent_id` и `class_kind`. У каждой class
ровно один canonical `contains` edge от root; class path совпадает с root path.

## Topology и occurrences

Import topology использует тот же aggregate edge contract, что
`dependency.files`: один edge на уникальную ordered exact pair, нормативный
`aggregate:imports:<sha256>` ID и положительный `exact_occurrence_count`.
Reverse и self pairs сохраняются. Canonical occurrence-level import edge IDs не
копируются, поскольку relation агрегирована.

Все `import_references` сохраняются отдельными whitelist-копиями с canonical ID,
spelling, alias, level, location, resolution и target. Поэтому повторные imports
одной пары остаются различимыми occurrences, но образуют один topology edge.
External/unresolved references входят в details и counts, но не создают edge.

Cross-invariants:

- counts точно равны распределению references по resolution;
- exact count равен сумме `exact_occurrence_count`;
- множество aggregate pairs равно множеству pairs exact references;
- count каждой pair равен числу её exact references;
- importer и exact target присутствуют как roots;
- contains endpoints, class parent и paths согласованы.

## Package policy и ограничения

Package определяется первым POSIX-сегментом root path; path без `/` относится к
`<root>`. Текущая Metrics file topology использует distinct exact non-self root
pairs, а package topology — distinct cross-package pairs. Сам view сохраняет
self import как canonical occurrence и aggregate pair; его исключение относится
к Metrics semantics, а не к фактам view.

Package nodes, package edges и metric values не вычисляются. Package quotient
cycle нельзя трактовать как file-level SCC. Import resolution counts являются
occurrence counts, а число edges — числом unique ordered pairs.

## Completeness и детерминизм

Query guarantee охватывает canonical root/class descriptors, непосредственное
class ownership, detailed import occurrences, exact import topology, resolution
counts и package grouping semantics. Calls, type relations, diagnostics,
complexity, owner structural facts и non-class declarations исключены; их
отсутствие не означает нулевое значение.

Nodes, edges и references сортируются по ID. Source не мутируется, compatible
extensions не попадают в whitelist автоматически, а fingerprint связывает весь
envelope, details и grouping descriptor. Изменение whitelist, aggregation,
self-edge или grouping policy требует новой profile version.

Fixture-scoped product target составляет не более 30% compact canonical Graph
DTO. Representative family v2 подтверждает target: medium `7910/37091`
(`21.3259%`), large `17723/91853` (`19.2949%`).
