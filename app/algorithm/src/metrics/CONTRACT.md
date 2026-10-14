# Metrics file contract

`calculate_metrics(graph_path: Path, output_path: Path) -> Path` accepts a
legacy unversioned parser graph or a validated Graph DTO v1. During migration,
v1 formulas consume only its required legacy `body` adapter; canonical identity
and fingerprint always come only from canonical v1 content. Until canonical
formulas exist, a result is identified by the pair `input.graph_fingerprint`
and `input.legacy_body_fingerprint`; the latter changes with every semantic
change to the actual legacy metric input. Output is atomic.
Legacy input uses metrics semantics v1; Graph DTO v1 uses semantics v2, where
DIT is `null` for classes whose ancestry reaches an inheritance cycle.
Canonical-mode object metrics expose deterministic per-class rows in `classes`
so this unknown depth is not replaced by a false finite value.

`input.graph_fingerprint` is calculated from canonical decoded legacy DTO
content, including a canonical order exclusively for the root graph `body`
file collection, rather than from the source JSON bytes. All nested lists,
including values of nested keys named `body`, retain their order during the
compatibility period.

Canonical call, inheritance, and type edges are not implemented yet. This v1
metrics path is transitional and does not claim completion of later migration
stages.

When a legacy call record contains the parser's transitional `semantic_target`,
local call resolution uses it exclusively. Records without it retain the legacy
short-name fallback.
