from __future__ import annotations

import json
import unittest
from pathlib import Path

from gpt_work_dir.parser.logic.errors import SourceSyntaxError
from gpt_work_dir.parser.logic.main import starter

HERE = Path(__file__).resolve().parent


class ParserGoldenTests(unittest.TestCase):
    def test_project1_matches_the_complete_golden_graph(self) -> None:
        expected = json.loads(
            (HERE / "project1" / "graph" / "graph.json").read_text(encoding="utf-8")
        )
        self.assertEqual(starter(HERE / "project1" / "data"), expected)

    def test_output_is_deterministic(self) -> None:
        project = HERE / "project1" / "data"
        self.assertEqual(starter(project), starter(project))


class ParserEdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = starter(HERE / "edge_cases" / "data")
        cls.files = {
            (item["file"]["path"], item["file"]["name"]): item["file"]
            for item in cls.graph["body"]
        }

    def test_same_named_modules_are_resolved_by_full_path(self) -> None:
        imports = self.files[("", "main")]["imports"]
        self.assertEqual(imports[0]["path"], "a.models")
        self.assertEqual(imports[1]["path"], "b.models")
        self.assertEqual(imports[0]["asname"], "F")

    def test_file_directory_is_serialized_as_path_parts(self) -> None:
        self.assertEqual(self.files[("", "main")]["path_parts"], [])
        self.assertEqual(self.files[("a", "models")]["path_parts"], ["a"])

    def test_multilevel_abstract_class_is_classified(self) -> None:
        classes = {
            item["name"]: item for item in self.files[("", "models")]["classes"]
        }
        self.assertEqual(classes["Base"]["type"], "abstract")
        self.assertEqual(classes["Middle"]["type"], "abstract")
        self.assertEqual(classes["Concrete"]["type"], "class")
        helper = next(
            method for method in classes["Concrete"]["methods"] if method["name"] == "helper"
        )
        self.assertEqual(helper["args"][0]["value"], 1)
        self.assertEqual(helper["args"][1]["value"], True)

    def test_nested_and_repeated_calls_are_not_lost(self) -> None:
        function = next(
            item
            for item in self.files[("", "main")]["functions"]
            if item["name"] == "async_job"
        )
        consume = function["calls"][0]
        self.assertEqual(consume["object"], "consume")
        self.assertEqual(len(consume["args"]), 2)
        self.assertEqual(
            [item["value"]["object"] for item in consume["args"]],
            ["First.__init__", "First.__init__"],
        )
        self.assertEqual(
            [item["value"]["args"][0]["value"]["object"] for item in consume["args"]],
            ["Second.__init__", "Second.__init__"],
        )

    def test_constructor_type_propagates_to_method_call(self) -> None:
        calls = self.files[("", "main")]["calls"]
        self.assertEqual(
            [item["object"] for item in calls],
            ["Concrete.__init__", "Concrete.run"],
        )

    def test_module_constants_are_collected(self) -> None:
        constants = self.files[("", "main")]["constants"]
        self.assertEqual(
            [(item["name"], item["type"], item["value"]) for item in constants],
            [("API_NAME", "str", "edge-cases"), ("RETRIES", "int", 3)],
        )

    def test_syntax_error_contains_location(self) -> None:
        with self.assertRaises(SourceSyntaxError) as caught:
            starter(HERE / "syntax_error")
        self.assertEqual(caught.exception.path.name, "broken.py")
        self.assertEqual(caught.exception.line, 1)


if __name__ == "__main__":
    unittest.main()
