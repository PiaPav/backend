import json
from pathlib import Path

from rules.rules_config import RULES_CONFIG
from tools_engine.interface.tool import AbstractTool
from tools_engine.models.source_index_model import SourceIndex, SourceFile
from tools_engine.models.tool_models import ToolName


class GetContent(AbstractTool):
    name = ToolName.Get_Content

    # def __init__(self, source_index_path: Path):
    #
    #     self.source_index: SourceIndex = self._load_source_index(source_index_path)

    @staticmethod
    def _load_source_index(path: Path) -> SourceIndex:
        """Загрузка индекса файлов и структур для быстрого поиска"""
        raw_index = json.loads(path.read_text(encoding="utf-8"))
        return SourceIndex.from_dict(raw_index)

    def check_valid_filepath_with_bool(self, filepath: Path, index: SourceIndex) -> bool:
        """Проверка существования пути"""
        posix_path = filepath.as_posix()
        if posix_path in index.files.keys():
            return True
        return False

    @staticmethod
    def check_rules_with_raise(source_file: SourceFile):
        """Проверка правил"""
        if source_file.size_bytes > RULES_CONFIG.max_extraction_file_size:
            raise  # Ошибка большого размера файла
        if Path(source_file.relative_path).suffix != ".py":
            raise  # Ошибка стороннего расширения

    def get_raw_filedata(self, filepath: Path, index: SourceIndex) -> str:
        """Получение сырого текста файла"""
        posix_path = filepath.as_posix()
        project_path = index.project.root
        source_file = index.files[posix_path]

        self.check_rules_with_raise(source_file)

        resolve_filepath = Path(project_path) / Path(posix_path)

        return resolve_filepath.read_text(encoding=source_file.encoding)

    def execute(self, source_index_path: Path, **kwargs):
        """Запуск тулы"""
        filepath: Path = Path(kwargs.get("FILEPATH"))
        index = self._load_source_index(source_index_path)

        if not self.check_valid_filepath_with_bool(filepath, index):
            raise  # Ошибка неверного пути

        result = self.get_raw_filedata(filepath, index)

        return result
