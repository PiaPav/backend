import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from core_server.logic.core import Core
from core_server.logic.orchestrator import Orchestrator
from harness_service.harness_handler import (
    ArtifactDescriptor,
    Claim,
    ClaimDisposition,
    DeliveryContext,
    DeliveryDecision,
    HarnessHandler,
    MaterializedInputs,
    Producer,
)
from harness_service.harness_runner import HarnessRunner
from llm_connector.logic.validator import Validator
from response_models.models import (
    FinishReasonType,
    FunctionCall,
    LLMAnalysis,
    ToolCall,
)
from tools_engine.logic.engine import ToolsEngine
from tools_engine.logic import engine as engine_module
from tools_engine.registry import TOOL_REGISTRY


HASH = "a" * 64
PROJECT_HASH = "b" * 64
FINAL_ANALYSIS = json.dumps({
    "issues": [],
    "strengths": [{
        "title": "Verified implementation",
        "description": "The implementation was inspected through graph, source, and metrics tools.",
        "location": "pkg/module.py:1",
        "evidence": "The graph node and source range agree.",
        "recommendation": "Keep the focused implementation.",
    }],
})


def _answer(reason, *, calls=None, content=None):
    choice = SimpleNamespace(
        finish_reason=FinishReasonType(reason),
        message=SimpleNamespace(tool_calls=calls, content=content),
    )
    return SimpleNamespace(choices=[choice], model_dump=lambda: {})


def _call(identifier, name, arguments):
    return ToolCall(
        id=identifier,
        function=FunctionCall(name=name, arguments=json.dumps(arguments)),
    )


class PromptLoader:
    def load_prompt(self):
        return "Use tools to verify the supplied overview before producing the report."


class ScriptedSession:
    def __init__(self, exchanges):
        self._exchanges = list(exchanges)
        self.start_messages = None
        self.tool_messages = []
        self.final_messages = []

    async def send_start(self, *, messages, tools):
        self.start_messages = messages
        assert {tool.function.name for tool in tools} == {
            definition.name.value for definition in TOOL_REGISTRY
        }
        return self._exchanges.pop(0)(None)

    async def send(self, messages):
        self.tool_messages.append(messages)
        return self._exchanges.pop(0)(messages)

    async def final_send(self, messages):
        self.final_messages.append(messages)
        return _answer("stop", content=FINAL_ANALYSIS)

    async def retry_send(self):
        raise AssertionError("provider retry was not expected")


class ScriptedConnector:
    def __init__(self, session):
        self.session = session
        self.created = 0
        self.closed = 0

    async def create_session(self, unique_id):
        self.created += 1
        return self.session

    async def close_session(self, unique_id):
        self.closed += 1


class Materializer:
    def __init__(self, fixtures, order):
        self.fixtures = fixtures
        self.order = order

    @contextmanager
    def materialize(self, **descriptors):
        self.order.append("materialize")
        assert set(descriptors["graph_profiles"].artifacts) == {
            "canonical.full", "aggregate.overview"
        }
        assert set(descriptors["metrics_profiles"].artifacts) == {
            "metrics.full", "metrics.overview"
        }
        yield MaterializedInputs(
            self.fixtures["graphs"], self.fixtures["metrics"],
            self.fixtures["source_index"], HASH, PROJECT_HASH,
        )


class ResultStore:
    def __init__(self, order):
        self.order = order
        self.content = None

    async def save(self, **values):
        self.order.append("save")
        self.content = values["content"]
        LLMAnalysis.model_validate_json(self.content)
        return ArtifactDescriptor("memory://result.json", HASH, len(self.content), 1)


class IdempotencyStore:
    def __init__(self, order):
        self.order = order
        self.output = None

    async def claim(self, **values):
        return Claim(ClaimDisposition.NEW, "claim-token")

    async def save_output(self, **values):
        self.order.append("persist")
        self.output = values["output_event"]

    async def mark_published(self, **values):
        self.order.append("published")


class Publisher:
    def __init__(self, order):
        self.order = order
        self.events = []

    async def publish(self, event):
        self.order.append("publish")
        self.events.append(event)


