# Контракт `objects.metrics_basis` v1

Профиль создаётся только из валидного Canonical Graph DTO schema 1 / Parser
semantics 7 и возвращает Graph View DTO schema 1. Поддерживается только точная
пара `objects.metrics_basis / 1`; default, `latest`, negotiation и fallback
запрещены. Профиль фиксирует basis секции `object_oriented` Metrics semantics 4,
но не является допустимым входом Metrics Core.

## Payload и population

Payload содержит ровно `nodes`, `edges` и `type_references`.

`nodes` включает все canonical classes, fields и methods, включая synthetic
methods. Дополнительно включаются только standalone functions, являющиеся exact
targets `calls`/`awaits` от non-synthetic class methods, и минимальная ownership
closure до file/module roots.

Root descriptor содержит `id`, `kind`, `qualified_name`, `path`; declaration —
также `parent_id`. Synthetic method содержит только `synthetic: true`, а каждый
non-synthetic method — полную глубокую копию canonical `complexity_facts`.
Target-only function complexity не включается. `class_kind`, node locations и
новые canonical поля не копируются автоматически.

`edges` содержит:

- необходимые canonical `contains` между выбранными nodes;
- все canonical `inherits` и `field_type`;
- canonical `accesses_field` только от non-synthetic class methods;
- exact canonical `calls`/`awaits` только от non-synthetic class methods.

Call edge сохраняет положительный canonical `weight`; остальные edges содержат
только `id`, `kind`, `source_id`, `target_id`. Weight является provenance
metadata: CBO и RFC используют distinct unweighted target adjacency. Self,
reverse, multiple inheritance, cycles и разные relation kinds не
нормализуются.

`type_references` сохраняет все canonical occurrences с полями `id`,
`owner_id`, `role`, `expression`, `location`, `resolution`, `target_id` и
`candidate_ids`. Non-exact references сохраняются как provenance, но не создают
topology и не влияют на object metrics. Все collections сортируются по ID,
вложенные данные копируются глубоко, source не мутируется.

## Матрица metric -> required facts

| Metric/output | Обязательные facts |
|---|---|
| class labels, sorting, top-10 | все class IDs и `qualified_name`; duplicate labels получают suffix `[id]` |
| DIT | все classes и distinct `inherits: child -> parent`; multiple inheritance использует maximum depth, cycle даёт `null` |
| NOC | все classes и distinct direct inheritance pairs; self edge не считается child |
| CBO | parents, exact field types и owning classes exact callable targets real methods; self class удаляется |
| RFC | все declared non-synthetic methods и distinct exact callable targets этих методов |
| LCOM | полные field/real-method populations и distinct same-class `accesses_field` |
| WMC | полные `complexity_facts` всех non-synthetic methods; synthetic methods исключаются |

Calls/awaits одной endpoint pair, repeated occurrences и weights не увеличивают
CBO/RFC повторно. Standalone function target увеличивает RFC, но не CBO.
Synthetic method исключается как declared method, caller, LCOM participant и WMC
term, однако exact call на synthetic target участвует в RFC и может дать CBO по
его class owner. LCOM равен `null`, если real methods меньше двух или class не
объявляет fields.

## Closure и validation

Каждый `parent_id`, edge endpoint, reference owner/target/candidate присутствует
в `nodes`. `parent_id` точно соответствует единственному projected `contains`;
ownership образует ацикличный forest до file/module root, а path descendant
совпадает с path root. Каждый включённый root владеет class либо target-only
function; functions присутствуют тогда и только тогда, когда являются targets
сохранённых method calls.

Endpoint kinds фиксированы контрактом. `accesses_field` связывает real method и
field одного class. Call source — только real method, target — function/method;
ordered triple `(kind, source_id, target_id)` уникален, weight — positive
non-boolean integer. Exact type-reference support точно совпадает с множеством
`inherits`/`field_type` triples; occurrence multiplicity остаётся в references.
Node, edge и reference ID уникальны в общем namespace.

## Гарантии и контрпримеры

Профиль query-lossless для текущих DIT/NOC/CBO/RFC/LCOM/WMC и полного
`object_oriented` output Metrics semantics 4. Изменение formulas, population,
synthetic policy или required facts требует новой версии профиля.

Профиль не сохраняет callsites, non-metric calls/accesses, imports, diagnostics,
owner structural facts, unrelated declarations и locations вне retained
complexity/type-reference facts. Поэтому graphs с одинаковым payload, но разными
dynamic/unresolved calls, import occurrences или module/function calls могут
различаться вне object metrics. Weight и type-reference occurrence multiplicity
сохраняются как provenance, но сами по себе не изменяют object metric values.

Graph View не является Graph DTO v1 и отклоняется Metrics Core. Проверочная
реконструкция метрик из basis допустима только как test oracle. Отдельный golden
size benchmark не определяется: в плане для профиля нет заранее заданного
budget.
