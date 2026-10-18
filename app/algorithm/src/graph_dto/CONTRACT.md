# Graph DTO v1

The envelope requires `schema_version: 1`, a supported
`parser_semantics_version`, `project.fingerprint`, and arrays `nodes`, `edges`,
`callsites`, `diagnostics`. Parser semantics 1 remains readable for compatibility.
Parser semantics 2-5 additionally require `type_references`; semantics 4 and 5
also require occurrence-level `import_references`.
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

Current parser output uses semantics 5. In addition to file/class/callable nodes,
it emits field and module-constant nodes and the following typed relations:

- `inherits`: child class -> exact internal parent class;
- `field_type`: field -> exact internal class referenced by its annotation or
  constructor assignment;
- `accesses_field`: method -> declared field occurrence;
- `calls` / `awaits`: call owner -> exact internal callable.

Every base and field-type occurrence is represented by `type_references` with
role, source expression, location and `exact`, `ambiguous`, `external`, or
`unresolved` resolution. Exact references and `inherits`/`field_type` edges are
mutually consistent. Non-exact references never create topology edges.

Each semantics-4 static import alias, at any lexical nesting level, has a stable
reference with its source spelling, alias, relative level, location and one of
`exact`, `external`, or `unresolved`. The importer is the containing file node;
lexical scope is not topology. An exact reference targets one internal
file/module and has one matching `imports:<reference-id>` edge in `dependent ->
dependency` direction. Exact `from` resolution identifies the dependency module,
not the existence of the imported attribute. External absolute imports and
failed relative imports have no target or topology edge. Dynamic imports remain
callsites rather than static import references.

Semantics 2-5 validate endpoint kinds, require both `imports` endpoints to be
file/module nodes, require fields and methods to belong to classes, and
require `accesses_field` endpoints to have the same class owner.
Semantics 3-5 additionally require `complexity_facts` on every non-synthetic
function/method and forbids them elsewhere. The validator checks the exact facts
shape, control parent references, kind-specific cardinalities, source paths,
callable spans and occurrence/control locations. Semantics 1 and 2 remain
readable without these facts.
Semantics 5 additionally requires `class_kind` on class nodes, preserves every
supported module-constant occurrence as a distinct `constant` node, and treats
file/module nodes as parentless canonical roots. All descendant paths and
locations must agree with their owning root. The transitional `body` remains
required for the consumers not yet migrated.
The temporary top-level `body` mirror remains outside the canonical fingerprint.
