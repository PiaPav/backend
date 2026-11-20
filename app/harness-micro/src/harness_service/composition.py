"""Dependency-injected composition root for the harness service."""

from core_server.logic.core import Core
from core_server.logic.orchestrator import Orchestrator
from llm_connector.logic.connector import LLMConnector
from llm_connector.logic.prompts_loader import PromptsLoader
from llm_connector.logic.validator import Validator
from tools_engine.logic.engine import ToolsEngine
from tools_engine.tools.get_content import GetContent
from tools_engine.tools.get_structure import GetStructure

from harness_service.harness_handler import (
    Clock,
    EventPublisher,
    HarnessHandler,
    IdempotencyStore,
    InputMaterializer,
    Producer,
    ResultStore,
)
from harness_service.harness_runner import HarnessRunner


async def build_handler(
    *,
    llm_url: str,
    llm_api_key: str,
    materializer: InputMaterializer,
    result_store: ResultStore,
    idempotency: IdempotencyStore,
    publisher: EventPublisher,
    producer_version: str = "1",
    concurrency: int = 2,
    timeout_seconds: float = 600.0,
    clock: Clock | None = None,
) -> HarnessHandler:
    """Build and start the current Core/Orchestrator implementation.

    Transport and persistence dependencies remain outside this composition
    root so a broker adapter can be attached without changing application code.
    """
    connector = LLMConnector()
    tools = ToolsEngine()
    tools.register_tools([GetContent, GetStructure])
    orchestrator = Orchestrator(
        llm_connector=connector,
        tools_engine=tools,
        validator=Validator(PromptsLoader()),
    )
    core = Core(orchestrator=orchestrator)
    await core.start(url=llm_url, apikey=llm_api_key)

    return HarnessHandler(
        runner=HarnessRunner(
            core=core,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
        ),
        materializer=materializer,
        result_store=result_store,
        idempotency=idempotency,
        publisher=publisher,
        producer=Producer("harness-service", producer_version),
        clock=clock,
    )


__all__ = ["build_handler"]
