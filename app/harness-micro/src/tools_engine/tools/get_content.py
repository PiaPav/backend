from response_models.models import ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.source import SourceAccessor
from tools_engine.interface.tool import AbstractTool, ExtractionLimitExceeded, InvalidArtifact
from tools_engine.models.analysis_context import AnalysisContext


class GetContent(AbstractTool):
    name = ToolName.Get_Content

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        filepath = kwargs["FILEPATH"]
        accessor = SourceAccessor(analysis_context.source_index_path)
        _, source_file, resolved = accessor.resolve_file(filepath)
        if source_file.size_bytes > RULES_CONFIG.max_extraction_file_size:
            raise ExtractionLimitExceeded(details={
                "scope": "source_file", "limit_bytes": RULES_CONFIG.max_extraction_file_size,
                "actual_bytes": source_file.size_bytes,
            })
        try:
            actual_size = resolved.stat().st_size
        except OSError as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
        if actual_size != source_file.size_bytes:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath})
        content = accessor.read_text(source_file, resolved)
        return {"filepath": filepath, "content": content}
