# Graph DTO v1

The envelope requires `schema_version: 1`, `parser_semantics_version: 1`,
`project.fingerprint`, and arrays `nodes`, `edges`, `callsites`, `diagnostics`.
Canonical collections are sorted before serialization. The SHA-256 fingerprint
is calculated over the envelope without `project.fingerprint` and without the
transitional `body` mirror; it is therefore independent of collection order.

File IDs are `file:<relative POSIX path>` (for example `file:pkg.py` and
`file:pkg/__init__.py`). All node references must exist. `contains` is an
acyclic forest and agrees with `parent_id`. Exact callsites have one
`target_id`; ambiguous callsites have at least two sorted `candidate_ids`;
external, dynamic and unresolved callsites have no internal target. Callsite
IDs are non-empty, `awaited` is a boolean, and declared callsite/edge locations
are structurally valid. Every exact internal callsite group has exactly the
corresponding aggregated `calls`/`awaits` weight (and vice versa); such edges
always carry a positive integer weight.

The current parser output includes file/class/callable nodes, containment and
resolved local import edges. Full canonical callsite, inheritance and type
resolution is explicitly marked incomplete by a diagnostic; legacy facts are
available only through the temporary top-level `body` mirror.
