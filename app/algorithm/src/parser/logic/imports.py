"""Import collection and project-local resolution."""

from __future__ import annotations

import ast

from .models import ImportInfo, ModuleInfo
from .project_index import ProjectIndex


def collect_imports(module: ModuleInfo, index: ProjectIndex) -> list[ImportInfo]:
    imports: list[ImportInfo] = []
    for node in module.tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_module = index.resolve_module(alias.name)
                imports.append(
                    ImportInfo(
                        module="",
                        object_name=alias.name,
                        asname=alias.asname,
                        local_module=local_module,
                        from_lib=local_module is None,
                        file=module.file,
                        line=node.lineno,
                        column=node.col_offset,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            requested = node.module or ""
            local_module = index.resolve_module(
                requested, current_package=module.package, level=node.level
            )
            for alias in node.names:
                # `from package import module` may target a child module.
                child_requested = f"{requested}.{alias.name}" if requested else alias.name
                child_module = index.resolve_module(
                    child_requested,
                    current_package=module.package,
                    level=node.level,
                )
                resolved = child_module or local_module
                imports.append(
                    ImportInfo(
                        module=requested,
                        object_name=alias.name,
                        asname=alias.asname,
                        local_module=resolved,
                        from_lib=resolved is None,
                        level=node.level,
                        file=module.file,
                        line=node.lineno,
                        column=node.col_offset,
                    )
                )
    module.imports = imports
    return imports
