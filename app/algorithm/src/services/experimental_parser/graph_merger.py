import json
from typing import Optional, Dict

from services.experimental_parser.utils import _find_longest_matching_prefix


class GraphMerger:
    def __init__(self, project_modules: Optional[Dict[str, str]] = None):
        """Инициализирует объединитель графов с опциональной информацией о модулях проекта."""
        self.graph = {}
        self.grouped_graph = {}
        self._project_file_paths = set(project_modules.values()) if project_modules else set()
        self.definitions = {'methods': set(), 'attributes': set(), 'classes': set()}
        self.instance_of = {}

    def merge(self, graphs: list, group_by_file: bool = False):
        """Объединяет несколько графов зависимостей с опцией группировки по файлам."""
        for g in graphs:
            if isinstance(g, dict) and 'graph' in g:
                self._merge_single(g['graph'])
                if 'definitions' in g:
                    self._merge_definitions(g['definitions'])
                if 'instance_of' in g and g['instance_of']:
                    self.instance_of.update(g['instance_of'])
            else:
                self._merge_single(g)
        self._deduplicate()
        self._ensure_all_nodes_exist()
        if group_by_file:
            self.grouped_graph = self._group_by_hierarchy()
            return self.grouped_graph
        return self.graph

    def _merge_definitions(self, defs: dict):
        """Объединяет словари определений методов, атрибутов и классов."""
        self.definitions['methods'].update(defs.get('methods', set()))
        self.definitions['attributes'].update(defs.get('attributes', set()))
        self.definitions['classes'].update(defs.get('classes', set()))
        if 'instance_of' in defs:
            self.instance_of.update(defs['instance_of'])

    def _merge_single(self, g: dict):
        """Добавляет узлы и зависимости из одного графа в общий результат."""
        for node, deps in g.items():
            if node not in self.graph:
                self.graph[node] = []
            self.graph[node].extend(deps)

    def _deduplicate(self):
        """Удаляет дубликаты зависимостей для каждого узла графа."""
        for node in self.graph:
            self.graph[node] = list(set(self.graph[node]))

    def _ensure_all_nodes_exist(self):
        """Гарантирует, что все узлы-зависимости присутствуют в графе как ключи."""
        all_deps = set()
        for deps in self.graph.values():
            all_deps.update(deps)
        for dep in all_deps:
            if dep not in self.graph:
                self.graph[dep] = []
        for method in self.definitions['methods']:
            if method not in self.graph:
                self.graph[method] = []
        for attr in self.definitions['attributes']:
            if attr not in self.graph:
                self.graph[attr] = []
        for cls in self.definitions.get('classes', set()):
            if cls not in self.graph:
                self.graph[cls] = []

    def _find_file_path(self, node_name):
        """Находит путь к файлу проекта для заданного имени узла."""
        # >>> REUSED: _find_longest_matching_prefix из utils.py
        return _find_longest_matching_prefix(node_name, self._project_file_paths)

    def _group_by_hierarchy(self):
        """Группирует граф зависимостей по иерархии файлов и классов."""
        grouped = {}

        def ensure_class_structure(file_path, class_name):
            if class_name not in grouped[file_path]:
                grouped[file_path][class_name] = {
                    "": {"deps": []},
                    "methods": {},
                    "attributes": []
                }
            else:
                if "" not in grouped[file_path][class_name]:
                    grouped[file_path][class_name][""] = {"deps": []}
                if "methods" not in grouped[file_path][class_name]:
                    grouped[file_path][class_name]["methods"] = {}
                if "attributes" not in grouped[file_path][class_name]:
                    grouped[file_path][class_name]["attributes"] = []

        graph_items = list(self.graph.items())
        for node, deps in graph_items:
            file_path = self._find_file_path(node)
            if not file_path:
                continue
            internal_part = node[len(file_path):]
            if internal_part.startswith("."):
                internal_part = internal_part[1:]
            parts = internal_part.split(".") if internal_part else []
            if file_path not in grouped:
                grouped[file_path] = {"": {"deps": [], "objects": {}}}
            if len(parts) == 1:
                obj_name = parts[0]
                if not obj_name:
                    continue
                full_node_name = f"{file_path}.{obj_name}"
                is_class = (
                        any(m.startswith(f"{full_node_name}.") for m in self.definitions['methods'])
                        or full_node_name in self.definitions.get('classes', set())
                )
                if is_class:
                    ensure_class_structure(file_path, obj_name)
                    grouped[file_path][obj_name][""]["deps"].extend(deps)
                else:
                    filtered_deps = []
                    for dep in deps:
                        if not dep.startswith(f"{full_node_name}."):
                            filtered_deps.append(dep)
                    grouped[file_path][""]["objects"][obj_name] = {"deps": filtered_deps}
                    if full_node_name in self.instance_of:
                        grouped[file_path][""]["objects"][obj_name]["instance_of"] = self.instance_of[full_node_name]
            elif len(parts) >= 2:
                class_name = parts[0]
                member_name = parts[1]
                full_class_name = f"{file_path}.{class_name}"
                is_class = (
                        any(m.startswith(f"{full_class_name}.") for m in self.definitions['methods'])
                        or full_class_name in self.definitions.get('classes', set())
                )
                if not is_class:
                    continue
                ensure_class_structure(file_path, class_name)
                full_member_name = f"{file_path}.{class_name}.{member_name}"
                if len(parts) == 2:
                    if full_member_name in self.definitions['methods']:
                        grouped[file_path][class_name]["methods"][member_name] = deps
                    else:
                        is_attr_exact = full_member_name in self.definitions.get('attributes', set())
                        is_attr_suffix = any(
                            attr.endswith(f".{member_name}") for attr in self.definitions.get('attributes', set()))
                        if is_attr_exact or is_attr_suffix:
                            grouped[file_path][class_name]["attributes"].append({
                                "name": member_name,
                                "deps": deps
                            })
                        else:
                            grouped[file_path][class_name]["methods"][member_name] = deps
                else:
                    method_name = parts[1]
                    if method_name not in grouped[file_path][class_name]["methods"]:
                        grouped[file_path][class_name]["methods"][method_name] = []
                    dep_name = ".".join(parts[2:])
                    full_dep_name = f"{file_path}.{class_name}.{dep_name}"
                    if full_dep_name not in grouped[file_path][class_name]["methods"][method_name]:
                        grouped[file_path][class_name]["methods"][method_name].append(full_dep_name)
            else:
                grouped[file_path][""]["deps"].extend(deps)
        self._cleanup_empty_groups(grouped)
        return grouped

    def _cleanup_empty_groups(self, grouped):
        """Удаляет пустые группы из сгруппированного графа."""
        for file_path in list(grouped.keys()):
            for name in list(grouped[file_path].keys()):
                if name == "":
                    if not grouped[file_path][""]["deps"] and not grouped[file_path][""]["objects"]:
                        del grouped[file_path][""]
                else:
                    item = grouped[file_path][name]
                    is_class_structure = "methods" in item or "attributes" in item
                    if is_class_structure:
                        if not item[""].get("deps"):
                            item.pop("", None)
                    else:
                        if not item.get("deps"):
                            del grouped[file_path][name]

    def export_grouped(self, format="dict"):
        """Экспортирует сгруппированный граф в формате dict или JSON."""
        if format == "dict":
            return self.grouped_graph
        elif format == "json":
            return json.dumps(self.grouped_graph, indent=2, ensure_ascii=False)
