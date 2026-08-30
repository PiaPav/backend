from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gpt_work_dir import optimize_metrics
from gpt_work_dir.graph_metrics import (
    compact_graph_metrics,
    restore_graph_metrics,
    save_graph_metrics,
)


class MetricsSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics = {
            "size": {"files": 2, "classes": 0},
            "ranked": [
                {"name": "service.create", "score": 1.25, "lcom": None},
                {"name": "service.update", "score": 0.0, "lcom": None},
                {"name": "service.delete", "score": 0.75, "lcom": None},
            ],
            "cycles": [],
        }

    def test_compaction_is_lossless_and_packs_repeated_objects(self) -> None:
        compact = compact_graph_metrics(self.metrics)

        self.assertIn("$columns", compact["ranked"])
        self.assertEqual(restore_graph_metrics(compact), self.metrics)

    def test_files_are_utf8_and_optimized_output_is_smaller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "graph_metrics.json"
            target = Path(directory) / "graph_metrics.optimized.json"

            save_graph_metrics(self.metrics, source)
            optimize_metrics.optimize_metrics_file(source, target)

            self.assertEqual(json.loads(source.read_text(encoding="utf-8")), self.metrics)
            self.assertLess(target.stat().st_size, source.stat().st_size)

    def test_script_main_uses_constants_without_cli_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            target = Path(directory) / "output.json"
            save_graph_metrics(self.metrics, source)

            output = StringIO()
            with (
                patch.object(optimize_metrics, "INPUT_METRICS", source),
                patch.object(optimize_metrics, "OUTPUT_METRICS", target),
                redirect_stdout(output),
            ):
                exit_code = optimize_metrics.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(target.is_file())
            self.assertIn("Примерно токенов:", output.getvalue())

    def test_token_estimate_uses_utf8_byte_length(self) -> None:
        self.assertEqual(optimize_metrics.estimate_token_count(""), 0)
        self.assertEqual(optimize_metrics.estimate_token_count("12345"), 2)
        self.assertEqual(optimize_metrics.estimate_token_count("тест"), 2)


if __name__ == "__main__":
    unittest.main()
