from typing import Set, Dict, List

from services.experimental_parser.import_resolver import ImportResolver
from services.experimental_parser.utils import _find_longest_matching_prefix


class DependencyTracker:
    """
    Отвечает за добавление зависимостей в граф и фильтрацию системных вызовов.
    """

    def __init__(self, project_files: Set[str], import_resolver: ImportResolver):
        """Инициализирует трекер зависимостей с резолвером импортов."""
        self.project_files = project_files
        self.import_resolver = import_resolver
        self.result: Dict[str, List[str]] = {}

    def _is_user_call(self, name: str) -> bool:
        """Определяет, относится ли имя к пользовательскому коду проекта."""
        return any(name.startswith(f_path + ".") or name == f_path for f_path in self.project_files)

    def add_dependency(self, scope: str, target: str):
        """Добавляет зависимость между областью видимости и целевым элементом."""
        if not scope:
            return
        if scope not in self.result:
            self.result[scope] = []
        if target not in self.result[scope]:
            self.result[scope].append(target)

    def add_call(self, name: str, scope: str, aliases: Dict[str, str]):
        """Обрабатывает вызов функции и регистрирует зависимость, если это пользовательский код."""
        resolved_name = self.import_resolver.resolve_full_name(name, aliases)
        if not self._is_user_call(resolved_name):
            return

        owner_file = _find_longest_matching_prefix(resolved_name, self.project_files)
        if not owner_file:
            return

        stored_name = name
        has_prefix = any(name.startswith(f + ".") or name == f for f in self.project_files)
        if not has_prefix:
            stored_name = f"{owner_file}.{name}"

        self.add_dependency(scope, stored_name)
