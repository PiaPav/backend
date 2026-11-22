import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llm_connector.logic.validator import Validator
from core_server.logic.orchestrator import Orchestrator
from response_models.models import FinishReasonType, FunctionCall, ToolCall, ToolName
from tools_engine.interface.tool import ToolError
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolResult
from tools_engine.registry import TOOL_REGISTRY, ToolDefinition, validate_registry
from utils.logger.custom_logger import DBHandler
from utils.logger.db.logs_orm import LogData, _extract_llm_usage


class Prompts:
    def load_prompt(self):
        return "prompt"


def context(index: Path) -> AnalysisContext:
    return AnalysisContext(1, {}, {}, index, "a" * 64, "b" * 64)


def write_source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "module.py"
    content = "class Box:\n    def size(self):\n        return 1\n"
    raw = content.encode()
    source.write_bytes(raw)
    method_start = raw.index(b"    def")
    index = {
        "schema_version": 1,
        "project": {"root": str(tmp_path), "fingerprint": "x", "file_count": 1},
        "files": {"module.py": {
            "relative_path": "module.py", "name": "module.py", "module": "module",
            "sha256": "x", "size_bytes": len(raw), "encoding": "utf-8",
            "classes": {"Box": ["class"]}, "functions": {}, "constants": {},
        }},
        "symbols": {
            "class": {"source_id": "class", "kind": "class", "name": "Box",
                      "qualified_name": "Box", "file": "module.py", "parent_id": None,
                      "span": {"start_line": 1, "start_column": 0, "end_line": 3,
                               "end_column": 16, "start_byte": 0, "end_byte": len(raw)},
                      "methods": {"size": ["method"]}},
            "method": {"source_id": "method", "kind": "method", "name": "size",
                       "qualified_name": "Box.size", "file": "module.py", "parent_id": "class",
                       "span": {"start_line": 2, "start_column": 4, "end_line": 3,
                                "end_column": 16, "start_byte": method_start + 4,
                                "end_byte": len(raw)}},
        },
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return index_path, content


def run(engine, ctx, name, arguments):
    return asyncio.run(engine.entry_tool(ctx, name, json.dumps(arguments)))


class ToolFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_registry_and_validator_use_same_schemas(self) -> None:
        validate_registry(TOOL_REGISTRY)
        models = Validator(Prompts(), TOOL_REGISTRY).load_tools_models()
        self.assertEqual([m.function.name for m in models], [i.name for i in TOOL_REGISTRY])

    def test_registry_rejects_duplicate_and_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_registry((TOOL_REGISTRY[0], TOOL_REGISTRY[0]))
        bad = ToolDefinition(ToolName.Get_Structure, TOOL_REGISTRY[0].implementation, TOOL_REGISTRY[1].schema_path)
        with self.assertRaisesRegex(ValueError, "Implementation"):
            validate_registry((bad,))

    def test_tool_result_contract_compact_utf8_and_validator_passthrough(self) -> None:
        result = ToolResult.failure(ToolError("ошибка", {"x": "я"}, False, code="sample"))
        content = result.to_json()
        decoded = json.loads(content)
        self.assertEqual(set(decoded), {"status", "profile_id", "result", "completeness", "diagnostics"})
        self.assertNotIn(": ", content)
        self.assertEqual(result.utf8_size(), len(content.encode("utf-8")))
        call = ToolCall(id="1", function=FunctionCall(name="GET-CONTENT", arguments="{}"))
        self.assertEqual(Validator(Prompts()).create_tool_message(call, content).content, content)

    def test_runtime_schema_validation_before_execute(self) -> None:
        engine = ToolsEngine()
        for arguments in ({}, {"FILEPATH": "x", "EXTRA": 1}, {"FILEPATH": 1}):
            with self.subTest(arguments=arguments):
                result = run(engine, context(self.tmp_path / "missing"), "GET-CONTENT", arguments)
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")

    def test_malformed_non_object_unknown_and_enum(self) -> None:
        engine = ToolsEngine()
        cases = [("NOPE", "{}", "unknown_tool"), ("GET-CONTENT", "[]", "invalid_tool_arguments"),
                 ("GET-CONTENT", "{", "invalid_tool_arguments"),
                 ("GET-STRUCTURE", json.dumps({"FILEPATH": "x", "STRUCTURE-TYPE": "BAD", "STRUCTURE-PATH": "x"}), "invalid_tool_arguments")]
        for name, arguments, code in cases:
            result = asyncio.run(engine.entry_tool(context(self.tmp_path / "missing"), name, arguments))
            self.assertEqual(result.diagnostics[0].code, code)

    def test_get_content_and_structure_success(self) -> None:
        index, content = write_source(self.tmp_path)
        engine = ToolsEngine()
        file_result = run(engine, context(index), "GET-CONTENT", {"FILEPATH": "module.py"})
        structure = run(engine, context(index), "GET-STRUCTURE", {
            "FILEPATH": "module.py", "STRUCTURE-TYPE": "METHOD", "STRUCTURE-PATH": "Box.size"})
        self.assertEqual(file_result.result, {"filepath": "module.py", "content": content}, file_result.to_json())
        self.assertEqual(structure.result["source_id"], "method")
        self.assertIn("def size", structure.result["content"])
        self.assertEqual((structure.completeness.total, structure.completeness.returned), (1, 1))

    def test_indexed_non_python_file_is_invalid_artifact(self) -> None:
        index, _ = write_source(self.tmp_path)
        data = json.loads(index.read_text(encoding="utf-8"))
        source = self.tmp_path / "notes.txt"
        source.write_text("not source", encoding="utf-8")
        data["files"]["notes.txt"] = {
            "relative_path": "notes.txt", "name": "notes.txt", "module": "notes",
            "sha256": "x", "size_bytes": source.stat().st_size, "encoding": "utf-8",
            "classes": {}, "functions": {}, "constants": {},
        }
        index.write_text(json.dumps(data), encoding="utf-8")
        result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "notes.txt"})
        self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
        self.assertNotIn(str(self.tmp_path), result.to_json())

    def test_unsafe_paths_do_not_leak_absolute_path(self) -> None:
        index, _ = write_source(self.tmp_path)
        for filepath in ("../module.py", "/module.py", "C:/module.py", "C:\\module.py", "//server/share", "dir\\module.py"):
            result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": filepath})
            self.assertEqual(result.diagnostics[0].code, "source_object_not_found")
            self.assertNotIn(str(self.tmp_path), result.to_json())

    def test_valid_missing_source_index_path_is_retryable_and_does_not_leak_path(self) -> None:
        index, _ = write_source(self.tmp_path)

        result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "missing.py"})

        self.assertEqual(result.diagnostics[0].code, "source_object_not_found")
        self.assertTrue(result.diagnostics[0].retryable)
        self.assertEqual(result.diagnostics[0].details, {"filepath": "missing.py"})

    def test_missing_structure_and_bad_method_format(self) -> None:
        index, _ = write_source(self.tmp_path)
        engine = ToolsEngine()
        missing = run(engine, context(index), "GET-STRUCTURE", {"FILEPATH": "module.py", "STRUCTURE-TYPE": "CLASS", "STRUCTURE-PATH": "Missing"})
        malformed = run(engine, context(index), "GET-STRUCTURE", {"FILEPATH": "module.py", "STRUCTURE-TYPE": "METHOD", "STRUCTURE-PATH": "bad"})
        self.assertEqual(missing.diagnostics[0].code, "source_object_not_found", missing.to_json())
        self.assertEqual(malformed.diagnostics[0].code, "invalid_tool_arguments")

    def test_corrupt_index_and_declared_size_are_invalid_artifact(self) -> None:
        index = self.tmp_path / "index.json"
        index.write_text("not json", encoding="utf-8")
        result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "module.py"})
        self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
        index, _ = write_source(self.tmp_path)
        data = json.loads(index.read_text(encoding="utf-8")); data["files"]["module.py"]["size_bytes"] += 1
        index.write_text(json.dumps(data), encoding="utf-8")
        result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "module.py"})
        self.assertEqual(result.diagnostics[0].code, "invalid_artifact")

    def test_full_result_limit_counts_utf8_bytes_without_truncation(self) -> None:
        index, _ = write_source(self.tmp_path)
        source = self.tmp_path / "module.py"
        content = source.read_text(encoding="utf-8") + "#" * 2000
        source.write_bytes(content.encode("utf-8"))
        data = json.loads(index.read_text(encoding="utf-8"))
        data["files"]["module.py"]["size_bytes"] = len(content.encode("utf-8"))
        data["symbols"]["class"]["span"]["end_byte"] = len(content.encode("utf-8"))
        data["symbols"]["method"]["span"]["end_byte"] = len(content.encode("utf-8"))
        index.write_text(json.dumps(data), encoding="utf-8")
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 500):
            result = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "module.py"})
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.code, "extraction_limit_exceeded", result.to_json())
        self.assertEqual(diagnostic.details["scope"], "serialized_tool_result")
        self.assertGreater(diagnostic.details["actual_bytes"], diagnostic.details["limit_bytes"])
        self.assertNotIn("#" * 100, result.to_json())

        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 1):
            compact = run(ToolsEngine(), context(index), "GET-CONTENT", {"FILEPATH": "module.py"})
        self.assertEqual(compact.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertEqual(compact.diagnostics[0].details, {})
        self.assertNotIn("#" * 100, compact.to_json())

    def test_result_limit_applies_to_errors_and_pathological_limit_is_safe(self) -> None:
        untrusted_name = "UNKNOWN-" + "секрет" * 1000
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 500):
            result = asyncio.run(ToolsEngine().entry_tool(
                context(self.tmp_path / "missing"), untrusted_name, "{}"))
        self.assertEqual(result.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertEqual(result.diagnostics[0].details["scope"], "serialized_tool_result")
        self.assertNotIn("секрет", result.to_json())

        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 1):
            compact = asyncio.run(ToolsEngine().entry_tool(
                context(self.tmp_path / "missing"), untrusted_name, "{}"))
        self.assertEqual(compact.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertEqual(compact.diagnostics[0].details, {})
        self.assertNotIn("секрет", compact.to_json())

    def test_structure_rejects_inconsistent_symbol_index(self) -> None:
        mutations = {
            "wrong kind": lambda data: data["symbols"]["method"].update(kind="function"),
            "wrong source id": lambda data: data["symbols"]["method"].update(source_id="other"),
            "wrong name": lambda data: data["symbols"]["method"].update(name="other"),
            "wrong file": lambda data: data["symbols"]["method"].update(file="other.py"),
            "wrong parent": lambda data: data["symbols"]["method"].update(parent_id="other"),
            "class source id mismatch": lambda data: data["symbols"]["class"].update(source_id="other"),
            "class kind mismatch": lambda data: data["symbols"]["class"].update(kind="function"),
            "class name mismatch": lambda data: data["symbols"]["class"].update(name="Other"),
            "class file mismatch": lambda data: data["symbols"]["class"].update(file="other.py"),
            "member relation mismatch": lambda data: data["symbols"]["class"]["methods"].update(size=["other"]),
            "boolean span": lambda data: data["symbols"]["method"]["span"].update(end_byte=True),
            "string span": lambda data: data["symbols"]["method"]["span"].update(start_line="2"),
            "zero start line": lambda data: data["symbols"]["method"]["span"].update(start_line=0),
            "zero end line": lambda data: data["symbols"]["method"]["span"].update(end_line=0),
            "negative span": lambda data: data["symbols"]["method"]["span"].update(start_column=-1),
            "reversed byte span": lambda data: data["symbols"]["method"]["span"].update(start_byte=999),
            "reversed line span": lambda data: data["symbols"]["method"]["span"].update(start_line=4),
            "reversed column span": lambda data: data["symbols"]["method"]["span"].update(
                start_line=3, end_line=3, start_column=17, end_column=16),
            "start before file": lambda data: data["symbols"]["method"]["span"].update(
                start_byte=1, start_column=4),
            "end beyond file": lambda data: data["symbols"]["method"]["span"].update(end_byte=999),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                index, _ = write_source(self.tmp_path)
                data = json.loads(index.read_text(encoding="utf-8"))
                mutate(data)
                index.write_text(json.dumps(data), encoding="utf-8")
                result = run(ToolsEngine(), context(index), "GET-STRUCTURE", {
                    "FILEPATH": "module.py", "STRUCTURE-TYPE": "METHOD",
                    "STRUCTURE-PATH": "Box.size",
                })
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact", result.to_json())

    def test_tool_log_metadata_excludes_content_and_arguments(self) -> None:
        result = ToolResult.success({"content": "secret source"}, profile_id="profile")
        metadata = Orchestrator._tool_log_metadata("GET-CONTENT", result)
        self.assertIsInstance(metadata, str)
        payload = json.loads(metadata)
        self.assertEqual(payload, {
            "tool_name": "GET-CONTENT",
            "status": "success",
            "profile_id": "profile",
            "completeness": {"returned": 1, "total": 1, "truncated": False},
            "serialized_utf8_size": result.utf8_size(),
        })
        self.assertEqual(metadata, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        self.assertNotIn("secret source", metadata)
        self.assertNotIn("arguments", metadata)

    def test_answer_log_metadata_excludes_content_and_arguments(self) -> None:
        answer = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=FinishReasonType.tool_calls,
            message=SimpleNamespace(
                content="content marker",
                tool_calls=[ToolCall(
                    id="1",
                    function=FunctionCall(
                        name="GET-CONTENT", arguments='{"marker":"arguments marker"}',
                    ),
                )],
            ),
        )])
        metadata = Orchestrator._answer_log_metadata(answer)
        self.assertIsInstance(metadata, str)
        payload = json.loads(metadata)
        self.assertEqual(payload, {
            "finish_reason": FinishReasonType.tool_calls.value,
            "tool_call_count": 1,
            "tool_names": ["GET-CONTENT"],
        })
        self.assertEqual(metadata, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        self.assertNotIn("content marker", metadata)
        self.assertNotIn("arguments marker", metadata)

    def test_metadata_is_accepted_by_log_data_and_db_handler_without_database(self) -> None:
        description = Orchestrator._answer_log_metadata(SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content="content marker", tool_calls=[]),
        )]))
        expected = LogData(unique_id=7, type="INFO", event="answer", description=description)
        handler = DBHandler()
        handler.worker_task = SimpleNamespace(done=lambda: False)
        record = logging.LogRecord(
            "test", 20, __file__, 1,
            json.dumps({
                "unique_id": 7,
                "event": "answer",
                "description": description,
            }), (), None,
        )

        handler.emit(record)

        parsed = handler.queue.get_nowait()
        self.assertIsInstance(parsed, LogData)
        self.assertEqual(parsed, expected)
        self.assertIsInstance(parsed.description, str)

    def test_extract_llm_usage_reads_safe_metadata_finish_reason(self) -> None:
        description = json.dumps({
            "finish_reason": "tool_calls",
            "tool_call_count": 1,
            "tool_names": ["GET-CONTENT"],
        })

        usage = _extract_llm_usage(description)

        self.assertEqual(usage["finish_reason"], "tool_calls")

    def test_extract_llm_usage_falls_back_to_legacy_choice_finish_reason(self) -> None:
        usage = _extract_llm_usage(json.dumps({
            "finish_reason": None,
            "choices": [{"finish_reason": "length"}],
        }))

        self.assertEqual(usage["finish_reason"], "length")


if __name__ == "__main__":
    unittest.main()
