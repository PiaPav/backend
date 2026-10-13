# Parser file contract

`parse_project(source_path: Path, output_path: Path) -> Path` accepts only
`Path` instances.  It writes the current legacy graph (`{"body": ...}`) as
canonical, sorted JSON, atomically, and returns the resolved output path.
This first increment deliberately does not claim to emit Graph DTO v1.
