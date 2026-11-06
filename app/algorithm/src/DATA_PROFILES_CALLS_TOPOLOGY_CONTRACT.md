# Контракт `calls.topology/1`

Graph View schema 1 строится из валидного Graph DTO schema 1 / Parser semantics
7. Payload содержит `nodes`, `edges`, `module_call_owner_ids` и
`callsite_counts`.

Nodes включают все functions/methods, классы-владельцы, ownership roots и roots
с module-level callsites. Edges включают необходимый `contains` и canonical
`calls`/`awaits` с исходными IDs и положительными weights. Self, reverse и
разные relation kinds не объединяются.

`callsite_counts` — zero-filled матрица resolution
`exact/ambiguous/external/dynamic/unresolved` × `awaited/non_awaited`:

```text
sum(await weights) == exact.awaited
sum(call weights)  == exact.non_awaited
```

Non-exact callsites не создают topology. Профиль сохраняет callable population,
ownership, weighted exact topology, synthetic identity и global occurrence
counts. Expressions, locations, individual callsites, candidates, complexity,
imports и types исключены; поэтому полную Metrics `call_graph` по нему
восстановить нельзя и Metrics Core его не принимает.
