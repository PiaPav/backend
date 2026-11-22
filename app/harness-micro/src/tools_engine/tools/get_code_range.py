from response_models.models import ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.source import SourceAccessor
from tools_engine.interface.tool import AbstractTool, InvalidToolArguments, SourceObjectNotFound
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import Completeness, ToolOutput


class GetCodeRange(AbstractTool):
    name = ToolName.Get_Code_Range

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        filepath = kwargs["FILEPATH"]
        start = kwargs["START-LINE"]
        end = kwargs["END-LINE"]
        if start > end:
            raise InvalidToolArguments("Начальная строка должна быть не больше конечной")
        if not filepath.endswith(".py"):
            raise SourceObjectNotFound(details={"filepath": filepath})

        accessor = SourceAccessor(analysis_context.source_index_path)
        _, source_file, resolved = accessor.resolve_file(filepath)
        lines, total_lines = accessor.read_line_range(
            source_file, resolved, start, end, RULES_CONFIG.max_code_range_lines
        )
        if end > total_lines:
            raise InvalidToolArguments(
                "Запрошенный диапазон выходит за конец файла",
                {"physical_lines": total_lines},
            )

        requested = end - start + 1
        returned = len(lines)
        returned_range = (
            {"start_line": start, "end_line": lines[-1]["line_number"]}
            if lines else None
        )
        return ToolOutput(
            result={
                "filepath": filepath,
                "requested_range": {"start_line": start, "end_line": end},
                "returned_range": returned_range,
                "lines": lines,
            },
            completeness=Completeness(returned < requested, requested, returned),
        )