class FixedClock:
    def now(self):
        return datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _fixtures(tmp_path: Path):
    source = tmp_path / "pkg" / "module.py"
    source.parent.mkdir()
    source.write_text("def target():\n    return 42\n", encoding="utf-8")
    canonical = {
        "schema_version": 1,
        "parser_semantics_version": 7,
        "nodes": [{
            "id": "function:target", "kind": "function",
            "qualified_name": "pkg.module.target", "path": "pkg/module.py",
            "location": {"path": "pkg/module.py", "line": 1, "column": 0},
        }],
        "edges": [], "callsites": [], "import_references": [], "type_references": [],
    }
    graph_overview = {"profile": "aggregate.overview", "summary": "one target function"}
    metrics_full = {"complexity": {"target": 7}, "large": "я" * 4000}
    metrics_overview = {"profile": "metrics.overview", "summary": {"functions": 1}}
    index = {
        "schema_version": 1,
        "project": {"root": str(tmp_path), "fingerprint": PROJECT_HASH, "file_count": 1},
        "files": {"pkg/module.py": {
            "relative_path": "pkg/module.py", "name": "module.py", "module": "pkg.module",
            "sha256": HASH, "size_bytes": len(source.read_bytes()), "encoding": "utf-8",
            "classes": {}, "functions": {}, "constants": {},
        }},
        "symbols": {}, "lookup": {}, "files_by_name": {"module.py": ["pkg/module.py"]},
    }
    return {
        "graphs": {
            "canonical.full": _write_json(tmp_path / "canonical.json", canonical),
            "aggregate.overview": _write_json(tmp_path / "graph-overview.json", graph_overview),
        },
        "metrics": {
            "metrics.full": _write_json(tmp_path / "metrics.json", metrics_full),
            "metrics.overview": _write_json(tmp_path / "metrics-overview.json", metrics_overview),
        },
        "source_index": _write_json(tmp_path / "source-index.json", index),
    }


def _artifact(uri):
    return {"uri": uri, "sha256": HASH, "size_bytes": 1, "schema_version": 1}


def _wire():
    return {
        "event_id": "stage5-event", "event_type": "harness.start.v1", "schema_version": 1,
        "occurred_at": "2026-11-23T10:00:00Z", "correlation_id": "analysis-5",
        "causation_id": "metrics-event", "tenant_id": "tenant-1",
        "producer": {"service": "analysis-coordinator", "version": "1"},
        "payload": {
            "source_uri": "memory://source",
            "graph_profiles": {
                "parser_semantics_version": 7, "graph_fingerprint": HASH,
                "artifacts": {
                    "canonical.full": _artifact("memory://canonical"),
                    "aggregate.overview": _artifact("memory://graph-overview"),
                },
            },
            "metrics_profiles": {
                "metrics_semantics_version": 4, "graph_fingerprint": HASH,
                "artifacts": {
                    "metrics.full": _artifact("memory://metrics"),
                    "metrics.overview": _artifact("memory://metrics-overview"),
                },
            },
            "source_index": {
                **_artifact("memory://source-index"), "project_fingerprint": PROJECT_HASH,
            },
        },
    }


def _application(tmp_path, session, *, max_tool_calls):
    order = []
    connector = ScriptedConnector(session)
    orchestrator = Orchestrator(
        connector, ToolsEngine(TOOL_REGISTRY), Validator(PromptLoader(), TOOL_REGISTRY),
        max_tool_calls=max_tool_calls, max_iterations=8,
        max_start_context_size=100_000, max_provider_retries=0,
    )
    store = ResultStore(order)
    state = IdempotencyStore(order)
    publisher = Publisher(order)
    handler = HarnessHandler(
        runner=HarnessRunner(Core(orchestrator)),
        materializer=Materializer(_fixtures(tmp_path), order), result_store=store,
        idempotency=state, publisher=publisher,
        producer=Producer("harness-service", "test"), clock=FixedClock(),
    )
    return handler, connector, store, state, publisher, order


def _tool_payload(messages, index=0):
    return json.loads(messages[index].content)


