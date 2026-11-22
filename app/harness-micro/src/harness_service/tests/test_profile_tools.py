import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_connector.logic.validator import Validator
from response_models.models import ToolName
from tools_engine.accessors.graph import GraphAccessor
from tools_engine.accessors.metrics import MetricsAccessor
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY, validate_registry


class Prompts:
    def load_prompt(self):
        return "prompt"


class ProfileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def profile(self, name, value):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def context(self, graphs=None, metrics=None):
        return AnalysisContext(1, graphs or {}, metrics or {}, self.root / "index.json",
                               "a" * 64, "b" * 64)

    @staticmethod
    def call(context, name, arguments):
        return asyncio.run(ToolsEngine().entry_tool(
            context, name, json.dumps(arguments)))

    def test_both_tools_return_whole_profile_with_atomic_metadata(self):
        graph = {"artifact_kind": "graph_summary", "payload": {"имя": [1, 2]}}
        metrics = {"artifact_kind": "metrics_view", "payload": {"total": 3}}
        context = self.context(
            {"summary.overview": self.profile("graph", graph)},
            {"metrics.overview": self.profile("metrics", metrics)},
        )
        cases = (("GET-GRAPH", "summary.overview", graph),
                 ("GET-METRICS", "metrics.overview", metrics))
        for name, profile_id, expected in cases:
            with self.subTest(name=name):
                result = self.call(context, name, {"PROFILE-ID": profile_id})
                self.assertEqual(result.status, "success", result.to_json())
                self.assertEqual(result.result, expected)
                self.assertEqual(result.profile_id, profile_id)
                self.assertEqual((result.completeness.truncated,
                                  result.completeness.total,
                                  result.completeness.returned), (False, 1, 1))

    def test_profile_lookup_is_exact_and_arguments_are_strict(self):
        context = self.context(
            {" graph ": self.profile("spaced-graph", {"value": 1})},
            {" metrics ": self.profile("spaced-metrics", {"value": 2})},
        )
        for name, exact in (("GET-GRAPH", " graph "),
                            ("GET-METRICS", " metrics ")):
            with self.subTest(name=name):
                self.assertEqual(self.call(context, name, {
                    "PROFILE-ID": exact,
                }).status, "success")
                for arguments in ({"PROFILE-ID": exact.strip()}, {"PROFILE-ID": ""},
                                  {}, {"PROFILE-ID": 1},
                                  {"PROFILE-ID": exact, "EXTRA": True}):
                    result = self.call(context, name, arguments)
                    expected = ("profile_not_found" if arguments.get("PROFILE-ID") == exact.strip()
                                else "invalid_tool_arguments")
                    self.assertEqual(result.diagnostics[0].code, expected)

    def test_missing_and_invalid_artifacts_have_safe_diagnostics(self):
        for name, graph in (("GET-GRAPH", True), ("GET-METRICS", False)):
            missing = self.call(self.context(), name, {"PROFILE-ID": "missing"})
            self.assertEqual(missing.diagnostics[0].code, "profile_not_found")
            self.assertTrue(missing.diagnostics[0].retryable)
            for index, raw in enumerate((b"{", b"[]", b"\xff")):
                path = self.root / f"bad-{name}-{index}.json"
                path.write_bytes(raw)
                context = self.context({"bad": path} if graph else None,
                                       None if graph else {"bad": path})
                result = self.call(context, name, {"PROFILE-ID": "bad"})
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
                self.assertFalse(result.diagnostics[0].retryable)
                self.assertNotIn(str(self.root), result.to_json())

    def test_results_are_deep_copies_and_accessors_reuse_task_cache(self):
        graph_path = self.profile("cached-graph", {"nested": {"items": [1]}})
        metrics_path = self.profile("cached-metrics", {"nested": {"items": [2]}})
        context = self.context({"p": graph_path}, {"p": metrics_path})
        with patch.object(GraphAccessor, "_read", wraps=GraphAccessor(context)._read) as graph_load:
            first = self.call(context, "GET-GRAPH", {"PROFILE-ID": "p"})
            first.result["nested"]["items"].append(9)
            second = self.call(context, "GET-GRAPH", {"PROFILE-ID": "p"})
            self.assertEqual(second.result["nested"]["items"], [1])
            self.assertEqual(graph_load.call_count, 1)
        with patch.object(MetricsAccessor, "_load", wraps=MetricsAccessor(context, "p")._load) as metrics_load:
            first = self.call(context, "GET-METRICS", {"PROFILE-ID": "p"})
            first.result["nested"]["items"].append(9)
            second = self.call(context, "GET-METRICS", {"PROFILE-ID": "p"})
            self.assertEqual(second.result["nested"]["items"], [2])
            self.assertEqual(metrics_load.call_count, 1)

    def test_utf8_limit_accepts_exact_boundary_and_rejects_one_byte_less(self):
        payload = "я" * 1000
        context = self.context(metrics={
            "p": self.profile("utf8", {"value": payload}),
        })
        unrestricted = self.call(context, "GET-METRICS", {"PROFILE-ID": "p"})
        boundary = unrestricted.utf8_size()
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", boundary):
            accepted = self.call(context, "GET-METRICS", {"PROFILE-ID": "p"})
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", boundary - 1):
            rejected = self.call(context, "GET-METRICS", {"PROFILE-ID": "p"})
        self.assertEqual(accepted.status, "success")
        self.assertEqual(rejected.diagnostics[0].code, "extraction_limit_exceeded")
        self.assertEqual(rejected.diagnostics[0].details["actual_bytes"], boundary)
        self.assertEqual(rejected.diagnostics[0].details["limit_bytes"], boundary - 1)
        self.assertIsNone(rejected.result)
        self.assertNotIn(payload[:100], rejected.to_json())
        self.assertLessEqual(rejected.utf8_size(), boundary - 1)

    def test_summary_graph_is_raw_readable_but_not_a_topology_profile(self):
        context = self.context({
            "summary.overview": self.profile("summary", {"summary": {"nodes": 4}}),
        })
        self.assertEqual(self.call(context, "GET-GRAPH", {
            "PROFILE-ID": "summary.overview",
        }).status, "success")
        topology = self.call(context, "GET-GRAPH-SUBGRAPH", {
            "PROFILE-ID": "summary.overview", "NODE-ID": "n", "DEPTH": 0,
        })
        self.assertEqual(topology.diagnostics[0].code, "invalid_tool_arguments")

    def test_registry_schemas_are_visible_and_strict(self):
        validate_registry(TOOL_REGISTRY)
        names = [model.function.name
                 for model in Validator(Prompts(), TOOL_REGISTRY).load_tools_models()]
        for tool_name in (ToolName.Get_Graph, ToolName.Get_Metrics):
            self.assertIn(tool_name.value, names)
            definitions = [item for item in TOOL_REGISTRY if item.name == tool_name]
            self.assertEqual(len(definitions), 1)
            function = json.loads(
                definitions[0].schema_path.read_text(encoding="utf-8"))["function"]
            self.assertEqual(function["parameters"]["required"], ["PROFILE-ID"])
            self.assertFalse(function["parameters"]["additionalProperties"])
            self.assertEqual(function["parameters"]["properties"]["PROFILE-ID"]["type"],
                             "string")
            self.assertTrue(function["strict"])


if __name__ == "__main__":
    unittest.main()
