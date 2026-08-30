"""Analyze a configured Python project and create its interactive graph."""

from __future__ import annotations

from pathlib import Path

if __package__:
    from .graph_metrics import (
        calculate_graph_metrics,
        format_graph_metrics,
        save_graph_metrics,
    )
    from .parser import (
        save_graph,
        save_source_index,
        starter_with_source_index,
        visualize_graph,
    )
else:
    # Allows direct execution: `python gpt_work_dir/analyze_project.py`.
    from graph_metrics import (
        calculate_graph_metrics,
        format_graph_metrics,
        save_graph_metrics,
    )
    from parser import (
        save_graph,
        save_source_index,
        starter_with_source_index,
        visualize_graph,
    )


# Укажите здесь корневую директорию анализируемого Python-проекта.
# Рекомендуется использовать абсолютный путь: Path(r"C:\projects\my_project")
PROJECT_PATH = Path(r"C:\Users\Red0c\PycharmProjects\PiaPav\backend\app\core\src")

# Итоговый файл будет создан рядом с этим скриптом.
OUTPUT_HTML = Path(__file__).with_name("project_graph.html")

# Полные метрики проекта будут сохранены в этот JSON-файл.
OUTPUT_METRICS = Path(__file__).with_name("graph_metrics.json")

# Индекс координат исходного кода для последующего быстрого поиска.
OUTPUT_SOURCE_INDEX = Path(__file__).with_name("source_index.json")

# Открыть результат в браузере сразу после анализа.
OPEN_BROWSER = False


def build_project_graph(
    project_path: str | Path,
    output_html: str | Path,
    output_metrics: str | Path,
    *,
    output_source_index: str | Path | None = None,
    open_browser: bool = False,
) -> Path:
    """Analyze ``project_path`` and write its interactive graph."""
    graph, source_index = starter_with_source_index(Path(project_path))
    save_graph(graph, Path.cwd() / "graph.json")
    save_source_index(
        source_index,
        output_source_index or (Path.cwd() / "source_index.json"),
    )
    metrics = calculate_graph_metrics(graph)
    save_graph_metrics(metrics, output_metrics)
    print("Метрики проекта:")
    print(format_graph_metrics(metrics))
    return visualize_graph(graph, output_html, open_browser=open_browser)


def main() -> int:
    project_path = PROJECT_PATH.expanduser().resolve()
    output_html = OUTPUT_HTML.expanduser().resolve()
    output_metrics = OUTPUT_METRICS.expanduser().resolve()
    output_source_index = OUTPUT_SOURCE_INDEX.expanduser().resolve()

    print(f"Анализ проекта: {project_path}")
    result = build_project_graph(
        project_path,
        output_html,
        output_metrics,
        output_source_index=output_source_index,
        open_browser=OPEN_BROWSER,
    )
    print(f"Граф создан: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
