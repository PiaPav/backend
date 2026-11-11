from pathlib import Path

from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from utils.config import CONFIG


class PromptsLoader(PromptsLoaderInterface):
    dirpath = Path(__file__).parent.parent.parent / Path(CONFIG.llm.prompts_dir)

    def load_prompt(self) -> str:
        """Загрузить промт для нейронки"""
        filepath = self.dirpath / "PROMPT.md"
        return filepath.read_text(encoding="utf-8")
