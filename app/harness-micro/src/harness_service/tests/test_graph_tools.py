import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from response_models.models import ToolName
from rules.rules_config import _graph_limits
from tools_engine.logic.engine import ToolsEngine
from tools_engine.accessors.graph import GraphAccessor, valid_graph_path
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY, validate_registry


class GraphToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def node(node_id, kind="class", name="pkg.Name", path="pkg/a.py", **extra):
        return {"id": node_id, "kind": kind, "qualified_name": name, "path": path,
                "location": {"path": path, "line": 1, "column": 0}, **extra}

    def context(self, nodes=None, raw=None, profiles=True):
        graph = self.root / "graph.json"
        if raw is None:
            graph.write_text(json.dumps({"schema_version": 1, "nodes": nodes or []}), encoding="utf-8")
        else:
            graph.write_bytes(raw)
        return AnalysisContext(1, {"canonical.full": graph} if profiles else {}, {},
                               self.root / "index.json", "a" * 64, "b" * 64)

    @staticmethod
    def call(context, name, arguments):
        return asyncio.run(ToolsEngine().entry_tool(context, name, json.dumps(arguments)))

    def test_all_kinds_projection_get_extras_and_completeness(self):
        kinds = ("file", "module", "class", "field", "method", "function", "constant")
        nodes = [self.node(str(i), kind, f"pkg.Item{i}", extra={"i": i})
                 for i, kind in enumerate(kinds)]
        context = self.context(nodes)
        found = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "item", "LIMIT": 1})
        self.assertEqual(set(found.result["nodes"][0]),
                         {"id", "kind", "qualified_name", "path", "location"})
        self.assertEqual((found.completeness.total, found.completeness.returned), (7, 1))
        self.assertTrue(found.completeness.truncated)
        got = self.call(context, "GET-GRAPH-NODE", {"NODE-ID": "0"})
        self.assertEqual(got.result["extra"], {"i": 0})
        self.assertEqual(got.profile_id, "canonical.full")

    def test_casefold_no_dedup_no_normalization_query_spaces_and_sort(self):
        nodes = [self.node("b", name="Straße"), self.node("a", name="STRASSE"),
                 self.node("c", name="é"), self.node("d", name="e\u0301"),
                 self.node("e", name="has space")]
        context = self.context(nodes)
        result = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "strasse"})
        self.assertEqual([n["id"] for n in result.result["nodes"]], ["a", "b"])
        self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {"QUERY": "é"}).completeness.total, 1)
        self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {"QUERY": " "}).result["nodes"][0]["id"], "e")

    def test_exact_filters_empty_unknown_and_argument_limits(self):
        context = self.context([self.node("x", kind="method", path="A/x.py")])
        self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {
            "QUERY": "name", "KIND": "method", "PATH": "A/x.py", "LIMIT": 100,
        }).completeness.total, 1)
        self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {
            "QUERY": "name", "PATH": "a/x.py",
        }).completeness.total, 0)
        for value in (0, 101, True):
            self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {
                "QUERY": "x", "LIMIT": value,
            }).diagnostics[0].code, "invalid_tool_arguments")
        self.assertEqual(self.call(context, "GET-GRAPH-NODE", {"NODE-ID": "X"}).diagnostics[0].code,
                         "node_not_found")

    def test_get_graph_node_rejects_invalid_arguments_as_retryable(self):
        context = self.context([self.node("x")])
        cases = ({}, {"NODE-ID": ""}, {"NODE-ID": 1},
                 {"NODE-ID": "x", "EXTRA": True})
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.call(context, "GET-GRAPH-NODE", arguments)
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")
                self.assertTrue(result.diagnostics[0].retryable)

    def test_empty_query_exact_limit_boundary_and_filters_precede_total(self):
        nodes = [self.node(str(i), kind="method" if i < 3 else "class",
                           name=f"pkg.Match{i}", path="pkg/a.py" if i != 2 else "pkg/b.py")
                 for i in range(4)]
        context = self.context(nodes)
        self.assertEqual(self.call(context, "FIND-GRAPH-NODES", {
            "QUERY": "",
        }).diagnostics[0].code, "invalid_tool_arguments")
        exact = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "match", "LIMIT": 4})
        self.assertEqual((exact.completeness.total, exact.completeness.returned,
                          exact.completeness.truncated), (4, 4, False))
        overflow = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "match", "LIMIT": 3})
        self.assertEqual((overflow.completeness.total, overflow.completeness.returned,
                          overflow.completeness.truncated), (4, 3, True))
        filtered = self.call(context, "FIND-GRAPH-NODES", {
            "QUERY": "match", "KIND": "method", "PATH": "pkg/a.py", "LIMIT": 1,
        })
        self.assertEqual((filtered.completeness.total, filtered.completeness.returned,
                          filtered.completeness.truncated), (2, 1, True))

    def test_default_twenty_and_runtime_lower_maximum(self):
        context = self.context([self.node(str(i), name=f"pkg.Match{i:02d}")
                                for i in range(21)])
        defaulted = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "match"})
        self.assertEqual((defaulted.completeness.total, defaulted.completeness.returned,
                          defaulted.completeness.truncated), (21, 20, True))
        with patch("tools_engine.tools.find_graph_nodes.RULES_CONFIG.default_graph_search_limit", 2), \
                patch("tools_engine.tools.find_graph_nodes.RULES_CONFIG.max_graph_search_limit", 2):
            accepted = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "match", "LIMIT": 2})
            rejected = self.call(context, "FIND-GRAPH-NODES", {"QUERY": "match", "LIMIT": 3})
        self.assertEqual(accepted.completeness.returned, 2)
        self.assertEqual(rejected.diagnostics[0].code, "invalid_tool_arguments")

    def test_missing_profile_and_safe_malformed_artifacts(self):
        missing = self.call(self.context(profiles=False), "FIND-GRAPH-NODES", {"QUERY": "x"})
        self.assertEqual(missing.diagnostics[0].code, "profile_not_found")
        malformed = (b"\xff", b"{", json.dumps({"schema_version": True, "nodes": []}).encode())
        for raw in malformed:
            result = self.call(self.context(raw=raw), "FIND-GRAPH-NODES", {"QUERY": "x"})
            self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
            self.assertNotIn(str(self.root), result.to_json())

    def test_invalid_nodes_paths_duplicates_and_runtime_config(self):
        invalid = [self.node("x", path=value) for value in
                   ("", "/x.py", "a\\x.py", "a//x.py", "./x.py", "a/../x.py")]
        invalid += [{"id": "x"}, self.node("x", kind="other")]
        invalid += [[self.node("x"), self.node("x")]]
        for value in invalid:
            nodes = value if isinstance(value, list) else [value]
            self.assertEqual(self.call(self.context(nodes), "FIND-GRAPH-NODES", {
                "QUERY": "x",
            }).diagnostics[0].code, "invalid_artifact")

    def test_path_rejects_drive_unc_backslash_dot_and_empty_segments(self):
        invalid = ("C:/x.py", "//host/x.py", "a\\x.py", ".", "..", "a/./x.py",
                   "a/../x.py", "a//x.py", "a/")
        for path in invalid:
            with self.subTest(path=path):
                self.assertFalse(valid_graph_path(path))
                result = self.call(self.context([self.node("x")]), "FIND-GRAPH-NODES", {
                    "QUERY": "x", "PATH": path,
                })
                self.assertEqual(result.diagnostics[0].code, "invalid_tool_arguments")

    def test_minimal_schema_root_required_fields_and_boolean_coordinates(self):
        invalid_roots = ([], {"nodes": []}, {"schema_version": 1},
                         {"schema_version": 1, "nodes": {}},
                         {"schema_version": 2, "nodes": []})
        for root in invalid_roots:
            with self.subTest(root=root):
                result = self.call(self.context(raw=json.dumps(root).encode()),
                                   "FIND-GRAPH-NODES", {"QUERY": "x"})
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
        for field in ("id", "kind", "qualified_name", "path", "location"):
            node = self.node("x")
            del node[field]
            with self.subTest(field=field):
                self.assertEqual(self.call(self.context([node]), "FIND-GRAPH-NODES", {
                    "QUERY": "x",
                }).diagnostics[0].code, "invalid_artifact")
        for field in ("path", "line", "column"):
            node = self.node("x")
            del node["location"][field]
            with self.subTest(location_field=field):
                self.assertEqual(self.call(self.context([node]), "FIND-GRAPH-NODES", {
                    "QUERY": "x",
                }).diagnostics[0].code, "invalid_artifact")
        for field in ("line", "column"):
            node = self.node("x")
            node["location"][field] = True
            with self.subTest(boolean_coordinate=field):
                self.assertEqual(self.call(self.context([node]), "FIND-GRAPH-NODES", {
                    "QUERY": "x",
                }).diagnostics[0].code, "invalid_artifact")
        with patch("tools_engine.tools.find_graph_nodes.RULES_CONFIG.default_graph_search_limit", True):
            self.assertEqual(self.call(self.context(), "FIND-GRAPH-NODES", {
                "QUERY": "x",
            }).diagnostics[0].code, "invalid_artifact")

    def test_cache_shared_by_tools_but_isolated_between_contexts(self):
        first = self.context([self.node("x")])
        original_load = GraphAccessor._load
        calls = []

        def counted_load(accessor):
            calls.append(accessor.context.task_id)
            return original_load(accessor)

        with patch.object(GraphAccessor, "_load", counted_load):
            self.call(first, "FIND-GRAPH-NODES", {"QUERY": "name"})
            self.call(first, "GET-GRAPH-NODE", {"NODE-ID": "x"})
            self.assertEqual(calls, [1])
        second = self.context([self.node("y")])
        self.assertEqual(self.call(second, "GET-GRAPH-NODE", {"NODE-ID": "y"}).status, "success")

    def test_config_registry_and_schemas(self):
        self.assertEqual(_graph_limits(20, 100), (20, 100))
        for values in ((0, 100), (True, 100), (20, 0), (101, 100)):
            with self.assertRaises(ValueError):
                _graph_limits(*values)
        names = {item.name for item in TOOL_REGISTRY}
        self.assertIn(ToolName.Find_Graph_Nodes, names)
        self.assertIn(ToolName.Get_Graph_Node, names)
        with self.assertRaises(ValueError):
            _graph_limits(20, 101)
        graph_definitions = tuple(item for item in TOOL_REGISTRY if item.name in {
            ToolName.Find_Graph_Nodes, ToolName.Get_Graph_Node,
        })
        self.assertEqual(len(graph_definitions), 2)
        validate_registry(graph_definitions)

    def test_get_exact_id_returns_independent_deep_copy(self):
        context = self.context([self.node("Case", metadata={"items": [1]})])
        self.assertEqual(self.call(context, "GET-GRAPH-NODE", {
            "NODE-ID": "case",
        }).diagnostics[0].code, "node_not_found")
        first = self.call(context, "GET-GRAPH-NODE", {"NODE-ID": "Case"})
        self.assertEqual(first.result["metadata"], {"items": [1]})
        first.result["metadata"]["items"].append(2)
        second = self.call(context, "GET-GRAPH-NODE", {"NODE-ID": "Case"})
        self.assertEqual(second.result["metadata"], {"items": [1]})

    def test_engine_utf8_result_limit_is_authoritative(self):
        context = self.context([self.node("x", payload="я" * 100)])
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 200):
            result = self.call(context, "GET-GRAPH-NODE", {"NODE-ID": "x"})
        self.assertEqual(result.diagnostics[0].code, "extraction_limit_exceeded")


if __name__ == "__main__":
    unittest.main()
