# Metrics file contract

`calculate_metrics(graph_path: Path, output_path: Path) -> Path` accepts a
legacy unversioned parser graph only. A versioned input is rejected unless its
`schema_version` is explicitly supported; Graph DTO v1 is **not** supported by
this increment. Output is an atomic deterministic Metrics DTO envelope with
`schema_version: 1` and `metrics_semantics_version: 1`.

`input.graph_fingerprint` is calculated from canonical decoded legacy DTO
content, including a canonical order exclusively for the root graph `body`
file collection, rather than from the source JSON bytes. All nested lists,
including values of nested keys named `body`, retain their order during the
compatibility period.
