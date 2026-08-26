from __future__ import annotations

import json
import unittest
from pathlib import Path

from gpt_work_dir.analyze_project import build_project_graph
from gpt_work_dir.parser.logic.main import starter
from gpt_work_dir.parser.visualizer import graph_to_html

HERE = Path(__file__).resolve().parent


class VisualizerTests(unittest.TestCase):
    def test_combined_entrypoint_analyzes_project_and_writes_page(self) -> None:
        output = HERE / "project1" / "graph" / "graph.html"
        result = build_project_graph(
            HERE / "project1" / "data", output, open_browser=False
        )
        self.assertEqual(result, output.resolve())
        self.assertIn("file-group", output.read_text(encoding="utf-8"))

    def test_parser_result_is_embedded_in_standalone_page(self) -> None:
        graph = starter(HERE / "project1" / "data")
        page = graph_to_html(graph)
        self.assertIn("<!doctype html>", page.lower())
        self.assertIn('id="graph-data"', page)
        self.assertIn("SomeClass", page)
        self.assertIn("Показать целиком", page)
        self.assertIn("file-group", page)
        self.assertIn("data.constants", page)
        self.assertIn("'импортирует'", page)
        self.assertIn("moduleNodes", page)
        self.assertIn("directory-group", page)
        self.assertIn("path_parts", page)
        self.assertIn("layoutFolder", page)
        self.assertIn("startFolderDrag", page)
        self.assertIn("moveFolder", page)

    def test_module_constants_are_available_as_grouped_nodes(self) -> None:
        graph = starter(HERE / "edge_cases" / "data")
        page = graph_to_html(graph)
        self.assertIn("API_NAME", page)
        self.assertIn("RETRIES", page)
        self.assertIn("константа", page)

    def test_embedded_json_cannot_close_the_script_element(self) -> None:
        page = graph_to_html({"body": [], "unsafe": "</script><script>alert(1)</script>"})
        self.assertNotIn("</script><script>alert(1)</script>", page)
        payload = page.split('type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(payload)["unsafe"], "</script><script>alert(1)</script>")


if __name__ == "__main__":
    unittest.main()
