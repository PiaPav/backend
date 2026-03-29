from typing import List

from services.experimental_parser.utils import normalize_path


class ScopeManager:
    """
    Управляет стеком областей видимости и вычислением текущего скоупа.
    Изолирует логику работы со скоупами от бизнес-логики парсинга.
    """

    def __init__(self, current_file: str):
        """Инициализирует менеджер областей видимости для текущего файла."""
        self.current_file = normalize_path(current_file)
        self.scope_stack: List[tuple] = []

    def push_scope(self, scope_type: str, name: str):
        """Добавляет новую область видимости в стек."""
        self.scope_stack.append((scope_type, name))

    def pop_scope(self):
        """Извлекает и удаляет верхнюю область видимости из стека."""
        if self.scope_stack:
            return self.scope_stack.pop()
        return None

    def get_current_scope(self) -> str:
        """Возвращает строковое представление текущей области видимости."""
        if not self.scope_stack:
            return self.current_file
        names = [name for _, name in self.scope_stack]
        return f"{self.current_file}." + ".".join(names)

    def get_current_scope_type(self) -> tuple:
        """Возвращает тип и имя текущей области видимости."""
        if not self.scope_stack:
            return 'module', None
        return self.scope_stack[-1]

    def is_module_level(self) -> bool:
        """Проверяет, находится ли текущая область на уровне модуля."""
        scope_type, _ = self.get_current_scope_type()
        return scope_type == 'module'

    def is_class_level(self) -> bool:
        """Проверяет, находится ли текущая область на уровне класса."""
        scope_type, _ = self.get_current_scope_type()
        return scope_type == 'class'
