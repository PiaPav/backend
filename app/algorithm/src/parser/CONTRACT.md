# Parser file contract

`parse_project(source_path: Path, output_path: Path) -> Path` accepts only
`Path` instances. It atomically writes Graph DTO v1 with canonical file and
declaration nodes, containment/import/call edges, callsites, diagnostics and a transitional
legacy `body` mirror, then returns the resolved output path. `starter()` keeps
returning the unchanged unversioned legacy graph for compatibility.

Call records may include transitional `semantic_target` with exact project-local
`module` and callable `object`. The legacy `object` field remains unchanged.
Canonical callsites are collected independently, including nested calls, so this
projection does not alter legacy call records or metrics input.
Executable declaration expressions (defaults, annotations, class keywords and
class-suite expressions) use the surrounding file/callable owner. Bodies of
nested functions and lambdas are intentionally not attributed to that owner
until nested declaration nodes are part of the DTO.
