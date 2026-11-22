from dataclasses import dataclass
from pathlib import Path

from response_models.models import ToolData, ToolName
from tools_engine.interface.tool import AbstractTool
from tools_engine.tools.get_content import GetContent
from tools_engine.tools.get_code_range import GetCodeRange
from tools_engine.tools.get_structure import GetStructure
from tools_engine.tools.find_graph_nodes import FindGraphNodes
from tools_engine.tools.get_graph_node import GetGraphNode
from tools_engine.tools.get_metrics_item import GetMetricsItem


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: ToolName
    implementation: type[AbstractTool]
    schema_path: Path


_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
TOOL_REGISTRY = (
    ToolDefinition(ToolName.Get_Content, GetContent, _PROMPTS / "get-content.json"),
    ToolDefinition(ToolName.Get_Code_Range, GetCodeRange, _PROMPTS / "get-code-range.json"),
    ToolDefinition(ToolName.Get_Structure, GetStructure, _PROMPTS / "get-structure.json"),
    ToolDefinition(ToolName.Find_Graph_Nodes, FindGraphNodes, _PROMPTS / "find-graph-nodes.json"),
    ToolDefinition(ToolName.Get_Graph_Node, GetGraphNode, _PROMPTS / "get-graph-node.json"),
    ToolDefinition(ToolName.Get_Metrics_Item, GetMetricsItem, _PROMPTS / "get-metrics-item.json"),
)


def validate_registry(registry: tuple[ToolDefinition, ...]) -> None:
    names: set[ToolName] = set()
    for definition in registry:
        if definition.name in names:
            raise ValueError(f"Duplicate tool name: {definition.name}")
        names.add(definition.name)
        if definition.implementation.name != definition.name:
            raise ValueError(f"Implementation name mismatch: {definition.name}")
        schema = ToolData.model_validate_json(definition.schema_path.read_text(encoding="utf-8"))
        if schema.function.name != definition.name.value:
            raise ValueError(f"Schema name mismatch: {definition.name}")


validate_registry(TOOL_REGISTRY)
