import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from parser_service.adapters.filesystem import LocalGraphArtifactStore, LocalGraphStagingArea, LocalSourceResolver
import parser_service.adapters.filesystem as filesystem
from parser_service.application.errors import (ArtifactConflictError, ArtifactStoreUnavailableError,
                                               SourceNotFoundError, StagingUnavailableError,
                                               UnsupportedUriSchemeError)


def test_source_resolver_accepts_contained_directory_and_rejects_unsafe_uris(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    resolver = LocalSourceResolver(tmp_path)
    with resolver.materialize(source.as_uri()) as resolved:
        assert resolved == source.resolve()
    for uri in ("https://example.test/source", source.as_uri() + "?secret=x", "file://remote/source"):
        with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(uri).__enter__()
    with pytest.raises(SourceNotFoundError): resolver.materialize((tmp_path / "missing").as_uri()).__enter__()


def test_staging_cleanup_and_immutable_store(tmp_path):
    staging_root = tmp_path / "stage"; staging_root.mkdir()
    artifact_root = tmp_path / "artifacts"; artifact_root.mkdir()
    key = "graph/" + "a" * 64
    staging = LocalGraphStagingArea(staging_root)
    with staging.create_target(key) as first:
        first.write_bytes(b"canonical"); saved = LocalGraphArtifactStore(artifact_root).save(first, key)
        assert first.exists()
    assert not first.exists()
    assert saved.sha256 == hashlib.sha256(b"canonical").hexdigest() and saved.size_bytes == 9
    with staging.create_target(key) as same:
        same.write_bytes(b"canonical"); assert LocalGraphArtifactStore(artifact_root).save(same, key) == saved
    with staging.create_target(key) as different:
        different.write_bytes(b"different")
        with pytest.raises(ArtifactConflictError): LocalGraphArtifactStore(artifact_root).save(different, key)
    assert (artifact_root / "graph" / ("a" * 64 + ".json")).read_bytes() == b"canonical"


def test_source_uri_matrix_containment_and_type(tmp_path):
    source = tmp_path / "данные"; source.mkdir()
    resolver = LocalSourceResolver(tmp_path)
    localhost_uri = source.as_uri().replace("file:///", "file://localhost/")
    with resolver.materialize(localhost_uri) as resolved: assert resolved == source.resolve()
    file_path = tmp_path / "file"; file_path.write_text("x")
    with pytest.raises(SourceNotFoundError): resolver.materialize(file_path.as_uri()).__enter__()
    outside = tmp_path.parent / "outside-parser"; outside.mkdir(exist_ok=True)
    with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(outside.as_uri()).__enter__()
    for uri in ("relative/path", source.as_uri() + "#x", source.as_uri() + "?x=1",
                "file://server/share", "http://localhost/path"):
        with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(uri).__enter__()
    link = tmp_path / "escape"
    try: link.symlink_to(outside, target_is_directory=True)
    except OSError as error: pytest.skip(f"directory symlinks unsupported: {error}")
    with pytest.raises(UnsupportedUriSchemeError): resolver.materialize(link.as_uri()).__enter__()


@pytest.mark.parametrize("key", ["graph/" + "A" * 64, "graph/" + "a" * 63,
                                  "graph/" + "a" * 64 + "/x", "metrics/" + "a" * 64])
def test_exact_key_validation(key, tmp_path):
    stage = tmp_path / "stage"; stage.mkdir(); artifacts = tmp_path / "artifacts"; artifacts.mkdir()
    with pytest.raises(StagingUnavailableError): LocalGraphStagingArea(stage).create_target(key).__enter__()
    source = tmp_path / "source"; source.write_bytes(b"x")
    with pytest.raises(ArtifactStoreUnavailableError): LocalGraphArtifactStore(artifacts).save(source, key)


def test_staging_unique_and_cleanup_on_exception(tmp_path):
    root = tmp_path / "stage"; root.mkdir(); staging = LocalGraphStagingArea(root); key = "graph/" + "c" * 64
    with staging.create_target(key) as first:
        with staging.create_target(key) as second: assert first != second
    with pytest.raises(RuntimeError):
        with staging.create_target(key) as failed:
            raise RuntimeError("boom")
    assert not failed.exists()


def test_concurrent_same_and_different_saves_are_atomic(tmp_path):
    root = tmp_path / "artifacts"; root.mkdir(); key = "graph/" + "d" * 64
    paths = []
    for index, data in enumerate((b"one", b"one", b"two")):
        path = tmp_path / f"input-{index}"; path.write_bytes(data); paths.append(path)
    store = LocalGraphArtifactStore(root)
    store.save(paths[0], key)
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda path: _save_outcome(store, path, key), paths))
    assert outcomes.count("ok") == 2 and outcomes.count("conflict") == 1
    assert (root / "graph" / ("d" * 64 + ".json")).read_bytes() == b"one"
    assert not list((root / "graph").glob(".publish-*"))


