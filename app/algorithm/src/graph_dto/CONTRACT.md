# Graph DTO v1

The envelope requires `schema_version: 1`, a supported
`parser_semantics_version`, `project.fingerprint`, and arrays `nodes`, `edges`,
`callsites`, `diagnostics`. Parser semantics 1 remains readable for compatibility.
Parser semantics 2 additionally requires `type_references`.
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
always carry a positive integer weight. File/module nodes may own module-level
callsites and be call-edge sources; targets remain function/method nodes.

Current parser output uses semantics 2. In addition to file/class/callable nodes,
it emits field nodes and the following typed relations:

- `inherits`: child class -> exact internal parent class;
- `field_type`: field -> exact internal class referenced by its annotation or
  constructor assignment;
- `accesses_field`: method -> declared field occurrence;
- `calls` / `awaits`: call owner -> exact internal callable.

Every base and field-type occurrence is represented by `type_references` with
role, source expression, location and `exact`, `ambiguous`, `external`, or
`unresolved` resolution. Exact references and `inherits`/`field_type` edges are
mutually consistent. Non-exact references never create topology edges.

Semantics 2 validates endpoint kinds, requires both `imports` endpoints to be
file/module nodes, requires fields and methods to belong to classes, and
requires `accesses_field` endpoints to have the same class owner.
The temporary top-level `body` mirror remains outside the canonical fingerprint.
