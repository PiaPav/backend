# Контракт `types.topology` v1

Профиль создаётся только из валидного Canonical Graph DTO schema 1 / Parser
semantics 7 и возвращает Graph View DTO schema 1. Поддерживается только точная
пара `types.topology / 1`; default, `latest`, negotiation и fallback запрещены.

## Payload и population

Payload содержит ровно `nodes`, `edges` и `type_references`.

`nodes` включает все canonical classes и fields и их минимальную ownership
closure до file/module roots. Root без class не включается. Root descriptor
содержит `id`, `kind`, `qualified_name`, `path`; class и field дополнительно
содержат `parent_id`. `class_kind`, node locations и любые новые canonical поля
не копируются автоматически.

`edges` содержит необходимые canonical `contains` и все canonical `inherits` и
`field_type` с неизменными ID и endpoints. Self, reverse, multiple inheritance,
cycles и несколько canonical edge IDs для одной endpoint triple сохраняются.
Edge locations исключаются.

`type_references` сохраняет все canonical occurrences с полями `id`,
`owner_id`, `role`, `expression`, `location`, `resolution`, `target_id` и
`candidate_ids`. Collections сортируются по ID, references копируются глубоко,
а исходный Graph DTO не мутируется.

## Referential closure и resolution

Каждый `parent_id`, edge endpoint, reference owner, exact target и ambiguous
candidate присутствует в `nodes`. Class принадлежит file/module root, field —
class; `parent_id` совпадает с canonical `contains`, а path descendant совпадает
с path owning root.

Exact reference с role `base` соответствует `inherits: class -> class`, а с
role `field_type` — `field_type: field -> class`. Множество exact reference
triples точно равно множеству projected typed-edge triples. Сравнивается
topology support, а не multiplicity: occurrence multiplicity хранится полным
списком references, canonical duplicate edges не агрегируются и сохраняют ID.

Ambiguous reference имеет не менее двух sorted unique class candidates, но не
создаёт topology. External и unresolved reference не имеют target/candidates.
Location остаётся occurrence fact и не обязана иметь path владельца, поскольку
такого ограничения нет в canonical Graph DTO.

## Гарантии и ограничения

Профиль query-lossless для canonical class/field population, их ownership,
type-reference occurrences и доказанной typed topology. Все classes, включая
изолированные, и distinct `inherits` pairs сохраняют basis текущих DIT/NOC:
направление relation — child to parent, DIT использует максимальную parent
depth, NOC считает distinct children без self edge, а inheritance cycle даёт
неопределённый DIT.

Профиль не является basis полной секции object metrics. Он исключает methods,
functions, constants, calls, `accesses_field`, complexity, imports, diagnostics
и owner structural facts, поэтому не сохраняет CBO, RFC, LCOM или WMC. Например,
два canonical graphs с одинаковыми type facts, но разными method calls, обязаны
давать одинаковый view при потенциально разных object metrics.

Graph View не является Graph DTO v1 и не передаётся в Metrics Core. Golden size
benchmark не определяется: в плане для `types.topology` нет заранее заданного
budget.
