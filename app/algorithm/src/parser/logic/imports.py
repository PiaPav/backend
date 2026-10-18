"""Import collection and project-local resolution."""

from __future__ import annotations

import ast

from .models import ImportInfo, ModuleInfo
from .project_index import ProjectIndex


def resolve_import_statement(
    statement: ast.Import | ast.ImportFrom,
    module: ModuleInfo,
    index: ProjectIndex,
) -> list[ImportInfo]:
    """Resolve one static statement, preserving its source alias order."""
    requested = (statement.module or "") if isinstance(statement, ast.ImportFrom) else ""
    level = statement.level if isinstance(statement, ast.ImportFrom) else 0
    package_depth = len(module.package.split(".")) if module.package else 0
    valid_context = level == 0 or level <= package_depth
    base_module = (
        index.resolve_module(requested, current_package=module.package, level=level)
        if isinstance(statement, ast.ImportFrom) and valid_context else None
    )
    result: list[ImportInfo] = []
    for alias_index, alias in enumerate(statement.names):
        if isinstance(statement, ast.Import):
            resolved = index.resolve_module(alias.name)
            import_module, object_name = "", alias.name
        else:
            child_requested = f"{requested}.{alias.name}" if requested else alias.name
            child = (
                index.resolve_module(
                    child_requested, current_package=module.package, level=level,
                )
                if valid_context and alias.name != "*" else None
            )
            resolved = child or base_module
            import_module, object_name = requested, alias.name
        result.append(ImportInfo(
            module=import_module,
            object_name=object_name,
            asname=alias.asname,
            local_module=resolved,
            from_lib=resolved is None,
            level=level,
            file=module.file,
            line=getattr(alias, "lineno", statement.lineno),
            column=getattr(alias, "col_offset", statement.col_offset),
            statement_line=statement.lineno,
            statement_column=statement.col_offset,
            alias_index=alias_index,
        ))
    return result


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, module: ModuleInfo, index: ProjectIndex) -> None:
        self.module = module
        self.index = index
        self.imports: list[ImportInfo] = []

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(resolve_import_statement(node, self.module, self.index))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.extend(resolve_import_statement(node, self.module, self.index))


def collect_imports(module: ModuleInfo, index: ProjectIndex) -> list[ImportInfo]:
    module.imports = [
        imported
        for statement in module.tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
        for imported in resolve_import_statement(statement, module, index)
    ]
    visitor = _ImportVisitor(module, index)
    visitor.visit(module.tree)
    module.canonical_imports = visitor.imports
    return module.imports
