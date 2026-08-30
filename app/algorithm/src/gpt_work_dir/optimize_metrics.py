"""Create a compact graph-metrics JSON for use in an LLM prompt."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

if __package__:
    from .graph_metrics import save_compact_graph_metrics
else:
    # Allows direct execution: `python gpt_work_dir/optimize_metrics.py`.
    from graph_metrics import save_compact_graph_metrics


# Укажите здесь пути к исходным и оптимизированным метрикам.
INPUT_METRICS = Path(__file__).with_name("graph_metrics.json")
OUTPUT_METRICS = Path(__file__).with_name("graph_metrics.optimized.json")


def estimate_token_count(text: str) -> int:
    """Estimate token count as one token per four UTF-8 bytes."""
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / 4)


def optimize_metrics_file(input_path: str | Path, output_path: str | Path) -> Path:
    """Read metrics JSON and write its lossless compact representation."""
    source = Path(input_path)
    metrics: Any = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict):
        raise ValueError("Metrics JSON root must be an object")
    return save_compact_graph_metrics(metrics, output_path)


def main() -> int:
    input_path = INPUT_METRICS.expanduser().resolve()
    output_path = OUTPUT_METRICS.expanduser().resolve()
    result = optimize_metrics_file(input_path, output_path)
    source_size = input_path.stat().st_size
    result_size = result.stat().st_size
    saved_percent = (1 - result_size / source_size) * 100 if source_size else 0.0
    source_tokens = estimate_token_count(input_path.read_text(encoding="utf-8"))
    result_tokens = estimate_token_count(result.read_text(encoding="utf-8"))
    saved_tokens = source_tokens - result_tokens
    token_percent = (saved_tokens / source_tokens) * 100 if source_tokens else 0.0
    print(f"Оптимизированные метрики: {result}")
    print(f"Размер: {source_size} -> {result_size} байт ({saved_percent:.1f}% экономии)")
    print(
        f"Примерно токенов: {source_tokens} -> {result_tokens} "
        f"(−{saved_tokens}, {token_percent:.1f}% экономии)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
