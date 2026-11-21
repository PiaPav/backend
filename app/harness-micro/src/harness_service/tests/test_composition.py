import asyncio
from unittest.mock import patch

import harness_service.composition as composition
from harness_service.harness_handler import HarnessHandler


class UnusedPort:
    pass


def test_composition_builds_core_around_current_orchestrator_api() -> None:
    created = {}

    class Connector:
        pass

    class Tools:
        def __init__(self, registry):
            created["tools"] = registry

    class Prompts:
        pass

    class Validator:
        def __init__(self, prompts, registry):
            created["prompts"] = prompts
            created["validator_registry"] = registry

    class Orchestrator:
        def __init__(self, *, llm_connector, tools_engine, validator):
            created["orchestrator_instance"] = self
            created["orchestrator_args"] = (llm_connector, tools_engine, validator)

    class Core:
        def __init__(self, orchestrator):
            created["orchestrator"] = orchestrator

        async def start(self, url, apikey):
            created["start"] = (url, apikey)

    with (
        patch.object(composition, "LLMConnector", Connector),
        patch.object(composition, "ToolsEngine", Tools),
        patch.object(composition, "PromptsLoader", Prompts),
        patch.object(composition, "Validator", Validator),
        patch.object(composition, "Orchestrator", Orchestrator),
        patch.object(composition, "Core", Core),
    ):
        result = asyncio.run(composition.build_handler(
            llm_url="https://llm.invalid",
            llm_api_key="key",
            materializer=UnusedPort(),
            result_store=UnusedPort(),
            idempotency=UnusedPort(),
            publisher=UnusedPort(),
        ))

    assert isinstance(result, HarnessHandler)
    assert created["orchestrator"] is created["orchestrator_instance"]
    assert created["start"] == ("https://llm.invalid", "key")
    assert created["tools"] is composition.TOOL_REGISTRY
    assert created["validator_registry"] is composition.TOOL_REGISTRY
