# Metrics file contract

`calculate_metrics(graph_path: Path, output_path: Path) -> Path` accepts only a
validated Graph DTO with `schema_version: 1` and `parser_semantics_version` 6 or
7. Unversioned graphs and parser semantics 1-5 are no longer Metrics inputs;
callers must regenerate them with `parser.parse_project()`. The shared Graph DTO
validator still recognizes the historical versions independently of this
consumer policy.

Semantics 6 and 7 contain all declarations, typed relations, complexity facts
and structural owner facts required by Metrics. Semantics 6 may carry an
optional `body`, but Metrics never reads it and the canonical fingerprint
ignores it. Semantics 7 forbids `body`. The in-memory
`calculate_graph_metrics(graph)` gateway applies the same version and structural
validation as the file API.

The output envelope is:

```json
{
  "schema_version": 1,
  "metrics_semantics_version": 4,
  "input": {
    "graph_schema_version": 1,
    "graph_fingerprint": "..."
  },
  "metrics": {}
}
```

Removing support for older inputs does not change formulas, thresholds,
rounding or output structure, so the mathematical semantics remains version 4.
The v6 and v7 canonical-equivalent payloads produce equal `metrics`; their full
input fingerprints differ because the parser semantics version is part of the
canonical envelope. `legacy_body_fingerprint` is no longer emitted.

Malformed JSON, non-object roots, unsupported schema versions and unsupported
parser semantics are rejected before output publication. Rejection preserves an
existing target. Successful output is written atomically as UTF-8 JSON with LF
line endings, `ensure_ascii=False`, two-space indentation, sorted keys and one
final newline. A temporary file is created beside the target and published with
`os.replace`; failures preserve the target and trigger best-effort cleanup.

## Canonical projection

Each aggregate calculation builds one immutable `MetricsGraphProjection`.
Internal calculators consume only this projection; public section gateways may
accept a caller-supplied projection and otherwise validate and project their raw
graph argument. The projection contains only canonical nodes, callsites,
occurrence-level import references, structural owner facts and typed topology.
There is no legacy file identity, nested-body traversal or string-based target
resolution in production Metrics.

Import edges are directed `dependent -> dependency`. Repeated import
occurrences affect activity facts but not the deduplicated file/package
topology. Canonical call topology uses ID-only `calls`/`awaits` edges; edge
weights preserve callsite multiplicity, while SCC, reachability, PageRank and
betweenness use the unweighted topology. `inherits`, `field_type` and
`accesses_field` relations drive object metrics exclusively by node ID.

## Preserved metrics semantics

Structural size is derived from canonical declaration nodes. Synthetic methods
do not increase the method population. Activity is derived from
`owner_structural_facts`; import counts are occurrences, not graph degrees.

`activity.average_calls_per_call_owner` retains the historical hybrid
denominator: every real function and method is counted whether active or not,
and a file/module root is counted only when it has at least one root-level call.
In symbols, the denominator is `real callables + roots with calls`. Changing it
requires a new metrics semantics version.

Object metrics use these definitions:

- DIT is the longest exact `inherits` path and is `null` when ancestry reaches a
  cycle;
- NOC counts distinct direct exact children;
- CBO is the distinct union of exact parents, owned-field class types and owner
  classes of exact callable targets, excluding self-coupling;
- RFC is the union of declared non-synthetic method IDs and their distinct exact
  callable targets;
- LCOM preserves the normalized pairwise formula over canonical field IDs;
- WMC sums canonical cyclomatic complexity of non-synthetic methods.

External, ambiguous, dynamic and unresolved facts never create topology.
Risk remains a relative heuristic in `[0, 100]` with weights
`0.35/0.25/0.20/0.20`, not a probability. Package instability,
abstractness and distance use canonical root ownership and `class_kind`.

The removed legacy contract is retained only as migration history in
[`LEGACY_GRAPH_CONTRACT.md`](LEGACY_GRAPH_CONTRACT.md). It is not an active
Metrics input contract.
