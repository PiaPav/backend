# Контракт `calls.detailed` v1

Профиль создаётся только из валидного Canonical Graph DTO schema 1 / Parser
semantics 7 и возвращает Graph View DTO schema 1. Поддерживается только точная
пара `calls.detailed / 1`; default, `latest`, negotiation и fallback запрещены.

## Payload

Payload содержит ровно:

```text
nodes
edges
callsites
module_call_owner_ids
owner_structural_facts
```

`nodes` включает все file/module roots для сохранения collision-safe label
namespace текущего Metrics, все functions/methods и классы-владельцы methods.
Roots содержат `id`, `kind`, `qualified_name`, `path`; descendants также
содержат `parent_id`. Synthetic methods маркируются только `synthetic: true` и
не имеют complexity facts. Каждый non-synthetic callable содержит полные raw
canonical `complexity_facts`. Node locations и `class_kind` исключаются.

`edges` содержит необходимые canonical `contains` и все canonical `calls` и
`awaits` с исходными IDs и positive weights. Calls и awaits одной пары не
объединяются; self и reverse edges сохраняются.

`callsites` сохраняет каждую canonical occurrence с полями `id`, `caller_id`,
`expression`, `location`, `syntactic_depth`, `resolution`, `target_id`,
`candidate_ids`, `awaited`. Callsite location остаётся canonical fact и не
обязана иметь тот же path, что caller. Exact callsites должны точно
соответствовать weighted call/await edges по тройке caller, target и kind.
Ambiguous candidates сохраняются, но не становятся topology edges.

`module_call_owner_ids` содержит все и только file/module callers сохранённых
callsites. `owner_structural_facts` содержит `{owner_id, call_occurrences}` для
всех roots и non-synthetic callables. Import counters исключаются, а structural
`call_occurrences` не приравниваются к числу canonical callsites.

## Гарантии и ограничения

Профиль query-lossless для текущего basis Metrics `call_graph`: weighted exact
topology, occurrence classifications и nesting, callable complexity, synthetic
policy, ownership, module callers и глобальный root label context. Это не делает
Graph View допустимым входом Metrics Core: production Metrics по-прежнему
вычисляется только из полного Graph DTO.

`calls.detailed` семантически включает `calls.topology`, но не вкладывает его
payload буквально. Topology counters однозначно выводятся из полных callsites;
common canonical nodes/edges и module owners сохраняют тот же смысл.

Профиль исключает imports, types, field access, fields/constants, diagnostics,
node/edge locations и root import activity. Поэтому он не является globally
lossless и не подходит как basis dependency/object metrics. Например,
structural `call_occurrences: 5` не доказывает наличие пяти canonical callsites,
а ambiguous candidate не доказывает runtime relation.
