"""Only public core APIs cross the service boundary."""
import asyncio
import tempfile
from pathlib import Path

from graph_dto import graph_fingerprint
from metrics import calculate_metrics, load_graph

from .contracts import PermanentError


class CoreMetricsEngine:
    async def calculate(self, raw: bytes, descriptor: dict) -> bytes:
        return await asyncio.to_thread(self._calculate, raw, descriptor)

    @staticmethod
    def _calculate(raw: bytes, descriptor: dict) -> bytes:
        with tempfile.TemporaryDirectory(prefix="metrics-") as directory:
            source, target = Path(directory) / "graph.json", Path(directory) / "metrics.json"
            source.write_bytes(raw)
            try:
                graph = load_graph(source)
                if (graph["schema_version"] != descriptor["schema_version"]
                        or graph["parser_semantics_version"] != descriptor["parser_semantics_version"]
                        or graph_fingerprint(graph) != descriptor["graph_fingerprint"]):
                    raise PermanentError("graph metadata mismatch")
                calculate_metrics(source, target)
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                raise PermanentError("invalid graph or incompatible core input") from exc
            return target.read_bytes()
