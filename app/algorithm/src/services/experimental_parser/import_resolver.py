from typing import List, Set, Dict, Optional

from services.experimental_parser.utils import normalize_path


class ImportResolver:
    """
    Отвечает за разрешение импортов и алиасов.
    Не зависит от состояния парсинга, только от конфигурации проекта.
    """

    def __init__(self, project_files: List[str]):
        """Инициализирует резолвер импортов для заданных файлов проекта."""
        self.project_files = set(normalize_path(f) for f in project_files)
        self.project_modules = self._build_project_modules(self.project_files)

    def _build_project_modules(self, files: Set[str]) -> Dict[str, str]:
        """Строит словарь имен модулей проекта в пути к файлам."""
        modules = {}
        for f in files:
            mod_name = f.replace("/", ".").replace(".py", "")
            modules[mod_name] = f
        return modules

    def resolve_import(self, module: str) -> Optional[str]:
        """Разрешает имя модуля в путь к файлу проекта или возвращает None."""
        if module in self.project_modules:
            return self.project_modules[module]
        parts = module.split(".")
        for proj_mod, proj_file in self.project_modules.items():
            proj_parts = proj_mod.split(".")
            if len(proj_parts) >= len(parts) and proj_parts[-len(parts):] == parts:
                return proj_file
        return None

    def resolve_relative_import(self, from_part: str, current_file: str) -> str:
        """Разрешает относительный импорт относительно текущего файла."""
        level = 0
        while from_part.startswith("."):
            level += 1
            from_part = from_part[1:]
        current = normalize_path(current_file).split("/")
        base = current[:-1]
        for _ in range(level - 1):
            if base:
                base.pop()
        if from_part:
            base.extend(from_part.split("."))
        return "/".join(base)

    def resolve_full_name(self, name: str, aliases: Dict[str, str], visited: Optional[Set[str]] = None,
                          depth: int = 0) -> str:
        """Разрешает полное имя с учетом алиасов и рекурсивных ссылок."""
        if visited is None:
            visited = set()
        parts = name.split(".")
        if parts[0] in aliases and parts[0] not in visited:
            visited.add(parts[0])
            base = aliases[parts[0]]
            if base in aliases and base not in visited:
                base = self.resolve_full_name(base, aliases, visited, depth + 1)
            return ".".join([base] + parts[1:]) if len(parts) > 1 and base else (base or name)
        return name
