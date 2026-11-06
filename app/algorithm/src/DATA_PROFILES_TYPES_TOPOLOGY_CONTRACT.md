# Контракт `types.topology/1`

Payload Graph View schema 1 содержит `nodes`, `edges`, `type_references` для
Graph DTO schema 1 / Parser semantics 7.

Nodes включают все classes/fields и ownership closure до roots. Edges содержат
необходимый `contains`, canonical `inherits` и `field_type`; IDs и endpoints не
меняются. References сохраняют owner, role, expression, location, resolution,
target и candidates.

Все ссылки имеют referential closure. Exact `base` references соответствуют
`inherits`, exact `field_type` — одноимённым edges. Ambiguous references имеют
кандидатов, но не создают topology; external/unresolved не имеют target.

Профиль query-lossless для class/field population, ownership, type occurrences
и доказанной topology, включая DIT/NOC basis. Methods, calls, field access,
complexity, imports и diagnostics исключены, поэтому CBO/RFC/LCOM/WMC не
сохраняются. View не является входом Metrics Core; нормативного size budget нет.
