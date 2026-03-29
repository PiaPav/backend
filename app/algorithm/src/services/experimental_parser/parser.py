from typing import List

import tree_sitter_python as tspython
from tree_sitter import Parser, Language

from logger import setup_logger
from services.experimental_parser.dependency_tracker import DependencyTracker
from services.experimental_parser.import_resolver import ImportResolver
from services.experimental_parser.node_handlers import NodeHandlers
from services.experimental_parser.scope_manager import ScopeManager
from services.experimental_parser.utils import normalize_path

logger = setup_logger(__name__)


class Analyzer(NodeHandlers):
    """
    Главный оркестратор анализа кода.
    Компонует зависимости и делегирует задачи специализированным классам.
    """

    def __init__(self, project_files: List[str], current_file: str):
        """Инициализирует анализатор с компонентами для разбора кода и отслеживания зависимостей."""
        # Инициализация tree-sitter
        PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(PY_LANGUAGE)

        # Нормализация входных данных
        self.project_files = set(normalize_path(f) for f in project_files)
        self.current_file = normalize_path(current_file)

        # Композиция компонентов (вместо наследования)
        self.import_resolver = ImportResolver(project_files)
        self.scope_manager = ScopeManager(current_file)
        self.dependency_tracker = DependencyTracker(self.project_files, self.import_resolver)

        # Состояние анализа
        self.definitions = {'methods': set(), 'attributes': set(), 'classes': set()}
        self.instance_of = {}
        self.aliases = {}
        self.result = {}  # Делегируется в dependency_tracker, но оставлен для совместимости
        self.code_bytes = b""

        # Синхронизация result между компонентами
        self.dependency_tracker.result = self.result

        logger.info(f"Analyzer initialized for: {self.current_file}")

    def analyze(self, code: str):
        """Запускает анализ исходного кода и возвращает граф зависимостей с определениями."""
        logger.info(f"Starting analysis of {self.current_file}")
        self.code_bytes = code.encode()
        self.result = {}
        self.dependency_tracker.result = self.result  # Синхронизация
        self.scope_manager = ScopeManager(self.current_file)  # Сброс стека
        self.aliases = {}

        tree = self.parser.parse(self.code_bytes)
        self._walk(tree.root_node)

        logger.info(f"Analysis complete. Found {len(self.result)} nodes")
        return {'graph': self.result, 'definitions': self.definitions, 'instance_of': self.instance_of}

    def _walk(self, node):
        """Рекурсивно обходит дерево синтаксического разбора, делегируя обработку узлов соответствующим обработчикам."""
        method = getattr(self, f"_handle_{node.type}", None)
        if method:
            method(node)
        else:
            for child in node.children:
                self._walk(child)


def analyze_code(code: str, project_files: List[str], current_file: str):
    """Публичная функция для анализа кода, создающая анализатор и запускающая обработку."""
    analyzer = Analyzer(project_files, current_file)
    return analyzer.analyze(code)
