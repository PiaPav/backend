from core_server.logic.core import Core
from llm_connector.logic.connector import LLMConnector
from llm_connector.logic.prompts_loader import PromptsLoader
from llm_connector.logic.validator import Validator
from tools_engine.logic.engine import ToolsEngine
from tools_engine.tools.get_content import GetContent
from tools_engine.tools.get_structure import GetStructure

from harness_service.harness_handler import HarnessHandler, InputMaterializer, ResultStore, IdempotencyStore, \
    EventPublisher
from harness_service.harness_runner import HarnessRunner


async def build_handler(
    *,
    llm_url: str,
    llm_api_key: str,
    materializer: InputMaterializer,
    result_store: ResultStore,
    idempotency: IdempotencyStore,
    publisher: EventPublisher,
) -> HarnessHandler:
    connector = LLMConnector()

    tools = ToolsEngine()
    tools.register_tools([GetContent, GetStructure])

    validator = Validator(PromptsLoader())

    core = Core(
        llm_connector=connector,
        tools_engine=tools,
        validator=validator,
    )

    # Инициализация LLM-клиента и ToolsEngine.
    await core.start(
        url=llm_url,
        apikey=llm_api_key,
    )

    runner = HarnessRunner(
        core=core,
        concurrency=2,
        timeout_seconds=600,
    )

    return HarnessHandler(
        runner=runner,
        materializer=materializer,
        result_store=result_store,
        idempotency=idempotency,
        publisher=publisher,
    )