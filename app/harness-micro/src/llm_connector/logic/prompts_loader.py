from pathlib import Path

from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from tools_engine.models.tool_models import ToolName
from utils.config import CONFIG


class PromptsLoader(PromptsLoaderInterface):
    dirpath = Path(__file__).parent.parent.parent / Path(CONFIG.llm.prompts_dir)

    def load_prompt(self) -> str:
        """Загрузить промт для нейронки"""
        filepath = self.dirpath / "PROMPT.md"
        return filepath.read_text(encoding="utf-8")

    def load_commands(self) -> str:
        """Загрузить команды, доступные нейронке"""
        filepath = self.dirpath / "TOOLS.md"
        return filepath.read_text(encoding="utf-8")

    def load_tool(self, tool_name: ToolName) -> str:
        """Загружает промт для конкретной тулы"""
        filepath = self.dirpath / f"{tool_name.name.upper()}.md"
        return filepath.read_text(encoding="utf-8")
