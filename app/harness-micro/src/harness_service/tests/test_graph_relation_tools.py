import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from response_models.models import ToolData, ToolName
from rules.rules_config import MAX_GRAPH_DEPTH, MAX_GRAPH_ITEM_LIMIT, _positive_int
from tools_engine.accessors.graph import GraphAccessor
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY, validate_registry


class GraphRelationToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def node(identifier, kind="class", path="pkg/a.py"):
        return {"id": identifier, "kind": kind, "qualified_name": identifier,
                "path": path, "location": {"path": path, "line": 1, "column": 0}}

    @staticmethod
    def edge(identifier, source, target, kind="contains", **extra):
        return {"id": identifier, "kind": kind, "source_id": source,
                "target_id": target, **extra}

    @staticmethod
    def location():
        return {"path": "pkg/a.py", "line": 1, "column": 0}

    def canonical(self):
        nodes = [self.node("file", "file"), self.node("module", "module"),
                 self.node("class", "class"), self.node("field", "field"),
                 self.node("function", "function"), self.node("method", "method"),
                 self.node("other", "class")]
        return {"schema_version": 1, "parser_semantics_version": 7,
                "nodes": nodes, "edges": [], "callsites": [],
                "import_references": [], "type_references": []}

    def view(self, profile, nodes, edges):
        return {"artifact_kind": "graph_view", "view_schema_version": 1,
                "profile": {"id": profile, "version": 1},
                "payload": {"nodes": nodes, "edges": edges}}

    def context(self, canonical=None, views=None, raw=None):
        paths = {}
        documents = {"canonical.full": canonical or self.canonical(), **(views or {})}
        for index, (profile, document) in enumerate(documents.items()):
            path = self.root / f"graph-{index}.json"
            if raw is not None and profile == "canonical.full":
                path.write_bytes(raw)
            else:
                path.write_text(json.dumps(document), encoding="utf-8")
            paths[profile] = path
        return AnalysisContext(1, paths, {}, self.root / "index.json", "a" * 64, "b" * 64)

    @staticmethod
    def call(context, name, arguments):
        return asyncio.run(ToolsEngine().entry_tool(context, name, json.dumps(arguments)))

    def subgraph(self, context, **changes):
        arguments = {"PROFILE-ID": "canonical.full", "NODE-ID": "file", "DEPTH": 1}
        arguments.update(changes)
        return self.call(context, "GET-GRAPH-SUBGRAPH", arguments)

    def references(self, context, owner="function", **changes):
        arguments = {"OWNER-NODE-ID": owner}
        arguments.update(changes)
        return self.call(context, "GET-GRAPH-REFERENCES", arguments)

    def test_canonical_root_depth_zero_self_loop_and_induced_parallel_edges(self):
        graph = self.canonical()
        graph["edges"] = [self.edge("z", "file", "file"),
                          self.edge("b", "file", "module"),
                          self.edge("a", "file", "module")]
        zero = self.subgraph(self.context(graph), **{"DEPTH": 0})
        self.assertEqual([item["node"]["id"] for item in zero.result["nodes"]], ["file"])
        self.assertEqual([edge["id"] for edge in zero.result["edges"]], ["z"])
        one = self.subgraph(self.context(graph))
        self.assertEqual([edge["id"] for edge in one.result["edges"]], ["a", "b", "z"])

    def test_direction_filter_cycle_stable_bfs_and_induced_extra_edge(self):
        graph = self.canonical()
        graph["edges"] = [self.edge("3", "file", "module"), self.edge("2", "module", "class"),
                          self.edge("1", "class", "file"), self.edge("0", "file", "class", "calls")]
        context = self.context(graph)
        outgoing = self.subgraph(context, **{"DEPTH": 2, "DIRECTION": "outgoing"})
        self.assertEqual([(x["node"]["id"], x["distance"]) for x in outgoing.result["nodes"]],
                         [("file", 0), ("class", 1), ("module", 1)])
        self.assertEqual([x["id"] for x in outgoing.result["edges"]], ["0", "1", "2", "3"])
        incoming = self.subgraph(context, **{"DIRECTION": "incoming"})
        self.assertEqual([x["node"]["id"] for x in incoming.result["nodes"]], ["file", "class"])
        filtered = self.subgraph(context, **{"RELATION-TYPE": "contains", "DEPTH": 1})
        self.assertEqual([x["node"]["id"] for x in filtered.result["nodes"]],
                         ["file", "class", "module"])

    def test_view_without_locations_profile_version_and_schema_whitelist(self):
        nodes = [{"id": "file", "kind": "file", "qualified_name": "file", "path": "a.py"}]
        profile = "structure.declarations"
        good = self.context(views={profile: self.view(profile, nodes, [])})
        result = self.subgraph(good, **{"PROFILE-ID": profile, "DEPTH": 0})
        self.assertEqual(result.result["nodes"][0]["node"], nodes[0])
        for field, value in (("version", 2), ("version", True)):
            bad = self.view(profile, nodes, [])
            bad["profile"][field] = value
            self.assertEqual(self.subgraph(self.context(views={profile: bad}),
                                           **{"PROFILE-ID": profile}).diagnostics[0].code,
                             "invalid_artifact")
        mismatch = self.view("dependency.files", nodes, [])
        self.assertEqual(self.subgraph(self.context(views={profile: mismatch}),
                                       **{"PROFILE-ID": profile}).diagnostics[0].code,
                         "invalid_artifact")
        self.assertEqual(self.subgraph(good, **{"PROFILE-ID": "unknown"}).diagnostics[0].code,
                         "invalid_tool_arguments")

    def test_empty_qualified_name_is_valid_in_canonical_and_view(self):
        graph = self.canonical(); graph["nodes"][0]["qualified_name"] = ""
        self.assertEqual(self.subgraph(self.context(graph), **{"DEPTH": 0}).result["root_node_id"],
                         "file")
        profile = "structure.declarations"
        node = {"id": "file", "kind": "file", "qualified_name": "", "path": "a.py"}
        result = self.subgraph(self.context(views={profile: self.view(profile, [node], [])}),
                               **{"PROFILE-ID": profile, "DEPTH": 0})
        self.assertEqual(result.result["nodes"][0]["node"]["qualified_name"], "")

    def test_all_graph_view_profiles_accept_their_relations(self):
        for profile, relation in (("structure.declarations", "contains"),
                                  ("dependency.files", "imports"),
                                  ("dependency.architecture", "imports"),
                                  ("calls.topology", "calls"),
                                  ("calls.detailed", "awaits"),
                                  ("types.topology", "inherits"),
                                  ("objects.metrics_basis", "accesses_field")):
            nodes = [{"id": "a", "kind": "file", "qualified_name": "a", "path": "a.py"},
                     {"id": "b", "kind": "file", "qualified_name": "b", "path": "b.py"}]
            view = self.view(profile, nodes, [self.edge("e", "a", "b", relation)])
            with self.subTest(profile=profile):
                result = self.subgraph(self.context(views={profile: view}),
                                       **{"PROFILE-ID": profile, "NODE-ID": "a",
                                          "RELATION-TYPE": relation})
                self.assertEqual([item["node"]["id"] for item in result.result["nodes"]], ["a", "b"])

    def test_unknown_node_missing_profile_and_bad_edges_or_optional_counts(self):
        self.assertEqual(self.subgraph(self.context(), **{"NODE-ID": "missing"}).diagnostics[0].code,
                         "node_not_found")
        context = self.context()
        context = AnalysisContext(1, {}, {}, context.source_index_path, "a" * 64, "b" * 64)
        self.assertEqual(self.subgraph(context).diagnostics[0].code, "profile_not_found")
        mutations = [self.edge("x", "file", "missing"), self.edge("x", "file", "module", weight=0),
                     self.edge("x", "file", "module", weight=True),
                     self.edge("x", "file", "module", exact_occurrence_count=-1)]
        for edge in mutations:
            graph = self.canonical(); graph["edges"] = [edge]
            with self.subTest(edge=edge):
                self.assertEqual(self.subgraph(self.context(graph)).diagnostics[0].code,
                                 "invalid_artifact")
        graph = self.canonical(); graph["edges"] = [self.edge("x", "file", "module")] * 2
        self.assertEqual(self.subgraph(self.context(graph)).diagnostics[0].code, "invalid_artifact")

    def test_node_truncation_counts_completeness_and_runtime_config(self):
        graph = self.canonical()
        graph["edges"] = [self.edge(str(i), "file", node["id"])
                          for i, node in enumerate(graph["nodes"][1:])]
        with patch("tools_engine.tools.get_graph_subgraph.RULES_CONFIG.max_graph_subgraph_nodes", 2):
            result = self.subgraph(self.context(graph))
        self.assertEqual(result.result["counts"]["nodes"], {"total": 7, "returned": 2})
        self.assertEqual(
            (result.completeness.total, result.completeness.returned),
            (result.result["counts"]["nodes"]["total"]
             + result.result["counts"]["edges"]["total"],
             result.result["counts"]["nodes"]["returned"]
             + result.result["counts"]["edges"]["returned"]),
        )
        self.assertTrue(result.completeness.truncated)
        for field, value in (("max_graph_subgraph_depth", True),
                             ("max_graph_subgraph_depth", 11),
                             ("max_graph_subgraph_nodes", 0)):
            with patch(f"tools_engine.tools.get_graph_subgraph.RULES_CONFIG.{field}", value):
                self.assertEqual(self.subgraph(self.context()).diagnostics[0].code, "invalid_artifact")

    def test_relation_filter_applies_before_bfs_and_truncation_is_distance_id_prefix(self):
        graph = self.canonical()
        graph["edges"] = [self.edge("call", "file", "class", "calls"),
                          self.edge("contains", "class", "other")]
        filtered = self.subgraph(self.context(graph), **{"RELATION-TYPE": "contains", "DEPTH": 2})
        self.assertEqual([item["node"]["id"] for item in filtered.result["nodes"]], ["file"])

        graph["edges"] = [self.edge("z", "file", "module"),
                          self.edge("a", "file", "class"),
                          self.edge("b", "class", "other")]
        with patch("tools_engine.tools.get_graph_subgraph.RULES_CONFIG.max_graph_subgraph_nodes", 3):
            truncated = self.subgraph(self.context(graph), **{"DEPTH": 2})
        self.assertEqual([(item["node"]["id"], item["distance"])
                          for item in truncated.result["nodes"]],
                         [("file", 0), ("class", 1), ("module", 1)])

    def call_ref(self, identifier="shared", owner="function", status="exact"):
        return {"id": identifier, "caller_id": owner, "expression": "f()",
                "location": self.location(), "syntactic_depth": 0, "awaited": False,
                "resolution": status, "target_id": "method" if status == "exact" else None,
                "candidate_ids": ["function", "method"] if status == "ambiguous" else []}

    def import_ref(self, identifier="shared", owner="file", status="exact"):
        return {"id": identifier, "importer_id": owner, "kind": "from", "module": "pkg",
                "name": "a", "alias": None, "level": 0, "location": self.location(),
                "resolution": status, "target_id": "module" if status == "exact" else None,
                "candidate_ids": []}

    def type_ref(self, identifier="shared", owner="class", status="exact", role="base"):
        return {"id": identifier, "owner_id": owner, "role": role, "expression": "Base",
                "location": self.location(), "resolution": status,
                "target_id": "other" if status == "exact" else None,
                "candidate_ids": ["class", "other"] if status == "ambiguous" else []}

    def test_direct_owners_statuses_same_ids_filters_and_order(self):
        graph = self.canonical()
        graph["callsites"] = [self.call_ref(owner="file"), self.call_ref("z", "function", "external"),
                              self.call_ref("module-call", "module"), self.call_ref("method-call", "method")]
        graph["import_references"] = [self.import_ref(), self.import_ref("module-import", "module")]
        graph["type_references"] = [self.type_ref()]
        file_result = self.references(self.context(graph), "file")
        self.assertEqual([x["reference_type"] for x in file_result.result["references"]],
                         ["call", "import"])
        self.assertEqual([x["reference"]["id"] for x in file_result.result["references"]],
                         ["shared", "shared"])
        exact = self.references(self.context(graph), "function", **{"STATUS": "external"})
        self.assertEqual(exact.result["references"][0]["reference"]["id"], "z")
        impossible = self.references(self.context(graph), "class",
                                     **{"REFERENCE-TYPE": "call", "STATUS": "exact"})
        self.assertEqual(impossible.completeness.total, 0)
        self.assertEqual([x["reference_type"] for x in
                          self.references(self.context(graph), "module").result["references"]],
                         ["call", "import"])
        self.assertEqual(len(self.references(self.context(graph), "method").result["references"]), 1)

    def test_all_resolution_forms_and_type_field_owner(self):
        graph = self.canonical()
        graph["callsites"] = [self.call_ref(status=status) for status in
                              ("exact", "ambiguous", "external", "dynamic", "unresolved")]
        for index, ref in enumerate(graph["callsites"]): ref["id"] = str(index)
        graph["type_references"] = [self.type_ref("field-ref", "field", role="field_type")]
        result = self.references(self.context(graph))
        self.assertEqual([x["reference"]["resolution"] for x in result.result["references"]],
                         ["exact", "ambiguous", "external", "dynamic", "unresolved"])
        self.assertEqual(len(self.references(self.context(graph), "field").result["references"]), 1)

    def test_optional_call_and_type_resolution_fields_follow_producer_defaults(self):
        cases = []
        for kind, factory, statuses in (("callsites", self.call_ref,
                                         ("exact", "ambiguous", "external", "dynamic", "unresolved")),
                                        ("type_references", self.type_ref,
                                         ("exact", "ambiguous", "external", "unresolved"))):
            for status in statuses:
                ref = factory(status=status)
                if status == "exact":
                    ref.pop("candidate_ids")
                elif status == "ambiguous":
                    ref.pop("target_id")
                else:
                    ref.pop("target_id"); ref.pop("candidate_ids")
                cases.append((kind, ref))
        for collection, ref in cases:
            graph = self.canonical(); graph[collection] = [ref]
            with self.subTest(collection=collection, status=ref["resolution"]):
                self.assertEqual(len(self.references(self.context(graph),
                                                     ref.get("caller_id", ref.get("owner_id"))).result["references"]), 1)

    def test_reference_collections_follow_parser_semantics_history(self):
        cases = ((1, ("type_references", "import_references"), "function"),
                 (2, ("import_references",), "class"),
                 (3, ("import_references",), "class"))
        for semantics, missing, owner in cases:
            graph = self.canonical(); graph["parser_semantics_version"] = semantics
            graph["callsites"] = [self.call_ref()]
            if semantics > 1:
                graph["type_references"] = [self.type_ref()]
            for field in missing:
                del graph[field]
            with self.subTest(semantics=semantics):
                self.assertTrue(self.references(self.context(graph), owner).result["references"])
        graph = self.canonical(); graph["parser_semantics_version"] = 4
        del graph["import_references"]
        self.assertEqual(self.references(self.context(graph)).diagnostics[0].code, "invalid_artifact")
        graph = self.canonical(); del graph["parser_semantics_version"]
        self.assertEqual(self.references(self.context(graph)).diagnostics[0].code, "invalid_artifact")
        for semantics in (True, 0, 8, "1"):
            graph = self.canonical(); graph["parser_semantics_version"] = semantics
            with self.subTest(invalid_semantics=semantics):
                self.assertEqual(self.references(self.context(graph)).diagnostics[0].code,
                                 "invalid_artifact")

    def test_reference_limit_counts_determinism_and_deepcopy(self):
        graph = self.canonical()
        graph["callsites"] = [self.call_ref("b"), self.call_ref("a")]
        graph["callsites"][0]["metadata"] = {"items": [1]}
        with patch("tools_engine.tools.get_graph_references.RULES_CONFIG.max_graph_references_limit", 1):
            result = self.references(self.context(graph))
        self.assertEqual(result.result["references"][0]["reference"]["id"], "a")
        self.assertEqual(result.result["counts"]["call"], {"total": 2, "returned": 1})
        self.assertTrue(result.completeness.truncated)
        context = self.context(graph)
        first = self.references(context); first.result["references"][1]["reference"]["metadata"]["items"].append(2)
        self.assertEqual(self.references(context).result["references"][1]["reference"]["metadata"],
                         {"items": [1]})

    def test_reference_invariants_are_rejected_without_path_leak(self):
        cases = []
        for field, value in (("expression", ""), ("syntactic_depth", -1),
                             ("syntactic_depth", True), ("awaited", 1),
                             ("candidate_ids", ["class"]), ("target_id", "class")):
            ref = self.call_ref(); ref[field] = value; cases.append(("callsites", ref))
        ref = self.call_ref(status="ambiguous"); ref["candidate_ids"] = ["method"]; cases.append(("callsites", ref))
        for field, value in (("kind", "bad"), ("module", None), ("name", ""),
                             ("alias", ""), ("level", True), ("candidate_ids", ["module"]),
                             ("target_id", "class"), ("importer_id", "class")):
            ref = self.import_ref(); ref[field] = value; cases.append(("import_references", ref))
        for field, value in (("role", "bad"), ("expression", ""), ("owner_id", "file"),
                             ("target_id", "method"), ("candidate_ids", ["method", "other"])):
            ref = self.type_ref(); ref[field] = value; cases.append(("type_references", ref))
        bad_location = self.call_ref(); bad_location["location"] = {"path": str(self.root), "line": 1, "column": 0}
        cases.append(("callsites", bad_location))
        missing_target = self.call_ref(); missing_target["target_id"] = "missing"; cases.append(("callsites", missing_target))
        unknown_candidate = self.call_ref(status="ambiguous"); unknown_candidate["candidate_ids"] = ["method", "missing"]
        cases.append(("callsites", unknown_candidate))
        for collection, ref, field in (("callsites", self.call_ref(), "expression"),
                                       ("import_references", self.import_ref(), "alias"),
                                       ("type_references", self.type_ref(), "role")):
            del ref[field]
            cases.append((collection, ref))
        for collection, ref in cases:
            graph = self.canonical(); graph[collection] = [ref]
            with self.subTest(collection=collection, ref=ref):
                result = self.references(self.context(graph))
                self.assertEqual(result.diagnostics[0].code, "invalid_artifact")
                self.assertNotIn(str(self.root), result.to_json())

    def test_producer_import_spelling_resolution_and_location_invariants(self):
        cases = []
        for changes in (
                {"kind": "import", "module": "pkg"},
                {"kind": "import", "level": 1},
                {"kind": "import", "name": "*"},
                {"kind": "from", "module": "", "level": 0},
                {"resolution": "external", "level": 1, "target_id": None},
                {"resolution": "unresolved", "level": 0, "target_id": None},
                {"location": {"path": "pkg/other.py", "line": 1, "column": 0}},
        ):
            ref = self.import_ref()
            ref.update(changes)
            cases.append(ref)
        for ref in cases:
            graph = self.canonical()
            graph["import_references"] = [ref]
            with self.subTest(reference=ref):
                self.assertEqual(
                    self.references(self.context(graph), "file").diagnostics[0].code,
                    "invalid_artifact",
                )

    def test_reference_ids_must_be_unique_only_within_each_collection(self):
        graph = self.canonical()
        graph["callsites"] = [self.call_ref(), self.call_ref()]
        self.assertEqual(self.references(self.context(graph)).diagnostics[0].code,
                         "invalid_artifact")

    def test_unknown_owner_missing_canonical_utf8_and_corrupt_reference_limit(self):
        self.assertEqual(self.references(self.context(), "missing").diagnostics[0].code,
                         "node_not_found")
        base = self.context(); missing = AnalysisContext(1, {}, {}, base.source_index_path, "a" * 64, "b" * 64)
        self.assertEqual(self.references(missing).diagnostics[0].code, "profile_not_found")
        for value in (0, True, 1001):
            with patch("tools_engine.tools.get_graph_references.RULES_CONFIG.max_graph_references_limit", value):
                self.assertEqual(self.references(self.context()).diagnostics[0].code, "invalid_artifact")
        graph = self.canonical(); graph["callsites"] = [self.call_ref()]; graph["callsites"][0]["expression"] = "я" * 100
        with patch("tools_engine.logic.engine.RULES_CONFIG.max_tool_result_size", 200):
            self.assertEqual(self.references(self.context(graph)).diagnostics[0].code,
                             "extraction_limit_exceeded")

    def test_raw_cache_shared_and_result_cache_isolated(self):
        context = self.context()
        original = GraphAccessor._read
        calls = []
        def counted(accessor, profile):
            calls.append(profile)
            return original(accessor, profile)
        with patch.object(GraphAccessor, "_read", counted):
            self.subgraph(context, **{"DEPTH": 0})
            self.references(context, "file")
        self.assertEqual(calls, ["canonical.full"])
        second = self.context()
        self.subgraph(second, **{"DEPTH": 0})

    def test_registry_schema_visibility_hard_ceilings_and_legacy_module(self):
        definitions = tuple(item for item in TOOL_REGISTRY if item.name in {
            ToolName.Get_Graph_Subgraph, ToolName.Get_Graph_References})
        self.assertEqual(len(definitions), 2); validate_registry(definitions)
        schema = ToolData.model_validate_json(definitions[0].schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema.function.parameters.properties["DEPTH"].maximum, MAX_GRAPH_DEPTH)
        self.assertEqual(MAX_GRAPH_ITEM_LIMIT, 1000)
        for value in (True, 0, -1):
            with self.assertRaises(ValueError): _positive_int(value, "test")
        graph = self.canonical()
        found = self.call(self.context(graph), "FIND-GRAPH-NODES", {"QUERY": "module"})
        self.assertEqual(found.result["nodes"][0]["kind"], "module")
        got = self.call(self.context(graph), "GET-GRAPH-NODE", {"NODE-ID": "module"})
        self.assertEqual(got.result["kind"], "module")


if __name__ == "__main__":
    unittest.main()
