# Parser file contract

`parse_project(source_path: Path, output_path: Path) -> Path` accepts only
`Path` instances. It atomically writes Graph DTO schema v1 / parser semantics v3
with canonical file, class, field and callable nodes; containment, import,
inheritance, field-type, field-access and call edges; callsites, type references,
diagnostics and a transitional legacy `body` mirror, then returns the resolved
output path. `starter()` keeps
returning the unchanged unversioned legacy graph for compatibility.

Every real function/method node carries canonical `complexity_facts`: callable
span and async status, ordered structural controls with parent indices and
cardinalities, and scoped occurrences. Nested function/class/lambda bodies are
excluded, while their declarations remain statement occurrences. The legacy
`body.metrics` projection is produced from the same facts in one AST pass.

Call records may include transitional `semantic_target` with exact project-local
`module` and callable `object`. The legacy `object` field remains unchanged.
Canonical callsites are collected independently, including nested calls, so this
projection does not alter legacy call records or metrics input.
Inheritance and field types are resolved in Parser from local declarations and
proven local import bindings. Aliased and qualified imports use the same
effective-module index as import/call resolution, including package initializer
precedence. Parser does not use project-wide short-name guessing. External and
unresolved references are preserved as non-topological `type_references`.

Declared `self.<field>` reads produce occurrence-level `accesses_field` edges;
nested functions, classes and lambdas are excluded from the enclosing method.
The legacy serializer remains unchanged.
Executable declaration expressions (defaults, annotations, class keywords and
class-suite expressions) use the surrounding file/callable owner. Bodies of
nested functions and lambdas are intentionally not attributed to that owner
until nested declaration nodes are part of the DTO.
