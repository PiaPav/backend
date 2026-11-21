from response_models.models import StructureType, ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.source import SourceAccessor
from tools_engine.interface.tool import (
    AbstractTool, ExtractionLimitExceeded, InvalidArtifact,
    InvalidToolArguments, SourceObjectNotFound,
)
from tools_engine.models.analysis_context import AnalysisContext


class GetStructure(AbstractTool):
    name = ToolName.Get_Structure

    @staticmethod
    def _ids(index, source_file, filepath: str, structure_type: StructureType,
             structure_path: str) -> list[str]:
        if structure_type is StructureType.CLASS:
            return source_file.classes.get(structure_path, [])
        if structure_type is StructureType.FUNCTION:
            return source_file.functions.get(structure_path, [])
        if structure_type is StructureType.CONSTANT:
            return source_file.constants.get(structure_path, [])
        parts = structure_path.split(".")
        if len(parts) != 2 or not all(parts):
            raise InvalidToolArguments(
                "STRUCTURE-PATH для METHOD должен иметь формат Class.method",
                {"argument": "STRUCTURE-PATH"},
            )
        class_ids = source_file.classes.get(parts[0], [])
        if not class_ids:
            return []
        class_symbol = index.symbols.get(class_ids[0])
        class_id = class_ids[0]
        if (class_symbol is None or class_symbol.source_id != class_id
                or class_symbol.kind != "class" or class_symbol.name != parts[0]
                or class_symbol.file != filepath):
            raise InvalidArtifact(details={"artifact": "source_index"})
        return class_symbol.methods.get(parts[1], [])

    @staticmethod
    def _validate_symbol(index, source_id: str, symbol, filepath: str,
                         structure_type: StructureType, structure_path: str) -> None:
        expected_kind = structure_type.value.lower()
        expected_name = structure_path
        if structure_type is StructureType.METHOD:
            class_name, expected_name = structure_path.split(".")
            class_id = index.files[filepath].classes[class_name][0]
            class_symbol = index.symbols.get(class_id)
            if (class_symbol is None or class_symbol.source_id != class_id
                    or class_symbol.kind != "class" or class_symbol.name != class_name
                    or class_symbol.file != filepath
                    or source_id not in class_symbol.methods.get(expected_name, [])):
                raise InvalidArtifact(details={"artifact": "source_index"})
            if symbol.parent_id != class_id:
                raise InvalidArtifact(details={"artifact": "source_index", "source_id": source_id})
        if (symbol.source_id != source_id or symbol.file != filepath
                or symbol.kind != expected_kind or symbol.name != expected_name):
            raise InvalidArtifact(details={"artifact": "source_index", "source_id": source_id})

    @staticmethod
    def _validated_range(symbol, actual_file_size: int) -> tuple[int, int]:
        span = symbol.span
        values = (
            span.start_line, span.start_column, span.end_line,
            span.end_column, span.start_byte, span.end_byte,
        )
        if (any(not isinstance(value, int) or isinstance(value, bool) for value in values)
                or span.start_line < 1
                or span.end_line < 1
                or any(value < 0 for value in (
                    span.start_column, span.end_column, span.start_byte, span.end_byte))
                or span.start_line > span.end_line
                or span.start_byte > span.end_byte
                or (span.start_line == span.end_line
                    and span.start_column > span.end_column)):
            raise InvalidArtifact(details={"artifact": "source_index", "source_id": symbol.source_id})
        start = span.start_byte - span.start_column
        if start < 0 or span.end_byte > actual_file_size:
            raise InvalidArtifact(details={"artifact": "source_index", "source_id": symbol.source_id})
        return start, span.end_byte - start

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        filepath = kwargs["FILEPATH"]
        try:
            structure_type = StructureType(kwargs["STRUCTURE-TYPE"])
        except ValueError as exc:
            raise InvalidToolArguments(details={"argument": "STRUCTURE-TYPE"}) from exc
        structure_path = kwargs["STRUCTURE-PATH"]
        accessor = SourceAccessor(analysis_context.source_index_path)
        index, source_file, resolved = accessor.resolve_file(filepath)
        try:
            actual_file_size = resolved.stat().st_size
        except OSError as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
        if actual_file_size != source_file.size_bytes:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath})
        ids = self._ids(index, source_file, filepath, structure_type, structure_path)
        if not ids:
            raise SourceObjectNotFound(details={
                "filepath": filepath, "structure_type": structure_type.value,
                "structure_path": structure_path,
            })
        source_id = ids[0]
        symbol = index.symbols.get(source_id)
        if symbol is None:
            raise InvalidArtifact(details={"artifact": "source_index", "source_id": source_id})
        self._validate_symbol(index, source_id, symbol, filepath, structure_type, structure_path)
        start, size = self._validated_range(symbol, actual_file_size)
        if size > RULES_CONFIG.max_extraction_structure_size:
            raise ExtractionLimitExceeded(details={
                "scope": "source_structure",
                "limit_bytes": RULES_CONFIG.max_extraction_structure_size,
                "actual_bytes": size,
            })
        raw = accessor.read_bytes(resolved, start, size, filepath)
        try:
            content = raw.decode(source_file.encoding)
        except (LookupError, UnicodeError) as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
        return {
            "filepath": filepath, "structure_type": structure_type.value,
            "structure_path": structure_path, "source_id": source_id, "content": content,
        }
