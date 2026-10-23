# Metrics file contract

`calculate_metrics(graph_path: Path, output_path: Path) -> Path` accepts a
legacy unversioned parser graph or a validated Graph DTO v1. Parser semantics
v1-v5 retain the required legacy `body` compatibility adapter. Semantics v6 and
v7 are calculated entirely from canonical content; v6 may carry an ignored
optional `body`, while v7 forbids it. Canonical identity and fingerprint always come only from
canonical v1 content. Compatibility results include
`input.legacy_body_fingerprint`; semantics-v6/v7 results do not. Output is atomic.
The canonical writer stores UTF-8 JSON with LF line endings,
`ensure_ascii=False`, two-space indentation, sorted keys and exactly one final
newline. It writes a temporary file beside the target and publishes it with
`os.replace`; failures preserve an existing target and trigger best-effort
temporary-file cleanup without masking the original error. The compatibility full and compact writers use the same atomic delivery
while retaining their established key order and compact encoding.
The exhaustive field-to-consumer matrix for this compatibility projection is
maintained in [`LEGACY_GRAPH_CONTRACT.md`](LEGACY_GRAPH_CONTRACT.md).
Version dispatch is explicit:

- unversioned legacy input uses metrics semantics v1;
- Graph DTO v1 / parser semantics v1 uses metrics semantics v2 and the legacy
  topology adapter;
- Graph DTO v1 / parser semantics v2 uses metrics semantics v3.
- Graph DTO v1 / parser semantics v3 uses metrics semantics v4.
- Graph DTO v1 / parser semantics v4 uses metrics semantics v4; formulas are
  unchanged, while file import topology comes from canonical exact import edges.
- Graph DTO v1 / parser semantics v5 uses metrics semantics v4; formulas remain
  unchanged, while structural size and package class populations use canonical
  declaration nodes.
- Graph DTO v1 / parser semantics v6 uses metrics semantics v4; activity also
  uses canonical structural owner facts and the entire calculation is bodyless.
- Graph DTO v1 / parser semantics v7 uses the same metrics semantics v4 and
  bodyless formulas; the input contract no longer permits `body`.

Semantics v3 builds object and call topology exclusively from canonical node IDs,
typed edges, callsites and type references.
Semantics v4 derives callable complexity from canonical facts keyed by node ID.
Quality, WMC and call-graph risk use that projection; transitional body mutation
cannot affect them. Synthetic constructors are excluded from those populations.
Parser semantics v5-v7 additionally derive `size` and package file/class/abstract
populations from canonical roots, declaration nodes and `class_kind`. Synthetic
constructors do not increase structural method counts. In semantics v6 and v7,
activity derives call and direct-import occurrences from
`owner_structural_facts`; body mutation or omission cannot affect it.

Current metrics semantics v1-v4 intentionally preserve the historical hybrid denominator
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

Metric calculation constructs one internal read-only `MetricsGraphProjection`.
It exposes collision-safe legacy file identity and effective semantic modules,
canonical nodes/callsites, directed file and package imports in the explicit
`dependent -> dependency` direction, normalized undirected file pairs, and an
immutable file-to-package ownership view. Architecture metrics consume these
file, package and undirected topology views from the same projection; for
parser semantics v4 the canonical package topology intentionally coexists with
legacy package populations, while v5 and later use canonical ownership.
Topology-only packages therefore have zero structural population. An ID-only
weighted `calls`/`awaits` graph and canonical object topology are exposed
through separate directed `inherits` (`class -> class`), `field_type`
(`field -> class`), and `accesses_field` (`method -> field`) views. Its DTOs are
frozen and its topology collections are immutable. This is an internal
data/topology view: it does not change formulas or perform legacy string
resolution. The transitional `body` adapter remains only for parser semantics
v1-v5.
Canonical size, complexity, quality, object WMC and call-graph risk read node
attributes, complexity facts and parser semantics version from that same
snapshot. Once a projection has been built, later mutation of the input mapping
cannot mix declaration data from one graph state with topology from another.
The canonical callable-complexity calculator and the private canonical
call-graph calculator accept only this projection. Raw graph mappings are
converted at their compatibility gateways when no projection is supplied, so
canonical calculators cannot read declaration data and topology from different
snapshots during one calculation.
For parser semantics v4 and later, import references are exposed as an immutable snapshot
and import topology is independent of legacy `body[*].file.imports`; older
parser semantics retain the compatibility projection.

Legacy nested calls have one compatibility traversal. A root mapping call has
depth 1; recursion follows only `args[*].value` mappings whose `type` is
`call`, preserving argument order. Activity, legacy call nesting, and RFC call
name collection consume that same traversal.

When a legacy call record contains the parser's transitional `semantic_target`,
local call resolution uses it exclusively. Records without it retain the legacy
short-name fallback.
