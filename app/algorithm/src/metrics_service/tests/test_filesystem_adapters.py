import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from metrics_service.adapters.filesystem import LocalGraphInputResolver, LocalMetricsArtifactStore, LocalMetricsStagingArea
import metrics_service.adapters.filesystem as filesystem
from metrics_service.application.errors import (ArtifactConflictError, ArtifactStoreUnavailableError,
                                                GraphNotFoundError, StagingUnavailableError,
                                                UnsupportedUriSchemeError)


def test_graph_resolver_requires_contained_regular_file(tmp_path):
    graph = tmp_path / "graph.json"; graph.write_bytes(b"{}")
    resolver = LocalGraphInputResolver(tmp_path)
    with resolver.materialize(graph.as_uri()) as resolved: assert resolved == graph.resolve()
    with pytest.raises(GraphNotFoundError): resolver.materialize(tmp_path.as_uri()).__enter__()
    for uri in ("s3://bucket/graph", graph.as_uri() + "#fragment", "file://remote/graph"):
        with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(uri).__enter__()


def test_metrics_staging_and_store_are_immutable(tmp_path):
    stage = tmp_path / "stage"; stage.mkdir(); root = tmp_path / "root"; root.mkdir()
    key = "metrics/" + "b" * 64; staging = LocalMetricsStagingArea(stage); store = LocalMetricsArtifactStore(root)
    with staging.create_target(key) as target:
        target.write_bytes(b"metrics"); descriptor = store.save(target, key)
    assert not target.exists() and descriptor.sha256 == hashlib.sha256(b"metrics").hexdigest()
    with staging.create_target(key) as target:
        target.write_bytes(b"other")
        with pytest.raises(ArtifactConflictError): store.save(target, key)
    assert (root / "metrics" / ("b" * 64 + ".json")).read_bytes() == b"metrics"


def test_graph_uri_matrix_containment_and_type(tmp_path):
    graph = tmp_path / "граф.json"; graph.write_bytes(b"{}")
    resolver = LocalGraphInputResolver(tmp_path)
    with resolver.materialize(graph.as_uri().replace("file:///", "file://localhost/")) as path:
        assert path == graph.resolve()
    directory = tmp_path / "directory"; directory.mkdir()
    with pytest.raises(GraphNotFoundError): resolver.materialize(directory.as_uri()).__enter__()
    outside = tmp_path.parent / "outside-metrics.json"; outside.write_bytes(b"{}")
    with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(outside.as_uri()).__enter__()
    for uri in ("relative.json", graph.as_uri() + "?x=1", graph.as_uri() + "#x",
                "file://server/share", "https://localhost/x"):
        with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(uri).__enter__()
    link = tmp_path / "escape.json"
    try: link.symlink_to(outside)
    except OSError as error: pytest.skip(f"file symlinks unsupported: {error}")
    with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(link.as_uri()).__enter__()


@pytest.mark.parametrize("key", ["metrics/" + "B" * 64, "metrics/" + "b" * 63,
                                  "metrics/" + "b" * 64 + "/x", "graph/" + "b" * 64])
def test_exact_key_validation(key, tmp_path):
    stage = tmp_path / "stage"; stage.mkdir(); root = tmp_path / "root"; root.mkdir()
    with pytest.raises(StagingUnavailableError): LocalMetricsStagingArea(stage).create_target(key).__enter__()
    source = tmp_path / "source"; source.write_bytes(b"x")
    with pytest.raises(ArtifactStoreUnavailableError): LocalMetricsArtifactStore(root).save(source, key)


