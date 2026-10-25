# Контракт `calls.topology` v1

Профиль строится только из валидного Canonical Graph DTO schema 1 / Parser
semantics 7 и возвращает Graph View DTO schema 1. Точная пара выбора —
`calls.topology / 1`; default, `latest`, negotiation и fallback запрещены.

## Payload и populations

Payload содержит ровно `nodes`, `edges`, `module_call_owner_ids` и
`callsite_counts`.

В `nodes` входят все canonical functions и methods, включая synthetic methods,
а также минимальная ownership closure: классы методов и корни функций/классов.
Дополнительно включаются file/module roots, являющиеся caller хотя бы одного
canonical callsite. `module_call_owner_ids` содержит все и только такие roots,
отсортированные по ID; поэтому closure-only roots не считаются вершинами call
topology. Все functions/methods являются topology vertices, classes служат
только ownership context.

Root descriptor содержит `id`, `kind`, `qualified_name`, `path`; class и
function дополнительно содержат `parent_id`; method имеет те же поля и только
для synthetic method — `synthetic: true`. `class_kind` и locations исключены.

`edges` содержит необходимые canonical `contains` и все canonical `calls` и
`awaits`. Их IDs не меняются. Call edges сохраняют исходный положительный
integer `weight`; повторная агрегация не выполняется. `calls` и `awaits` одной
пары остаются разными relations, self и reverse edges сохраняются.

## Occurrence counters

`callsite_counts` — обязательная zero-filled совместная матрица для `exact`,
`ambiguous`, `external`, `dynamic`, `unresolved`; каждая строка содержит ровно
`awaited` и `non_awaited`. Значения считают callsite occurrences, а не topology
edges. Выполняются инварианты:

```text
sum(weight for awaits edges) == callsite_counts.exact.awaited
sum(weight for calls edges) == callsite_counts.exact.non_awaited
```

Non-exact callsites не создают topology, включая ambiguous candidates.

## Гарантия и ограничения

Профиль query-lossless для canonical callable population и ownership, exact
weighted call topology, synthetic identity, module-level caller population и
глобального распределения resolution × awaited. Он достаточен для SCC,
reachability и topology centrality при явно выбранной callable/root population.

Individual callsite IDs, expressions, locations, syntactic depth, candidate
IDs, callable complexity, structural facts, imports, types и field access не
сохраняются. Например, два ordinary exact callsites одной пары представлены
одним `calls` edge с `weight: 2`; по view нельзя восстановить их expressions или
locations. Наличие ambiguous count также не доказывает relation ни к одному
candidate. Поэтому профиль не является basis полной текущей Metrics-секции
`call_graph` и отклоняется Metrics Core.

Standalone validator проверяет необходимый population invariant: каждый module
owner без исходящего exact root edge требует отдельного occurrence в суммарных
non-exact buckets. Доказать соответствие каждого root конкретному callsite без
сохранения occurrence records невозможно; точное правило all-and-only
обеспечивается projector из валидного canonical source.
