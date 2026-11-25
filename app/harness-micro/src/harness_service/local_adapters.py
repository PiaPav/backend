import hashlib
import json

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .harness_handler import (
    ArtifactDescriptor, Claim, ClaimDisposition, MaterializedInputs,
    PayloadConflictError, RejectedInputError,
)
# ДЛЯ КОНТЕЙНЕРА:
from views import materialize_graph_profile, materialize_metrics_profile


def resolve_uri(uri: str) -> Path:
    parsed = urlparse(uri)

    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif not parsed.scheme:
        path = Path(uri)
    else:
        raise RejectedInputError(f"Unsupported URI scheme: {parsed.scheme}")

    path = path.resolve()

    if not path.is_relative_to(Path("/data").resolve()):
        raise RejectedInputError("Path is outside /data")
    if not path.exists():
        raise RejectedInputError(f"Path not found: {path}")

    return path


def resolve_artifact(descriptor) -> Path:
    path = resolve_uri(descriptor.uri)

    if not path.is_file():
        raise RejectedInputError("Expected an artifact file")

    content = path.read_bytes()

    if len(content) != descriptor.size_bytes:
        raise RejectedInputError("Artifact size mismatch")
    if hashlib.sha256(content).hexdigest() != descriptor.sha256:
        raise RejectedInputError("Artifact checksum mismatch")

    return path

def save_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


class LocalInputMaterializer:

    @contextmanager
    def materialize(self, *, source_uri, graph_profiles, metrics_profiles, source_index):
        source_root = resolve_uri(source_uri)
        graph_paths = {name: resolve_artifact(desc) for name, desc in graph_profiles.artifacts.items()}
        metrics_paths = {name: resolve_artifact(desc) for name, desc in metrics_profiles.artifacts.items()}
        index_path = resolve_artifact(source_index)

        with TemporaryDirectory() as temp:
            root = Path(temp)

            if "aggregate.overview" not in graph_paths:
                graph = json.loads(graph_paths["canonical.full"].read_text(encoding="utf-8"))
                overview = materialize_graph_profile(graph, profile_id="aggregate.overview", profile_version=1)
                graph_paths["aggregate.overview"] = save_json(root / "graph_overview.json", overview)

            if "metrics.overview" not in metrics_paths:
                metrics = json.loads(metrics_paths["metrics.full"].read_text(encoding="utf-8"))
                overview = materialize_metrics_profile(metrics, profile_id="metrics.overview", profile_version=1)
                metrics_paths["metrics.overview"] = save_json(root / "metrics_overview.json", overview)

            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["project"]["root"] = str(source_root)
            local_index = save_json(root / "source_index.json", index)

            yield MaterializedInputs(
                graph_paths, metrics_paths, local_index,
                graph_profiles.graph_fingerprint, source_index.project_fingerprint,
            )


class LocalResultStore:

    def __init__(self, root: Path):
        self.root = root

    async def save(self, *, tenant_id: str, event_id: str, content: str) -> ArtifactDescriptor:
        key = hashlib.sha256(f"{tenant_id}\0{event_id}".encode()).hexdigest()
        directory = self.root / key
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / "result.json"
        raw = content.encode("utf-8")
        path.write_bytes(raw)

        return ArtifactDescriptor(path.resolve().as_uri(), hashlib.sha256(raw).hexdigest(), len(raw), 1)


class InMemoryIdempotencyStore:

    def __init__(self):
        self.records = {}

    async def claim(self, *, key, payload_digest):
        record = self.records.get(key)

        if record is not None:
            if record["digest"] != payload_digest:
                raise PayloadConflictError("Event payload has changed")
            if record["state"] == "published":
                return Claim(ClaimDisposition.PUBLISHED, record["token"])
            if record["state"] == "saved":
                return Claim(ClaimDisposition.SAVED, record["token"], record["event"])

        token = str(uuid4())
        self.records[key] = {"digest": payload_digest, "token": token, "state": "claimed", "event": None}

        return Claim(ClaimDisposition.NEW, token)

    async def save_output(self, *, key, claim_token, output_event):
        record = self.records[key]

        if record["token"] != claim_token:
            raise RuntimeError("Invalid claim token")

        record["event"] = dict(output_event)
        record["state"] = "saved"

    async def mark_published(self, *, key, claim_token):
        record = self.records[key]

        if record["token"] != claim_token:
            raise RuntimeError("Invalid claim token")

        record["state"] = "published"