def test_staging_unique_cleanup_and_concurrent_atomic_save(tmp_path):
    stage = tmp_path / "stage"; stage.mkdir(); key = "metrics/" + "e" * 64
    staging = LocalMetricsStagingArea(stage)
    with staging.create_target(key) as first:
        with staging.create_target(key) as second: assert first != second
    with pytest.raises(RuntimeError):
        with staging.create_target(key) as failed: raise RuntimeError("boom")
    assert not failed.exists()
    root = tmp_path / "root"; root.mkdir(); store = LocalMetricsArtifactStore(root); paths = []
    for index, data in enumerate((b"same", b"same", b"other")):
        path = tmp_path / f"input-{index}"; path.write_bytes(data); paths.append(path)
    store.save(paths[0], key)
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda path: _save_outcome(store, path, key), paths))
    assert outcomes.count("ok") == 2 and outcomes.count("conflict") == 1
    assert (root / "metrics" / ("e" * 64 + ".json")).read_bytes() == b"same"
    assert not list((root / "metrics").glob(".publish-*"))


def _save_outcome(store, path, key):
    try:
        store.save(path, key); return "ok"
    except ArtifactConflictError:
        return "conflict"


@pytest.mark.parametrize("suffix", ["%ZZ", "%", "%FF", "%00", "%2F", "%5C", "%01", "%7F",
                                    "%C2%85", "\t", "\r", "\n", "//child"])
def test_graph_uri_rejects_malformed_or_ambiguous_paths(tmp_path, suffix):
    graph = tmp_path / "unicode-граф.json"; graph.write_bytes(b"{}")
    resolver = LocalGraphInputResolver(tmp_path)
    with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(graph.as_uri() + suffix).__enter__()
    with resolver.materialize(graph.as_uri()) as resolved: assert resolved == graph.resolve()


def test_cleanup_failures_preserve_primary_and_hide_paths(tmp_path, monkeypatch):
    root = tmp_path / "stage"; root.mkdir(); key = "metrics/" + "1" * 64
    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("secret-path")))
    with pytest.raises(StagingUnavailableError):
        with LocalMetricsStagingArea(root).create_target(key): pass
    primary = RuntimeError("primary")
    with pytest.raises(RuntimeError) as caught:
        with LocalMetricsStagingArea(root).create_target(key): raise primary
    assert caught.value is primary and caught.value.__notes__ == ["Metrics staging cleanup was unavailable"]
    assert "secret-path" not in caught.value.__notes__[0]
    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_publish_cleanup_fsync_and_destination_type_guards(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"; root.mkdir(); source = tmp_path / "input"; source.write_bytes(b"new")
    key = "metrics/" + "2" * 64; destination = root / "metrics" / ("2" * 64 + ".json")
    calls = []; monkeypatch.setattr(filesystem, "_fsync_directory", lambda path: calls.append(Path(path)))
    LocalMetricsArtifactStore(root).save(source, key)
    assert calls == [root.resolve(), (root / "metrics").resolve()]
    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("private"))
                      if self.name.startswith(".publish-") else real_unlink(self, *a, **k))
    with pytest.raises(ArtifactStoreUnavailableError):
        LocalMetricsArtifactStore(root).save(source, "metrics/" + "3" * 64)
    source.write_bytes(b"different")
    with pytest.raises(ArtifactConflictError) as caught: LocalMetricsArtifactStore(root).save(source, key)
    assert caught.value.__notes__ == ["Metrics artifact cleanup was unavailable"]
    monkeypatch.setattr(Path, "unlink", real_unlink)
    outside = tmp_path / "outside"; outside.write_bytes(b"outside")
    destination.unlink(); destination.symlink_to(outside)
    with pytest.raises(ArtifactConflictError): LocalMetricsArtifactStore(root).save(source, key)
    assert outside.read_bytes() == b"outside"
    destination.unlink(); destination.mkdir()
    with pytest.raises(ArtifactConflictError): LocalMetricsArtifactStore(root).save(source, key)


def test_directory_fsync_failure_maps_and_windows_skip_is_explicit(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir(); source = tmp_path / "input"; source.write_bytes(b"x")
    real_fsync_directory = filesystem._fsync_directory
    monkeypatch.setattr(filesystem, "_fsync_directory", lambda path: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(ArtifactStoreUnavailableError):
        LocalMetricsArtifactStore(root).save(source, "metrics/" + "4" * 64)
    monkeypatch.setattr(filesystem.os, "name", "nt")
    monkeypatch.setattr(filesystem.os, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must skip")))
    real_fsync_directory(root)
