import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_connector.logic.validator import Validator
from response_models.models import ToolName
from tools_engine.accessors.metrics import MetricsAccessor
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY, validate_registry


class Prompts:
    def load_prompt(self):
        return "prompt"


class MetricsToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def context(self, profiles=None, task_id=1):
        return AnalysisContext(task_id, {}, profiles or {}, self.root / "index.json",
                               "a" * 64, "b" * 64)

    def profile(self, name, value):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def call(context, arguments):
        return asyncio.run(ToolsEngine().entry_tool(
            context, "GET-METRICS-ITEM", json.dumps(arguments)))

    def test_scalar_full_view_and_root_preserve_raw_contract(self):
        data = {"scalar": 7, "full": {"$columns": ["x"], "$rows": [[1]]},
                "view": [True, None]}
        context = self.context({"metrics.full": self.profile("full", data)})
        self.assertEqual(self.call(context, {
            "PROFILE-ID": "metrics.full", "METRIC-PATH": "/scalar",
        }).result, 7)
        self.assertEqual(self.call(context, {
            "PROFILE-ID": "metrics.full", "METRIC-PATH": "/full",
        }).result, data["full"])
        self.assertEqual(self.call(context, {
            "PROFILE-ID": "metrics.full", "METRIC-PATH": "/view",
        }).result, data["view"])
        self.assertEqual(self.call(context, {
            "PROFILE-ID": "metrics.full", "METRIC-PATH": "",
        }).result, data)

    def test_escaping_empty_key_arrays_and_numeric_object_key(self):
        data = {"a/b": {"~key": {"": "empty"}}, "items": ["zero", {"0": "key"}]}
        context = self.context({"p": self.profile("p", data)})
        cases = (("/a~1b/~0key/", "empty"), ("/items/0", "zero"),
                 ("/items/1/0", "key"))
        for pointer, expected in cases:
            with self.subTest(pointer=pointer):
                self.assertEqual(self.call(context, {
                    "PROFILE-ID": "p", "METRIC-PATH": pointer,
                }).result, expected)

    def test_invalid_pointer_syntax(self):
        context = self.context({"p": self.profile("p", {})})
        for pointer in ("x", "#", "#/x", "/x~", "/x~2", "/x~01~"):
            with self.subTest(pointer=pointer):
                result = self.call(context, {"PROFILE-ID": "p", "METRIC-PATH": pointer})
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")

    def test_missing_paths_array_forms_and_scalar_traversal(self):
        context = self.context({"p": self.profile(
            "p", {"a": [1], "scalar": 1, "null": None})})
        for pointer in ("/missing", "/a/-", "/a/00", "/a/01", "/a/+1",
                        "/a/-1", "/a/1", "/a/١", "/scalar/x", "/null/x"):
            with self.subTest(pointer=pointer):
                result = self.call(context, {"PROFILE-ID": "p", "METRIC-PATH": pointer})
                self.assertEqual(result.diagnostics[0].code, "metric_path_not_found")

    def test_oversized_array_index_is_reported_as_missing_path(self):
        pointer = "/a/" + "9" * 5000
        context = self.context({"p": self.profile("p", {"a": [1]})})

        diagnostic = self.call(context, {
            "PROFILE-ID": "p", "METRIC-PATH": pointer,
        }).diagnostics[0]

        self.assertEqual(diagnostic.code, "metric_path_not_found")
        self.assertTrue(diagnostic.retryable)
        self.assertEqual(diagnostic.details["metric_path"], pointer)

    def test_missing_and_empty_profile(self):
        missing = self.call(self.context(), {"PROFILE-ID": "missing", "METRIC-PATH": ""})
        empty = self.call(self.context(), {"PROFILE-ID": "", "METRIC-PATH": ""})
        self.assertEqual(missing.diagnostics[0].code, "profile_not_found")
        self.assertEqual(empty.diagnostics[0].code, "invalid_tool_arguments")

    def test_profile_id_is_an_exact_mapping_key(self):
        context = self.context({
            "profile": self.profile("plain", {"value": "plain"}),
            " profile ": self.profile("spaced", {"value": "spaced"}),
        })
        spaced = self.call(context, {
            "PROFILE-ID": " profile ", "METRIC-PATH": "/value",
        })
        wrong_case = self.call(context, {
            "PROFILE-ID": "PROFILE", "METRIC-PATH": "/value",
        })
        self.assertEqual(spaced.result, "spaced")
        self.assertEqual(wrong_case.diagnostics[0].code, "profile_not_found")

    def test_malformed_artifacts_have_safe_details(self):
        cases = (b"\xff", b"{", b"[]")
        for index, raw in enumerate(cases):
            path = self.root / f"bad{index}.json"
            path.write_bytes(raw)
            result = self.call(self.context({"p": path}), {
                "PROFILE-ID": "p", "METRIC-PATH": "",
            })
            diagnostic = result.diagnostics[0]
            self.assertEqual(diagnostic.code, "invalid_artifact")
            self.assertEqual(diagnostic.details, {"artifact": "metrics_profile", "profile_id": "p"})
            self.assertNotIn(str(self.root), result.to_json())
        missing_file = self.call(self.context({"p": self.root / "absent.json"}), {
            "PROFILE-ID": "p", "METRIC-PATH": "",
        })
        self.assertEqual(missing_file.diagnostics[0].code, "invalid_artifact")
        self.assertEqual(missing_file.diagnostics[0].details,
                         {"artifact": "metrics_profile", "profile_id": "p"})
        self.assertNotIn(str(self.root), missing_file.to_json())

    def test_cache_is_per_profile_and_context(self):
        profiles = {"a": self.profile("a", {"x": 1}),
                    "b": self.profile("b", {"x": 2})}
        first = self.context(profiles, 1)
        original = MetricsAccessor._load
        calls = []

        def counted(accessor):
            calls.append((accessor.context.task_id, accessor.profile_id))
            return original(accessor)

        with patch.object(MetricsAccessor, "_load", counted):
            self.call(first, {"PROFILE-ID": "a", "METRIC-PATH": "/x"})
            self.call(first, {"PROFILE-ID": "a", "METRIC-PATH": "/x"})
            self.call(first, {"PROFILE-ID": "b", "METRIC-PATH": "/x"})
            self.call(self.context(profiles, 2), {"PROFILE-ID": "a", "METRIC-PATH": "/x"})
        self.assertEqual(calls, [(1, "a"), (1, "b"), (2, "a")])

    def test_returned_values_are_deep_copies(self):
        context = self.context({"p": self.profile("p", {"nested": {"items": [1]}})})
        first = self.call(context, {"PROFILE-ID": "p", "METRIC-PATH": "/nested"})
        first.result["items"].append(2)
        second = self.call(context, {"PROFILE-ID": "p", "METRIC-PATH": "/nested"})
        self.assertEqual(second.result, {"items": [1]})

    def test_schema_registry_and_validator_visibility(self):
        validate_registry(TOOL_REGISTRY)
        definitions = [item for item in TOOL_REGISTRY
                       if item.name == ToolName.Get_Metrics_Item]
        self.assertEqual(len(definitions), 1)
        names = [model.function.name
                 for model in Validator(Prompts(), TOOL_REGISTRY).load_tools_models()]
        self.assertIn("GET-METRICS-ITEM", names)

        schema = json.loads(definitions[0].schema_path.read_text(encoding="utf-8"))["function"]
        self.assertEqual(schema["parameters"]["required"], ["PROFILE-ID", "METRIC-PATH"])
        self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(schema["parameters"]["properties"]["PROFILE-ID"]["type"], "string")
        self.assertEqual(schema["parameters"]["properties"]["METRIC-PATH"]["type"], "string")
        self.assertTrue(schema["strict"])

    def test_argument_validation_and_diagnostics_contract(self):
        context = self.context({"p": self.profile("p", {"a": []})})
        cases = (
            ({"PROFILE-ID": "p"}, {"missing": ["METRIC-PATH"]}),
            ({"METRIC-PATH": ""}, {"missing": ["PROFILE-ID"]}),
            ({"PROFILE-ID": 1, "METRIC-PATH": ""},
             {"argument": "PROFILE-ID", "expected": "string"}),
            ({"PROFILE-ID": "p", "METRIC-PATH": 1},
             {"argument": "METRIC-PATH", "expected": "string"}),
            ({"PROFILE-ID": "p", "METRIC-PATH": "", "EXTRA": True},
             {"additional": ["EXTRA"]}),
        )
        for arguments, details in cases:
            with self.subTest(arguments=arguments):
                diagnostic = self.call(context, arguments).diagnostics[0]
                self.assertEqual(diagnostic.code, "invalid_tool_arguments")
                self.assertTrue(diagnostic.retryable)
                self.assertEqual(diagnostic.details, details)

        missing_path = self.call(context, {
            "PROFILE-ID": "p", "METRIC-PATH": "/a/0",
        }).diagnostics[0]
        self.assertEqual(missing_path.code, "metric_path_not_found")
        self.assertTrue(missing_path.retryable)
        self.assertEqual(missing_path.details, {
            "profile_id": "p", "metric_path": "/a/0",
        })

        missing_profile = self.call(context, {
            "PROFILE-ID": "absent", "METRIC-PATH": "",
        }).diagnostics[0]
        self.assertEqual(missing_profile.code, "profile_not_found")
        self.assertTrue(missing_profile.retryable)
        self.assertEqual(missing_profile.details, {"profile_id": "absent"})

    def test_utf8_result_limit(self):
        context = self.context({"p": self.profile("p", {"value": "я" * 1000})})
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 500):
            result = self.call(context, {"PROFILE-ID": "p", "METRIC-PATH": "/value"})
        self.assertEqual(result.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertTrue(result.diagnostics[0].retryable)
        self.assertEqual(result.diagnostics[0].details["scope"], "serialized_tool_result")
        self.assertEqual(result.diagnostics[0].details["limit_bytes"], 500)
        self.assertGreater(result.diagnostics[0].details["actual_bytes"], 500)
        self.assertLessEqual(result.utf8_size(), 500)


if __name__ == "__main__":
    unittest.main()