def _save_outcome(store, path, key):
    try:
        store.save(path, key); return "ok"
    except ArtifactConflictError:
        return "conflict"


@pytest.mark.parametrize("suffix", ["%ZZ", "%", "%FF", "%00", "%2F", "%5C", "%01", "%7F",
                                    "%C2%85", "\t", "\r", "\n", "//child"])
def test_source_uri_rejects_malformed_or_ambiguous_paths(tmp_path, suffix):
    source = tmp_path / "unicode-данные"; source.mkdir()
    resolver = LocalSourceResolver(tmp_path)
    with pytest.raises(UnsupportedUriSchemeError):
        resolver.materialize(source.as_uri() + suffix).__enter__()
    with resolver.materialize(source.as_uri()) as resolved:
        assert resolved == source.resolve()


def test_cleanup_failures_preserve_primary_and_hide_paths(tmp_path, monkeypatch):
    root = tmp_path / "stage"; root.mkdir(); key = "graph/" + "1" * 64
    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("secret-path")))
    with pytest.raises(StagingUnavailableError):
        with LocalGraphStagingArea(root).create_target(key): pass
    primary = RuntimeError("primary")
    with pytest.raises(RuntimeError) as caught:
        with LocalGraphStagingArea(root).create_target(key): raise primary
    assert caught.value is primary
    assert caught.value.__notes__ == ["Graph staging cleanup was unavailable"]
    assert "secret-path" not in caught.value.__notes__[0]
    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_publish_cleanup_fsync_and_destination_type_guards(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"; root.mkdir(); source = tmp_path / "input"; source.write_bytes(b"new")
    key = "graph/" + "2" * 64; destination = root / "graph" / ("2" * 64 + ".json")
    calls = []
    monkeypatch.setattr(filesystem, "_fsync_directory", lambda path: calls.append(Path(path)))
    descriptor = LocalGraphArtifactStore(root).save(source, key)
    assert descriptor.size_bytes == 3 and calls == [root.resolve(), (root / "graph").resolve()]
    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("private"))
                      if self.name.startswith(".publish-") else real_unlink(self, *a, **k))
    with pytest.raises(ArtifactStoreUnavailableError):
        LocalGraphArtifactStore(root).save(source, "graph/" + "3" * 64)
    source.write_bytes(b"different")
    with pytest.raises(ArtifactConflictError) as caught:
        LocalGraphArtifactStore(root).save(source, key)
    assert caught.value.__notes__ == ["Graph artifact cleanup was unavailable"]
    monkeypatch.setattr(Path, "unlink", real_unlink)
    outside = tmp_path / "outside"; outside.write_bytes(b"outside")
    destination.unlink(); destination.symlink_to(outside)
    with pytest.raises(ArtifactConflictError): LocalGraphArtifactStore(root).save(source, key)
    assert outside.read_bytes() == b"outside"
    destination.unlink(); destination.mkdir()
    with pytest.raises(ArtifactConflictError): LocalGraphArtifactStore(root).save(source, key)


def test_directory_fsync_failure_maps_and_windows_skip_is_explicit(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir(); source = tmp_path / "input"; source.write_bytes(b"x")
    real_fsync_directory = filesystem._fsync_directory
    monkeypatch.setattr(filesystem, "_fsync_directory", lambda path: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(ArtifactStoreUnavailableError):
        LocalGraphArtifactStore(root).save(source, "graph/" + "4" * 64)
    monkeypatch.setattr(filesystem.os, "name", "nt")
    monkeypatch.setattr(filesystem.os, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must skip")))
    real_fsync_directory(root)
