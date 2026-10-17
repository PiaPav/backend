# Metrics file contract

`calculate_metrics(graph_path: Path, output_path: Path) -> Path` accepts a
legacy unversioned parser graph or a validated Graph DTO v1. During migration,
some formulas still consume its required legacy `body` adapter; canonical
identity and fingerprint always come only from canonical v1 content. Until all
formulas are migrated, a result is identified by the pair `input.graph_fingerprint`
and `input.legacy_body_fingerprint`; the latter changes with every semantic
change to the actual legacy metric input. Output is atomic.
The exhaustive field-to-consumer matrix for this compatibility projection is
maintained in [`LEGACY_GRAPH_CONTRACT.md`](LEGACY_GRAPH_CONTRACT.md).
Version dispatch is explicit:

- unversioned legacy input uses metrics semantics v1;
- Graph DTO v1 / parser semantics v1 uses metrics semantics v2 and the legacy
  topology adapter;
- Graph DTO v1 / parser semantics v2 uses metrics semantics v3.
- Graph DTO v1 / parser semantics v3 uses metrics semantics v4.

Semantics v3 builds object and call topology exclusively from canonical node IDs,
typed edges, callsites and type references. Legacy `body` is still used for
size, activity, architecture, quality and WMC until complexity facts migrate.
Semantics v4 derives callable complexity from canonical facts keyed by node ID.
Quality, WMC and call-graph risk use that projection; transitional body mutation
cannot affect them. Synthetic constructors are excluded from those populations.

Semantics v1-v3 intentionally preserve the historical hybrid denominator
of `activity.average_calls_per_call_owner`: every declared function and method
is counted, whether or not it contains a call, and a module is counted only
when it contains at least one module-level call. In symbols, the denominator is
`functions + methods + modules_with_calls`. The name "call owner" must not be
read as "active owner" for these versions. Changing to active owners only would
change metric values and therefore requires a new metrics semantics version.

`input.graph_fingerprint` is calculated from canonical decoded legacy DTO
content, including a canonical order exclusively for the root graph `body`
file collection, rather than from the source JSON bytes. All nested lists,
including values of nested keys named `body`, retain their order during the
compatibility period.

Semantics-v3 object metrics use these project-internal definitions:

- DIT is the longest exact `inherits` path and is `null` when ancestry reaches a
  cycle;
- NOC counts distinct direct exact children;
- CBO is the distinct union of exact parent, owned-field type, and called-method
  owner class IDs, excluding self-coupling;
- RFC is the union of declared non-synthetic method IDs and their distinct exact
  callable targets;
- LCOM preserves the normalized pairwise formula over canonical field IDs.

External, ambiguous, dynamic and unresolved facts do not create metric topology.
Canonical call-graph topology uses only `calls`/`awaits`; callsite resolution
provides classification and zero-based depth is reported as one-based nesting.
Declared functions and methods remain graph vertices; file/module vertices are
included only when they own a canonical callsite or an outgoing canonical call
edge. In semantics v4 `risk_top` joins canonical complexity to topology only by
node ID. Semantics v1-v3 retain their prior compatibility behavior.
String, import-suffix and annotation-name resolution is confined to legacy v1/v2
compatibility branches.

When a legacy call record contains the parser's transitional `semantic_target`,
local call resolution uses it exclusively. Records without it retain the legacy
short-name fallback.
