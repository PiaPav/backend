# Контракт `calls.detailed/1`

Graph View schema 1 создаётся из Graph DTO schema 1 / Parser semantics 7.
Payload содержит `nodes`, `edges`, `callsites`, `module_call_owner_ids` и
`owner_structural_facts`.

Nodes включают все roots для collision-safe labels, functions/methods и
классы-владельцы; non-synthetic callables сохраняют `complexity_facts`. Edges
содержат ownership и canonical weighted `calls`/`awaits`. Callsites сохраняют
ID, caller, expression, location, syntactic depth, resolution, target/candidates
и `awaited`.

Exact callsites обязаны совпадать с weighted topology по caller, target и kind.
Ambiguous candidates не становятся edges. `module_call_owner_ids` перечисляет
root callers, а structural `call_occurrences` не приравнивается к числу
callsites.

Профиль query-lossless для текущего basis Metrics `call_graph`, но не является
допустимым входом Metrics Core. Imports, types, fields, diagnostics и несвязанные
declarations исключены. Benchmark target: `<=60%` полного Graph DTO.
