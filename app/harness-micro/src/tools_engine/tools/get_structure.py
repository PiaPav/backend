import json
from pathlib import Path

from rules.rules_config import RULES_CONFIG
from tools_engine.interface.tool import AbstractTool
from tools_engine.models.source_index_model import SourceIndex, SourceSymbol, SourceSpan
from tools_engine.models.tool_models import ToolName, StructureType


class GetStructure(AbstractTool):
    name = ToolName.Get_Structure

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

    def get_structure_id(self, filepath: Path, structure_type: StructureType, structure_path: str,
                         index: SourceIndex) -> list[str]:
        """Ищет id структуры"""
        posix_path = filepath.as_posix()
        source_file = index.files[posix_path]

        if structure_type == StructureType.CLASS:
            if structure_path in source_file.classes.keys():
                return source_file.classes[structure_path]
            raise  # Структура отсутствует

        elif structure_type == StructureType.FUNCTION:
            if structure_path in source_file.functions.keys():
                return source_file.functions[structure_path]
            raise  # Структура отсутствует

        elif structure_type == StructureType.METHOD:
            structure_class = structure_path.split(".")[0]
            structure_method = structure_path.split(".")[1]

            if structure_class in source_file.classes.keys():
                class_id = source_file.classes[structure_class][0]

                if structure_method in index.symbols[class_id].methods:
                    return index.symbols[class_id].methods[structure_method]
                raise  # Структура отсутствует
            raise  # Структура отсутствует

        elif structure_type == StructureType.CONSTANT:
            if structure_path in source_file.constants.keys():
                return source_file.constants[structure_path]
            raise  # Структура отсутствует

        raise  # Неизвестный тип структуры ?

    @staticmethod
    def check_rules_with_raise(bites_size: int):
        """Проверка правил"""
        print(bites_size, RULES_CONFIG.max_extraction_structure_size)
        if bites_size > RULES_CONFIG.max_extraction_structure_size:
            raise  # Ошибка большого размера файла
        # if Path(source_file.relative_path).suffix != ".py":
        #     raise  # Ошибка стороннего расширения

    def get_raw_structure_data(self, structure_id: str, resolve_filepath: Path, index: SourceIndex,
                               encoding: str = "utf-8") -> str:
        """Получение сырого текста структуры"""
        source_symbol: SourceSymbol = index.symbols[structure_id]

        span: SourceSpan = source_symbol.span

        start_byte = span.start_byte - span.start_column
        expected_size = span.end_byte - start_byte
        self.check_rules_with_raise(expected_size)

        with resolve_filepath.open("rb") as source_file:
            source_file.seek(start_byte)
            raw_data = source_file.read(expected_size)

        return raw_data.decode(encoding)

    def get_resolve_filepath(self, filepath: Path, index: SourceIndex) -> Path:
        """Собирает абсолютный путь"""
        posix_path = filepath.as_posix()
        project_path = index.project.root
        resolve_filepath = Path(project_path) / Path(posix_path)

        return resolve_filepath

    def execute(self, source_index_path: Path, **kwargs):
        """Запуск тулы"""
        filepath: Path = Path(kwargs.get("FILEPATH"))
        structure_type: StructureType = StructureType(kwargs.get("STRUCTURE-TYPE"))
        structure_path: str = str(kwargs.get("STRUCTURE-PATH"))

        index = self._load_source_index(source_index_path)

        resolve_filepath = self.get_resolve_filepath(filepath, index)

        if not self.check_valid_filepath_with_bool(filepath, index):
            raise  # Ошибка неверного пути

        structure_id = self.get_structure_id(filepath, structure_type, structure_path, index)[0]

        result = self.get_raw_structure_data(structure_id, resolve_filepath, index)

        return result
