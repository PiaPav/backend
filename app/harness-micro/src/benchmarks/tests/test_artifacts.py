import hashlib
import json
import asyncio
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

import benchmarks.artifacts as artifacts_module
from benchmarks.artifacts import load_artifact_bundle, stage_artifact_bundle
from benchmarks.event import HarnessEventIdentity, build_harness_start_event
from benchmarks.runners import prepare_harness_input
from harness_service.harness_handler import (
    ArtifactDescriptor as ResultDescriptor, Claim, ClaimDisposition,
    DeliveryContext, DeliveryDecision, HarnessHandler, MaterializedInputs,
)
from harness_service.harness_runner import HarnessResult


GRAPH_FINGERPRINT = "a" * 64
PROJECT_FINGERPRINT = "b" * 64


def _write_opaque_export(root: Path) -> tuple[Path, dict[str, object]]:
    """Create opaque bytes only; this fixture is not a producer snapshot."""
    (root / "source").mkdir()
    (root / "source" / "module.py").write_bytes(b"opaque source")
    (root / "artifacts").mkdir()
    payloads = {
        "graph-full.bin": b"opaque graph full",
        "graph-overview.bin": b"opaque graph overview",
        "metrics-full.bin": b"opaque metrics full",
        "metrics-overview.bin": b"opaque metrics overview",
        "source-index.bin": b"opaque source index",
    }
    for name, content in payloads.items():
        (root / "artifacts" / name).write_bytes(content)

    def descriptor(name: str) -> dict[str, object]:
        content = payloads[name]
        return {"path": f"artifacts/{name}", "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "schema_version": 1}

    manifest: dict[str, object] = {
        "schema_version": 1,
        "producer": {"service": "producer", "version": "1.2.3"},
        "source": {"path": "source", "project_fingerprint": PROJECT_FINGERPRINT},
        "graph_profiles": {"parser_semantics_version": 7, "graph_fingerprint": GRAPH_FINGERPRINT,
                           "artifacts": {"canonical.full": descriptor("graph-full.bin"),
                                         "aggregate.overview": descriptor("graph-overview.bin")}},
        "metrics_profiles": {"metrics_semantics_version": 4, "graph_fingerprint": GRAPH_FINGERPRINT,
                             "artifacts": {"metrics.full": descriptor("metrics-full.bin"),
                                           "metrics.overview": descriptor("metrics-overview.bin")}},
        "source_index": {**descriptor("source-index.bin"), "project_fingerprint": PROJECT_FINGERPRINT},
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest


def _identity() -> HarnessEventIdentity:
    return HarnessEventIdentity("event-1", "2026-11-24T12:00:00Z", "correlation-1",
                                "cause-1", "tenant-1")


def test_load_stage_and_exact_public_event(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    original_index = (export / "artifacts" / "source-index.bin").read_bytes()
    destination = tmp_path / "staged"
    staged = stage_artifact_bundle(load_artifact_bundle(manifest_path), destination)

    event = build_harness_start_event(staged, _identity())

    assert staged.root == destination
    assert staged.source_root == destination / "source"
    assert set(event) == {"event_id", "event_type", "schema_version", "occurred_at",
                          "correlation_id", "causation_id", "tenant_id", "producer", "payload"}
    assert event["event_type"] == "harness.start.v1"
    assert event["producer"] == {"service": "producer", "version": "1.2.3"}
    payload = event["payload"]
    assert set(payload) == {"source_uri", "graph_profiles", "metrics_profiles", "source_index"}
    assert not ({"graph_uri", "metrics_uri", "artifact_uri"} & set(payload))
    assert set(payload["graph_profiles"]["artifacts"]) == {"canonical.full", "aggregate.overview"}
    assert set(payload["metrics_profiles"]["artifacts"]) == {"metrics.full", "metrics.overview"}
    assert all(item["uri"].startswith("file:") for item in payload["graph_profiles"]["artifacts"].values())
    assert (export / "artifacts" / "source-index.bin").read_bytes() == original_index


def test_prepare_returns_recursively_immutable_event(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    prepared = prepare_harness_input(manifest_path, tmp_path / "staged", _identity())
    first_wire = prepared.wire_event()
    wire = json.dumps(first_wire)

    assert json.loads(wire) == first_wire
    with pytest.raises(TypeError):
        prepared.event["event_id"] = "changed"
    with pytest.raises(TypeError):
        prepared.event["payload"]["source_uri"] = "changed"
    first_wire["event_id"] = "changed"
    first_wire["payload"]["graph_profiles"]["artifacts"].pop("canonical.full")
    assert prepared.wire_event()["event_id"] == "event-1"
    assert "canonical.full" in prepared.wire_event()["payload"]["graph_profiles"]["artifacts"]


@pytest.mark.parametrize("mutation", [
    lambda value: value["graph_profiles"]["artifacts"].pop("canonical.full"),
    lambda value: value["metrics_profiles"].update(metrics_semantics_version=3),
    lambda value: value["metrics_profiles"].update(graph_fingerprint="c" * 64),
    lambda value: value["source_index"].update(project_fingerprint="c" * 64),
    lambda value: value.update(unexpected=True),
    lambda value: value["source_index"].update(size_bytes=True),
])
def test_manifest_contract_rejections(tmp_path: Path, mutation) -> None:
    manifest_path, manifest = _write_opaque_export(tmp_path)
    mutation(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)


@pytest.mark.parametrize("bad_path", ["../escape", "a\\b", "/absolute", "C:/absolute", "a/./b"])
def test_unsafe_artifact_paths_are_rejected(tmp_path: Path, bad_path: str) -> None:
    manifest_path, manifest = _write_opaque_export(tmp_path)
    manifest["graph_profiles"]["artifacts"]["canonical.full"]["path"] = bad_path
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)


def test_hash_size_duplicate_and_existing_destination_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    manifest_path, manifest = _write_opaque_export(first)
    manifest["graph_profiles"]["artifacts"]["canonical.full"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)

    second = tmp_path / "second"
    second.mkdir()
    manifest_path, manifest = _write_opaque_export(second)
    manifest["metrics_profiles"]["artifacts"]["metrics.full"] = manifest["graph_profiles"]["artifacts"]["canonical.full"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)

    third = tmp_path / "third"
    third.mkdir()
    manifest_path, _ = _write_opaque_export(third)
    bundle = load_artifact_bundle(manifest_path)
    (third / "staged").mkdir()
    with pytest.raises(ValueError):
        stage_artifact_bundle(bundle, third / "staged")


def test_source_and_artifact_symlinks_are_rejected(tmp_path: Path) -> None:
    manifest_path, manifest = _write_opaque_export(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    source_link = tmp_path / "source" / "link.bin"
    try:
        source_link.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit symlink creation")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)
    source_link.unlink()
    artifact = tmp_path / "artifacts" / "graph-full.bin"
    artifact.unlink()
    artifact.symlink_to(outside)
    content = outside.read_bytes()
    manifest["graph_profiles"]["artifacts"]["canonical.full"].update(
        sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_artifact_bundle(manifest_path)


def test_manifest_itself_symlink_is_rejected(tmp_path: Path) -> None:
    manifest_path, _ = _write_opaque_export(tmp_path)
    real_manifest = tmp_path / "real-manifest.json"
    manifest_path.rename(real_manifest)
    try:
        manifest_path.symlink_to(real_manifest)
    except OSError as error:
        pytest.skip(f"OS does not permit symlink creation: {error}")
    with pytest.raises(ValueError, match="manifest must be an ordinary file"):
        load_artifact_bundle(manifest_path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_source_directory_junction_is_rejected(tmp_path: Path) -> None:
    manifest_path, _ = _write_opaque_export(tmp_path)
    source = tmp_path / "source"
    external_source = tmp_path / "external-source"
    source.rename(external_source)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(source), str(external_source)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"creating a junction is unavailable: {result.stderr or result.stdout}")
    try:
        assert source.is_junction()
        with pytest.raises(ValueError):
            load_artifact_bundle(manifest_path)
    finally:
        os.rmdir(source)


def test_artifact_mutation_after_load_aborts_and_cleans_staging(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    bundle = load_artifact_bundle(manifest_path)
    bundle.graph_artifacts["canonical.full"].path.write_bytes(b"mutated after load")
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="size or SHA-256"):
        stage_artifact_bundle(bundle, destination)

    assert not destination.exists()


def test_staging_race_never_removes_foreign_destination(tmp_path: Path, monkeypatch) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    bundle = load_artifact_bundle(manifest_path)
    destination = tmp_path / "staged"
    original_rename = Path.rename

    def raced_rename(path, target):
        if target == destination:
            destination.mkdir()
            (destination / "foreign.marker").write_text("owned elsewhere", encoding="utf-8")
            try:
                return original_rename(path, target)
            except OSError as error:
                raise FileExistsError(destination) from error
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", raced_rename)
    with pytest.raises(FileExistsError):
        stage_artifact_bundle(bundle, destination)
    assert (destination / "foreign.marker").read_text(encoding="utf-8") == "owned elsewhere"
    assert list(tmp_path.glob(".staged-*")) == []


def test_staging_is_validated_before_atomic_publication(tmp_path: Path, monkeypatch) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    bundle = load_artifact_bundle(manifest_path)
    destination = tmp_path / "staged"
    original_validate = artifacts_module.validate_staged_bundle
    original_rename = Path.rename
    validated = False

    def recording_validate(staged):
        nonlocal validated
        original_validate(staged)
        validated = True

    def ordered_rename(path, target):
        if target == destination:
            assert validated
        return original_rename(path, target)

    monkeypatch.setattr(artifacts_module, "validate_staged_bundle", recording_validate)
    monkeypatch.setattr(Path, "rename", ordered_rename)

    staged = stage_artifact_bundle(bundle, destination)

    assert staged.root == destination


def test_failure_after_atomic_publication_does_not_remove_destination(tmp_path: Path, monkeypatch) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    bundle = load_artifact_bundle(manifest_path)
    destination = tmp_path / "staged"
    original_relative_to = Path.relative_to

    def fail_after_publication(path, *other, **kwargs):
        if destination.exists() and path != destination:
            raise RuntimeError("failure after publication")
        return original_relative_to(path, *other, **kwargs)

    monkeypatch.setattr(Path, "relative_to", fail_after_publication)

    with pytest.raises(RuntimeError, match="failure after publication"):
        stage_artifact_bundle(bundle, destination)

    assert destination.is_dir()
    assert (destination / "source" / "module.py").read_bytes() == b"opaque source"
    assert list(tmp_path.glob(".staged-*")) == []


def test_staging_destination_inside_source_is_rejected(tmp_path: Path) -> None:
    manifest_path, _ = _write_opaque_export(tmp_path)
    bundle = load_artifact_bundle(manifest_path)
    with pytest.raises(ValueError, match="outside the producer bundle"):
        stage_artifact_bundle(bundle, bundle.source_root / "staged")


def test_staged_artifact_mutation_is_rejected_before_event_build(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    staged = stage_artifact_bundle(load_artifact_bundle(manifest_path), tmp_path / "staged")
    staged.metrics_artifacts["metrics.full"].path.write_bytes(b"mutated while staged")

    with pytest.raises(ValueError, match="size or SHA-256"):
        build_harness_start_event(staged, _identity())


def test_manually_constructed_staged_bundle_cannot_escape_root(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    staged = stage_artifact_bundle(load_artifact_bundle(manifest_path), tmp_path / "staged")
    invalid = replace(staged, source_root=tmp_path)
    with pytest.raises(ValueError, match="inside staged root"):
        build_harness_start_event(invalid, _identity())


def test_staged_intermediate_symlink_is_rejected_before_event_build(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    staged = stage_artifact_bundle(load_artifact_bundle(manifest_path), tmp_path / "staged")
    artifacts = staged.root / "artifacts"
    external = tmp_path / "external-artifacts"
    artifacts.rename(external)
    try:
        artifacts.symlink_to(external, target_is_directory=True)
    except OSError as error:
        external.rename(artifacts)
        pytest.skip(f"OS does not permit symlink creation: {error}")
    with pytest.raises(ValueError, match="link-like"):
        build_harness_start_event(staged, _identity())


@pytest.mark.parametrize("timestamp", [
    "2026-11-24T12:00:00+00:00",
    "2026-02-30T12:00:00Z",
    "2026-11-24 12:00:00Z",
    "2026-11-24T12:00:00z",
])
def test_identity_rejects_malformed_timestamp(timestamp: str) -> None:
    with pytest.raises(ValueError, match="occurred_at must be UTC RFC 3339"):
        HarnessEventIdentity("event", timestamp, "correlation", "cause", "tenant")


def test_prepared_event_passes_real_handler_profile_branch_offline(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    manifest_path, _ = _write_opaque_export(export)
    prepared = prepare_harness_input(manifest_path, tmp_path / "staged", _identity())

    class Materializer:
        @contextmanager
        def materialize(self, **descriptors):
            graph = {key: item.path for key, item in prepared.bundle.graph_artifacts.items()}
            metrics = {key: item.path for key, item in prepared.bundle.metrics_artifacts.items()}
            yield MaterializedInputs(graph, metrics, prepared.bundle.source_index.path,
                                     prepared.bundle.graph_fingerprint,
                                     prepared.bundle.project_fingerprint)

    class Runner:
        request = None

        async def execute(self, request):
            self.request = request
            assert len(request.graph_profiles) + len(request.metrics_profiles) == 4
            return HarnessResult('{"issues":[],"strengths":[]}')

    class Store:
        content = None

        async def save(self, **values):
            self.content = values["content"]
            return ResultDescriptor("memory://result", "d" * 64, len(self.content), 1)

    class Idempotency:
        async def claim(self, **values):
            return Claim(ClaimDisposition.NEW, "claim")

        async def save_output(self, **values):
            self.output = values["output_event"]

        async def mark_published(self, **values):
            self.published = True

    class Publisher:
        events = []

        async def publish(self, event):
            self.events.append(event)

    runner, store, state, publisher = Runner(), Store(), Idempotency(), Publisher()
    handler = HarnessHandler(runner=runner, materializer=Materializer(), result_store=store,
                             idempotency=state, publisher=publisher)

    decision = asyncio.run(handler.handle(prepared.wire_event(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.ACK
    assert set(runner.request.graph_profiles) == {"canonical.full", "aggregate.overview"}
    assert set(runner.request.metrics_profiles) == {"metrics.full", "metrics.overview"}
    assert json.loads(store.content) == {"issues": [], "strengths": []}
    assert publisher.events[0]["event_type"] == "harness.completed.v1"
