# Parser file contract

`parse_project(source_path: Path, output_path: Path) -> Path` accepts only
`Path` instances. It atomically writes Graph DTO v1 with canonical file and
declaration nodes, containment/import edges, diagnostics and a transitional
legacy `body` mirror, then returns the resolved output path. `starter()` keeps
returning the unchanged unversioned legacy graph for compatibility.

Call records may include transitional `semantic_target` with exact project-local
`module` and callable `object`. The legacy `object` field remains unchanged.
