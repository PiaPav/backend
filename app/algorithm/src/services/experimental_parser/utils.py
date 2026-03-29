import os
from typing import List, Dict, Set, Optional


def normalize_path(path: str) -> str:
    """Приводит путь к единому виду, заменяя разделители на прямые слеши."""
    return path.replace(os.path.sep, "/")


def create_project_index(files: List[str]) -> Dict[str, str]:
    """Создает маппинг имен модулей проекта в пути к соответствующим файлам."""
    return {
        normalize_path(f).replace("/", ".").replace(".py", ""): normalize_path(f)
        for f in files
    }


def _find_longest_matching_prefix(name: str, candidates: Set[str]) -> Optional[str]:
    """Находит наиболее специфичное совпадение префикса имени среди кандидатов."""
    found_path = None
    max_len = 0
    for f_path in candidates:
        if name == f_path:
            return f_path
        if name.startswith(f_path + "."):
            if len(f_path) > max_len:
                max_len = len(f_path)
                found_path = f_path
    return found_path
