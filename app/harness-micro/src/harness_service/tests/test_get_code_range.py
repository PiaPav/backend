import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from response_models.models import ToolName
from rules.rules_config import _positive_int
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY


class GetCodeRangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_context(self, raw="one\n  two\nтри".encode("utf-8"), *, encoding="utf-8", size=None):
        source = self.root / "module.py"
        source.write_bytes(raw)
        index = {
            "schema_version": 1,
            "project": {"root": str(self.root), "fingerprint": "x", "file_count": 1},
            "files": {"module.py": {
                "relative_path": "module.py", "name": "module.py", "module": "module",
                "sha256": "x", "size_bytes": len(raw) if size is None else size,
                "encoding": encoding, "classes": {}, "functions": {}, "constants": {},
            }},
            "symbols": {}, "lookup": {}, "files_by_name": {"module.py": ["module.py"]},
        }
        index_path = self.root / "index.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        return AnalysisContext(1, {}, {}, index_path, "a" * 64, "b" * 64)

    @staticmethod
    def call(context, arguments):
        return asyncio.run(ToolsEngine().entry_tool(
            context, "GET-CODE-RANGE", json.dumps(arguments)
        ))

    def test_success_preserves_spaces_unicode_and_has_inclusive_ranges(self):
        result = self.call(self.make_context(), {
            "FILEPATH": "module.py", "START-LINE": 2, "END-LINE": 3,
        })
        self.assertEqual(result.result["lines"], [
            {"line_number": 2, "content": "  two"},
            {"line_number": 3, "content": "три"},
        ])
        self.assertEqual(result.result["requested_range"], {"start_line": 2, "end_line": 3})
        self.assertEqual(result.result["returned_range"], {"start_line": 2, "end_line": 3})
        self.assertEqual((result.completeness.total, result.completeness.returned), (2, 2))
        self.assertFalse(result.completeness.truncated)

    def test_single_empty_line_and_trailing_newline(self):
        context = self.make_context(b"first\n\nlast\n")
        empty = self.call(context, {"FILEPATH": "module.py", "START-LINE": 2, "END-LINE": 2})
        last = self.call(context, {"FILEPATH": "module.py", "START-LINE": 3, "END-LINE": 3})
        beyond = self.call(context, {"FILEPATH": "module.py", "START-LINE": 4, "END-LINE": 4})
        self.assertEqual(empty.result["lines"][0]["content"], "")
        self.assertEqual(last.result["lines"][0]["content"], "last")
        self.assertEqual(beyond.diagnostics[0].code, "invalid_tool_arguments")

    def test_truncates_to_configured_line_prefix(self):
        with patch("tools_engine.tools.get_code_range.RULES_CONFIG.max_code_range_lines", 2):
            result = self.call(self.make_context(b"1\n2\n3\n4"), {
                "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 4,
            })
        self.assertEqual([line["line_number"] for line in result.result["lines"]], [1, 2])
        self.assertEqual(result.result["returned_range"], {"start_line": 1, "end_line": 2})
        self.assertEqual((result.completeness.total, result.completeness.returned), (4, 2))
        self.assertTrue(result.completeness.truncated)

    def test_invalid_runtime_line_limits_are_invalid_artifacts(self):
        for limit in (0, -1, True, "2"):
            with self.subTest(limit=limit):
                with patch("tools_engine.tools.get_code_range.RULES_CONFIG.max_code_range_lines", limit):
                    result = self.call(self.make_context(), {
                        "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
                    })
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
                self.assertFalse(result.diagnostics[0].retryable)
                self.assertIsNone(result.result)

    def test_config_line_limit_requires_positive_exact_integer(self):
        for value in (0, -1, True, "2", 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "max_code_range_lines"):
                    _positive_int(value, "max_code_range_lines")
        self.assertEqual(_positive_int(2, "max_code_range_lines"), 2)

    def test_path_replacement_between_resolution_and_open_is_invalid_artifact(self):
        context = self.make_context(b"safe\n")
        source = self.root / "module.py"
        replacement = self.root / "replacement.py"
        replacement.write_bytes(b"evil\n")
        real_open = os.open
        replaced = False

        def replacing_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if not replaced and Path(path) == source:
                replaced = True
                os.replace(replacement, source)
            return real_open(path, flags, *args, **kwargs)

        with patch("tools_engine.accessors.source.os.open", side_effect=replacing_open):
            result = self.call(context, {
                "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
            })

        self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
        self.assertIsNone(result.result)
        self.assertNotIn("evil", result.to_json())
        self.assertNotIn(str(self.root), result.to_json())

    def test_ignores_full_file_extraction_limit_but_obeys_result_byte_limit(self):
        context = self.make_context(b"x" * 1000)
        with patch("tools_engine.tools.get_content.RULES_CONFIG.max_extraction_file_size", 1):
            success = self.call(context, {
                "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
            })
        self.assertEqual(success.status, "success")
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 200):
            limited = self.call(context, {
                "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
            })
        self.assertEqual(limited.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertIsNone(limited.result)

    def test_result_limit_uses_complete_utf8_serialization_boundary(self):
        context = self.make_context("я".encode("utf-8"))
        arguments = {"FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1}
        baseline = self.call(context, arguments)
        serialized_size = len(baseline.to_json().encode("utf-8"))

        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", serialized_size):
            exact = self.call(context, arguments)
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", serialized_size - 1):
            over = self.call(context, arguments)

        self.assertEqual(exact.result, baseline.result)
        self.assertEqual(exact.utf8_size(), serialized_size)
        self.assertEqual(over.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertIsNone(over.result)
        self.assertNotIn('"content":"я"', over.to_json())

    def test_invalid_arguments_eof_and_empty_file(self):
        context = self.make_context(b"")
        cases = [
            {"FILEPATH": "module.py", "START-LINE": 0, "END-LINE": 1},
            {"FILEPATH": "module.py", "START-LINE": True, "END-LINE": 1},
            {"FILEPATH": "module.py", "START-LINE": 2, "END-LINE": 1},
            {"FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.call(context, arguments)
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")
                self.assertTrue(result.diagnostics[0].retryable)

    def test_unknown_and_unsafe_paths(self):
        context = self.make_context()
        for filepath in ("missing.py", "module.txt", "../module.py", "/module.py", "C:/module.py", "dir\\module.py"):
            with self.subTest(filepath=filepath):
                result = self.call(context, {
                    "FILEPATH": filepath, "START-LINE": 1, "END-LINE": 1,
                })
                self.assertEqual(result.diagnostics[0].code, "source_object_not_found")
                self.assertNotIn(str(self.root), result.to_json())

    def test_indexed_non_python_file_is_rejected_without_path_leak(self):
        context = self.make_context()
        index = json.loads(context.source_index_path.read_text(encoding="utf-8"))
        source = self.root / "notes.txt"
        source.write_text("not python", encoding="utf-8")
        index["files"]["notes.txt"] = {
            "relative_path": "notes.txt", "name": "notes.txt", "module": "notes",
            "sha256": "x", "size_bytes": source.stat().st_size, "encoding": "utf-8",
            "classes": {}, "functions": {}, "constants": {},
        }
        context.source_index_path.write_text(json.dumps(index), encoding="utf-8")

        result = self.call(context, {
            "FILEPATH": "notes.txt", "START-LINE": 1, "END-LINE": 1,
        })

        self.assertEqual(result.diagnostics[0].code, "source_object_not_found")
        self.assertNotIn(str(self.root), result.to_json())

    def test_size_encoding_and_io_corruption_are_invalid_artifacts(self):
        cases = [
            (b"one", "utf-8", 999),
            (b"\xff", "utf-8", None),
            (b"one", "not-an-encoding", None),
        ]
        for raw, encoding, size in cases:
            with self.subTest(encoding=encoding, size=size):
                context = self.make_context(raw, encoding=encoding, size=size)
                result = self.call(context, {
                    "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
                })
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact")

        context = self.make_context()
        (self.root / "module.py").unlink()
        missing_materialized_file = self.call(context, {
            "FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1,
        })
        self.assertEqual(missing_materialized_file.diagnostics[0].code, "invalid_artifact")

    def test_registry_contains_schema_and_tool(self):
        definition = next(item for item in TOOL_REGISTRY if item.name == ToolName.Get_Code_Range)
        schema = json.loads(definition.schema_path.read_text(encoding="utf-8"))["function"]
        self.assertEqual(schema["parameters"]["required"], ["FILEPATH", "START-LINE", "END-LINE"])
        self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(schema["parameters"]["properties"]["START-LINE"]["minimum"], 1)
        self.assertEqual(schema["parameters"]["properties"]["END-LINE"]["minimum"], 1)

    def test_runtime_schema_rejects_missing_extra_wrong_types_and_end_bool(self):
        context = self.make_context()
        cases = [
            {"FILEPATH": "module.py", "START-LINE": 1},
            {"FILEPATH": "module.py", "START-LINE": 1, "END-LINE": 1, "EXTRA": 1},
            {"FILEPATH": 1, "START-LINE": 1, "END-LINE": 1},
            {"FILEPATH": "module.py", "START-LINE": 1, "END-LINE": True},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.call(context, arguments)
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")


if __name__ == "__main__":
    unittest.main()
