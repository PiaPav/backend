from pathlib import Path
import ast
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from benchmarks.project import load_project


PROJECT = Path(__file__).resolve().parents[1] / "projects" / "import_cycle"


def test_loads_real_project_as_immutable_oracle() -> None:
    oracle = load_project(PROJECT)
    assert oracle.project_id == "import_cycle"
    assert oracle.expected_findings[0].locations == (
        "package_a/service.py", "package_b/repository.py",
    )
    assert len(oracle.project_sha256) == 64
    with pytest.raises(AttributeError):
        oracle.project_id = "other"  # type: ignore[misc]


def test_project_digest_is_deterministic_and_covers_source(tmp_path: Path) -> None:
    copied = tmp_path / "import_cycle"
    shutil.copytree(PROJECT, copied)
    first = load_project(copied).project_sha256
    assert load_project(copied).project_sha256 == first
    source = copied / "project" / "app.py"
    source.write_bytes(source.read_bytes() + b"\n")
    assert load_project(copied).project_sha256 != first


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"creating symlinks is unavailable on this system: {exc}")


def test_rejects_external_file_symlink_before_digest_read(tmp_path: Path) -> None:
    copied = tmp_path / "import_cycle"
    shutil.copytree(PROJECT, copied)
    external = tmp_path / "external.py"
    external.write_text("must not be read", encoding="utf-8")
    link = copied / "project" / "external.py"
    _symlink_or_skip(link, external)

    with pytest.raises(ValueError, match="project entry.*symlink|symlink.*project entry"):
        load_project(copied)


def test_rejects_symlink_used_as_project_directory(tmp_path: Path) -> None:
    copied = tmp_path / "import_cycle"
    shutil.copytree(PROJECT, copied)
    external_project = tmp_path / "external_project"
    (copied / "project").rename(external_project)
    _symlink_or_skip(copied / "project", external_project, target_is_directory=True)

    with pytest.raises(ValueError, match="project directory.*symlink|symlink.*project directory"):
        load_project(copied)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_rejects_junction_used_as_project_directory(tmp_path: Path) -> None:
    copied = tmp_path / "import_cycle"
    shutil.copytree(PROJECT, copied)
    external_project = tmp_path / "external_project"
    junction = copied / "project"
    junction.rename(external_project)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(external_project)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"creating a junction is unavailable: {result.stderr or result.stdout}")
    try:
        assert junction.is_junction()
        with pytest.raises(ValueError, match="project directory.*junction|junction.*project directory"):
            load_project(copied)
    finally:
        os.rmdir(junction)


def test_real_project_contains_static_cycle_without_executing_imports() -> None:
    project_root = PROJECT / "project"

    def imported_modules(relative_path: str) -> set[str]:
        tree = ast.parse((project_root / relative_path).read_text(encoding="utf-8"))
        return {
            f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
            for alias in node.names
        }

    assert "package_b.repository" in imported_modules("package_a/service.py")
    assert "package_a.service" in imported_modules("package_b/repository.py")


def _mutated_card(tmp_path: Path, mutate: object) -> Path:
    copied = tmp_path / "import_cycle"
    shutil.copytree(PROJECT, copied)
    card_path = copied / "benchmark.yml"
    card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    mutate(card)
    card_path.write_text(yaml.safe_dump(card, sort_keys=False), encoding="utf-8")
    return copied


@pytest.mark.parametrize("mutate,match", [
    (lambda card: card.update(project_id="wrong"), "directory name"),
    (lambda card: card["expected_findings"].append(card["expected_findings"][0].copy()), "duplicated"),
    (lambda card: card["expected_findings"][0].update(severity_min="critical"), "exceeds"),
    (lambda card: card["expected_findings"][0].update(locations=["../app.py"]), "POSIX"),
    (lambda card: card["expected_findings"][0].update(locations=["missing.py"]), "project file"),
    (lambda card: card["expected_findings"][0]["required_data"].update(metrics=True),
     r"required_data\.metrics=true requires evidence\.metrics"),
    (lambda card: card["expected_findings"][0]["evidence"].update(relations=[]),
     r"required_data\.graph=true requires evidence\.graph"),
    (lambda card: card["expected_findings"][0]["required_data"].update(source=True),
     r"required_data\.source=true requires evidence\.source"),
    (lambda card: card["expected_findings"][0].update(forbidden_claims=["CYCLIC DEPENDENCY"]), "overlaps"),
    (lambda card: card.update(description="  "), "whitespace-only"),
])
def test_semantic_rejections(tmp_path: Path, mutate: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_project(_mutated_card(tmp_path, mutate))  # type: ignore[arg-type]
