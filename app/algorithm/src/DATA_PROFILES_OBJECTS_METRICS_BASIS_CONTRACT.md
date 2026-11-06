# Контракт `objects.metrics_basis/1`

Graph View schema 1 фиксирует basis `object_oriented` Metrics semantics 4 для
Graph DTO schema 1 / Parser semantics 7, но не передаётся в Metrics Core.

Payload содержит `nodes`, `edges`, `type_references`. Nodes включают все
classes/fields/methods, ownership roots и standalone functions, являющиеся exact
targets реальных methods. Non-synthetic methods сохраняют complexity; synthetic
methods маркируются явно.

Edges: необходимый `contains`, все `inherits`/`field_type`, `accesses_field` и
exact `calls`/`awaits` от non-synthetic class methods. Call weight сохраняется
как provenance, но CBO/RFC используют distinct unweighted adjacency. Non-exact
type references не создают topology.

| Metric | Необходимые facts |
|---|---|
| DIT/NOC | Все classes и inheritance topology |
| CBO | Parents, field types и owning classes exact targets |
| RFC | Real methods и distinct exact callable targets |
| LCOM | Real methods, fields и same-class field access |
| WMC | Complexity всех non-synthetic methods |

Synthetic method не входит в declared-method/WMC/LCOM population, но может быть
exact target. Standalone function target влияет на RFC, но не CBO. LCOM равен
`null` при менее чем двух real methods или отсутствии fields; inheritance cycle
даёт `DIT: null`.

Профиль query-lossless для текущих DIT/NOC/CBO/RFC/LCOM/WMC. Callsites,
imports, diagnostics, module/function calls и прочие facts исключены;
нормативного size budget нет.
