"""Post-collection class classification."""

from __future__ import annotations

from .models import ClassInfo, ModuleInfo


def classify_classes(modules: list[ModuleInfo]) -> None:
    classes = {
        (module.module, item.name): item
        for module in modules
        for item in module.classes
    }
    module_map = {module.module: module for module in modules}

    def resolve_parent(item: ClassInfo, parent_name: str) -> ClassInfo | None:
        short_name = parent_name.rsplit(".", 1)[-1]
        local = classes.get((item.module, short_name))
        if local:
            return local
        module = module_map[item.module]
        imported = module.import_aliases.get(parent_name.split(".", 1)[0])
        if imported and imported.local_module:
            return classes.get((imported.local_module, imported.object_name))
        return None

    def unresolved_abstract_methods(item: ClassInfo, visiting: set[str]) -> set[str]:
        if item.name in visiting:
            return set()
        inherited: set[str] = set()
        for parent_name in item.parents:
            parent = resolve_parent(item, parent_name)
            if parent:
                inherited |= unresolved_abstract_methods(parent, visiting | {item.name})
                inherited |= parent.abstract_methods
        implemented = {
            method.name
            for method in item.methods
            if method.name not in item.abstract_methods
        }
        return (inherited | item.abstract_methods) - implemented

    for item in classes.values():
        decorator_names = {name.rsplit(".", 1)[-1] for name in item.decorators}
        parent_names = {name.rsplit(".", 1)[-1] for name in item.parents}
        if "dataclass" in decorator_names:
            item.kind = "dataclass"
        elif "Enum" in parent_names:
            item.kind = "enum"
        elif "ABC" in parent_names or unresolved_abstract_methods(item, set()):
            item.kind = "abstract"
        else:
            item.kind = "class"
