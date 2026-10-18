# Parser file contract

`parse_project(source_path: Path, output_path: Path) -> Path` accepts only
`Path` instances. It atomically writes Graph DTO schema v1 / parser semantics v5
with canonical file, class, field, module-constant and callable nodes; containment, import,
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

Every static import alias, including imports nested in functions, classes and
control-flow bodies, is preserved as an occurrence-level `import_references`
record. Project-local imports are `exact` and create one canonical edge;
non-local absolute imports are `external`; failed relative imports, including
traversal above package context, are `unresolved`. For `from module import name`,
`exact` means that the dependency module was resolved, not that the imported
attribute was proven to exist. Non-exact imports do not create nodes or edges.
Dynamic imports remain callsites. The legacy `body` continues to expose only its
established module-level import projection.

Each class node carries the existing parser classification as `class_kind`.
Every supported top-level module constant is represented by a separate canonical
occurrence node with a stable ID; repeated declarations and chained targets are
not collapsed. These neutral declaration facts let Metrics calculate structural
populations without reading their legacy mirror.

Declared `self.<field>` reads produce occurrence-level `accesses_field` edges;
nested functions, classes and lambdas are excluded from the enclosing method.
The legacy serializer remains unchanged.
Executable declaration expressions (defaults, annotations, class keywords and
class-suite expressions) use the surrounding file/callable owner. Bodies of
nested functions and lambdas are intentionally not attributed to that owner
until nested declaration nodes are part of the DTO.