def test_minimal_profiles_complete_real_tool_journey(tmp_path: Path):
    names = []

    def first(_):
        names.append("FIND-GRAPH-NODES")
        return _answer("tool_calls", calls=[_call(
            "find", "FIND-GRAPH-NODES", {"QUERY": "target"}
        )])

    def second(messages):
        payload = _tool_payload(messages)
        assert payload["result"]["nodes"][0]["id"] == "function:target"
        names.append("GET-GRAPH-SUBGRAPH")
        return _answer("tool_calls", calls=[_call("subgraph", "GET-GRAPH-SUBGRAPH", {
            "PROFILE-ID": "canonical.full", "NODE-ID": "function:target", "DEPTH": 0,
        })])

    def third(messages):
        assert _tool_payload(messages)["result"]["root_node_id"] == "function:target"
        names.append("GET-CODE-RANGE")
        return _answer("tool_calls", calls=[_call("source", "GET-CODE-RANGE", {
            "FILEPATH": "pkg/module.py", "START-LINE": 1, "END-LINE": 2,
        })])

    def fourth(messages):
        lines = _tool_payload(messages)["result"]["lines"]
        assert "def target" in lines[0]["content"]
        names.append("GET-METRICS-ITEM")
        return _answer("tool_calls", calls=[_call("metric", "GET-METRICS-ITEM", {
            "PROFILE-ID": "metrics.full", "METRIC-PATH": "/complexity/target",
        })])

    session = ScriptedSession([first, second, third, fourth])
    application, connector, store, state, publisher, order = _application(
        tmp_path, session, max_tool_calls=4
    )

    decision = asyncio.run(application.handle(_wire(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.ACK
    assert names == ["FIND-GRAPH-NODES", "GET-GRAPH-SUBGRAPH",
                     "GET-CODE-RANGE", "GET-METRICS-ITEM"]
    assert _tool_payload(session.final_messages[0])["result"] == 7
    start_context = "\n".join(message.content or "" for message in session.start_messages)
    assert "one target function" in start_context
    assert '"functions": 1' in start_context
    assert "function:target" not in start_context
    assert '"target": 7' not in start_context
    assert connector.created == connector.closed == 1
    assert len(session.final_messages) == 1
    assert LLMAnalysis.model_validate_json(store.content).strengths
    assert order == ["materialize", "save", "persist", "publish", "published"]
    assert state.output == publisher.events[0]


def test_errors_budget_accumulates_and_stops_batch(tmp_path: Path, monkeypatch):
    executed_calls = []
    original_entry_tool = ToolsEngine.entry_tool

    async def recording_entry_tool(self, analysis_context, name, arguments):
        executed_calls.append(name)
        return await original_entry_tool(self, analysis_context, name, arguments)

    def first(_):
        return _answer("tool_calls", calls=[_call(
            "missing", "GET-GRAPH", {"PROFILE-ID": "calls.topology"}
        )])

    def second(messages):
        diagnostic = _tool_payload(messages)["diagnostics"][0]
        assert diagnostic["code"] == "profile_not_found"
        assert diagnostic["details"] == {"profile_id": "calls.topology"}
        return _answer("tool_calls", calls=[
            _call("large", "GET-METRICS-ITEM", {
                "PROFILE-ID": "metrics.full", "METRIC-PATH": "/large",
            }),
            _call("never", "FIND-GRAPH-NODES", {"QUERY": "target"}),
        ])

    session = ScriptedSession([first, second])
    application, connector, store, _, _, order = _application(
        tmp_path, session, max_tool_calls=2
    )
    monkeypatch.setattr(ToolsEngine, "entry_tool", recording_entry_tool)
    monkeypatch.setattr(
        engine_module,
        "RULES_CONFIG",
        replace(engine_module.RULES_CONFIG, max_tool_result_size=500),
    )

    decision = asyncio.run(application.handle(_wire(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.ACK
    final_messages = session.final_messages[0]
    extraction = _tool_payload(final_messages, 0)["diagnostics"][0]
    limited = _tool_payload(final_messages, 1)["diagnostics"][0]
    assert extraction["code"] == "extraction_limit_exceeded"
    assert extraction["details"]["scope"] == "serialized_tool_result"
    assert extraction["details"]["limit_bytes"] == 500
    assert limited == {
        "code": "tool_call_limit_exceeded",
        "details": {"limit": 2, "used": 2},
        "message": "Исчерпан лимит использования инструментов. Использовано 2 из 2.",
        "retryable": False,
    }
    assert len(session.tool_messages) == 1
    assert len(session.final_messages) == 1
    assert executed_calls == ["GET-GRAPH", "GET-METRICS-ITEM"]
    assert connector.closed == 1
    assert LLMAnalysis.model_validate_json(store.content).strengths
    assert order == ["materialize", "save", "persist", "publish", "published"]
